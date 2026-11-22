import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from parakh import __version__, cli
from parakh import run as run_module
from parakh.cli import app
from parakh.degrade.presets import PRESET_ORDER
from parakh.report.model import write_report_json
from tests.fakes import FakeEngine, make_report


def test_version_prints_package_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"parakh {__version__}"
    assert __version__ == "0.0.1"


def test_budget_notes_rpm_not_estimated():
    from pathlib import Path

    example = Path(__file__).parents[2] / "scenarios" / "hinglish" / "clinic-book-hinglish-01.yaml"
    result = CliRunner().invoke(app, ["budget", str(example)])
    assert result.exit_code == 0
    assert "RPM is not estimated" in result.output


# Exit code 2 outside `run` (README "Errors found before a call starts"): every
# failure below exits 2 with a short message on stderr and no traceback.

SCENARIO = """\
schema_version: 1
id: cli-exit-01
title: CLI exit codes
language: hi-en
domain: clinic
clock: "2026-11-19T10:00:00+05:30"
caller:
  voice: hi-IN-SwaraNeural
turns:
  - say: "haan"
"""

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


class _RaisingEngine:
    name = "raising"
    version = "1"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        raise self._exc


class _GarbageEngine:
    """Returns bytes ffmpeg cannot decode, so decode_to_pcm16 raises RuntimeError."""

    name = "garbage"
    version = "1"

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        return b"this is not audio"


def _scenario_file(tmp_path: Path, text: str = SCENARIO) -> Path:
    base = tmp_path / "dir with space"
    base.mkdir(exist_ok=True)
    path = base / "s.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _assert_clean_exit_2(result: Result) -> None:
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit)  # typer.Exit, not an escaped error
    assert "Traceback" not in result.output


def _tts_build(tmp_path: Path, scenario: Path) -> Result:
    cache = tmp_path / "dir with space" / "cache"
    return CliRunner().invoke(app, ["tts", "build", str(scenario), "--cache-dir", str(cache)])


def test_tts_build_invalid_scenario_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "make_engine", lambda: FakeEngine())
    bad = _scenario_file(tmp_path, SCENARIO.replace("schema_version: 1", "schema_version: 9"))
    result = _tts_build(tmp_path, bad)
    _assert_clean_exit_2(result)
    assert "s.yaml" in result.output
    assert "schema_version" in result.output


def test_tts_build_engine_value_error_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # edge-tts raises ValueError for a malformed caller rate, before any request.
    engine = _RaisingEngine(ValueError("Invalid rate 'fast'."))
    monkeypatch.setattr(cli, "make_engine", lambda: engine)
    result = _tts_build(tmp_path, _scenario_file(tmp_path))
    _assert_clean_exit_2(result)
    assert result.output.strip() == "tts build failed: ValueError: Invalid rate 'fast'."


@needs_ffmpeg
def test_tts_build_undecodable_audio_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "make_engine", lambda: _GarbageEngine())
    result = _tts_build(tmp_path, _scenario_file(tmp_path))
    _assert_clean_exit_2(result)
    assert result.output.startswith("tts build failed: RuntimeError: ")
    assert len(result.output.strip().splitlines()) == 1


def test_report_non_utf8_report_json_exit_2(tmp_path: Path) -> None:
    run_dir = tmp_path / "dir with space" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_bytes(b'{"status": "\xff\xfe"}')
    result = CliRunner().invoke(app, ["report", str(run_dir)])
    _assert_clean_exit_2(result)
    assert "cannot read report.json" in result.output
    assert len(result.output.strip().splitlines()) == 1


@needs_ffmpeg
def test_run_undecodable_audio_exit_2_without_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "make_engine", lambda: _GarbageEngine())
    runs = tmp_path / "dir with space" / "runs"
    args = ["run", str(_scenario_file(tmp_path)), "--agent", "ws://127.0.0.1:1"]
    cache = tmp_path / "dir with space" / "cache"
    result = CliRunner().invoke(app, [*args, "--runs-dir", str(runs), "--cache-dir", str(cache)])
    _assert_clean_exit_2(result)
    assert result.output.startswith("run failed: RuntimeError: ")
    assert len(result.output.strip().splitlines()) == 1
    assert not runs.exists()


def test_importing_cli_prints_no_pipecat_banner() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", "import parakh.cli"], capture_output=True, text=True, check=False
    )
    assert "Pipecat" not in proc.stdout + proc.stderr


def test_run_prints_run_dir_at_start_and_exits_2_on_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "dir with space" / "abc123"

    async def fake_run_scenario(*_a: object, on_start: Callable[[Path], None], **_k: object):
        on_start(run_dir)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "make_engine", lambda: FakeEngine())
    monkeypatch.setattr(run_module, "run_scenario", fake_run_scenario)
    args = ["run", str(_scenario_file(tmp_path)), "--agent", "ws://127.0.0.1:1"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    assert result.output.count("run dir:") == 1
    assert result.output.index("run dir:") < result.output.index("interrupted")


def test_batch_interrupt_prints_comparison_path_before_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_dir = tmp_path / "dir with space" / "b1"

    async def fake_run_batch(*_a: object, on_batch: Callable[[Path], None], **_k: object):
        on_batch(batch_dir)
        batch_dir.mkdir(parents=True)
        (batch_dir / "compare.html").write_text("x", encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "make_engine", lambda: FakeEngine())
    monkeypatch.setattr(cli, "run_batch", fake_run_batch)
    args = ["run", str(_scenario_file(tmp_path)), "--agent", "ws://127.0.0.1:1"]
    result = CliRunner().invoke(app, [*args, "--preset", "clean", "--preset", "phone"])
    assert result.exit_code == 2, result.output
    assert result.output.count("comparison:") == 1
    assert str(batch_dir / "compare.html") in result.output
    assert result.output.index("comparison:") < result.output.index("interrupted")


def test_run_rejects_unsupported_agent_rate(tmp_path: Path) -> None:
    args = ["run", str(_scenario_file(tmp_path)), "--agent", "ws://127.0.0.1:1"]
    result = CliRunner().invoke(app, [*args, "--agent-rate", "12345"])
    _assert_clean_exit_2(result)
    assert "agent_rate" in result.output


def _tone_wav(path: Path, seconds: float = 1.0, rate: int = 16000, amp: float = 8000.0) -> Path:
    import numpy as np

    from parakh.audio import write_wav

    t = np.arange(int(seconds * rate)) / rate
    write_wav(path, (amp * np.sin(2 * np.pi * 300 * t)).astype(np.int16), rate)
    return path


def _wav_info(path: Path) -> tuple[int, int]:
    import wave

    with wave.open(str(path), "rb") as wf:
        return wf.getframerate(), wf.getnframes()


def test_degrade_writes_wav(tmp_path):
    base = tmp_path / "dir with space"
    clip = _tone_wav(base / "in.wav")
    result = CliRunner().invoke(app, ["degrade", str(clip), "--preset", "phone"])
    assert result.exit_code == 0, result.output
    out = base / "in.phone.wav"
    assert out.is_file()
    rate, frames = _wav_info(out)
    assert rate == 16000
    assert abs(frames - 16000) <= 320
    assert f"wrote {out}" in result.stdout
    assert "snr n/a, lost frames 0/" in result.stdout


def test_degrade_rate_option(tmp_path):
    base = tmp_path / "dir with space"
    clip = _tone_wav(base / "in.wav")
    out = base / "o.wav"
    result = CliRunner().invoke(
        app, ["degrade", str(clip), "--preset", "phone", "--rate", "8000", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert _wav_info(out)[0] == 8000


def test_degrade_unknown_preset_exits_2(tmp_path):
    clip = _tone_wav(tmp_path / "dir with space" / "in.wav")
    result = CliRunner().invoke(app, ["degrade", str(clip), "--preset", "nope"])
    assert result.exit_code == 2
    assert "unknown preset" in result.stderr
    assert "Traceback" not in result.output


def test_degrade_silent_clip_with_noise_exits_2(tmp_path):
    import numpy as np

    from parakh.audio import write_wav

    clip = tmp_path / "dir with space" / "silent.wav"
    write_wav(clip, np.zeros(16000, dtype=np.int16), 16000)
    result = CliRunner().invoke(app, ["degrade", str(clip), "--preset", "bad_line"])
    assert result.exit_code == 2
    assert "SNR" in result.stderr


def test_degrade_babble_uses_engine(tmp_path, monkeypatch):
    base = tmp_path / "dir with space"
    clip = _tone_wav(base / "in.wav")
    engine = FakeEngine()
    monkeypatch.setattr(cli, "make_engine", lambda: engine)
    result = CliRunner().invoke(
        app,
        ["degrade", str(clip), "--preset", "phone_noisy", "--cache-dir", str(base / "cache")],
    )
    assert result.exit_code == 0, result.output
    assert engine.calls == 6
    assert "snr " in result.stdout
    assert "snr n/a" not in result.stdout


def test_degrade_snr_uses_peak_normalised_clip(tmp_path):
    # A quiet clip: scaling noise from the raw clip would not give the preset's 5 dB.
    base = tmp_path / "dir with space"
    clip = _tone_wav(base / "quiet.wav", amp=500.0)
    result = CliRunner().invoke(app, ["degrade", str(clip), "--preset", "bad_line"])
    assert result.exit_code == 0, result.output
    assert "snr 5.0 dB, lost frames" in result.stdout


def _fake_runs(monkeypatch: pytest.MonkeyPatch, statuses: list[str]) -> list[str]:
    seen: list[str] = []
    codes = iter(statuses)

    async def fake(_path: Path, _url: str, *, preset: str, runs_dir: Path, **_k: object):
        seen.append(preset)
        report = make_report(preset=preset, status=next(codes), run_id=f"r{len(seen)}")
        return report, runs_dir / f"r{len(seen)}"

    monkeypatch.setattr(cli, "make_engine", lambda: FakeEngine())
    monkeypatch.setattr(run_module, "run_scenario", fake)
    return seen


def _run_args(tmp_path: Path, *presets: str) -> list[str]:
    args = ["run", str(_scenario_file(tmp_path)), "--agent", "ws://127.0.0.1:1"]
    for name in presets:
        args += ["--preset", name]
    base = tmp_path / "dir with space"
    return [*args, "--runs-dir", str(base / "r"), "--cache-dir", str(base / "cache")]


def test_preset_all_expands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake_runs(monkeypatch, ["completed"] * len(PRESET_ORDER))
    result = CliRunner().invoke(app, _run_args(tmp_path, "all"))
    assert result.exit_code == 0, result.output
    assert seen == list(PRESET_ORDER)
    assert "comparison:" in result.output


def test_batch_exit_code_is_highest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runs(monkeypatch, ["completed", "agent_unreachable", "agent_hung_up_early"])
    result = CliRunner().invoke(app, _run_args(tmp_path, "clean", "phone", "bad_line"))
    assert result.exit_code == 2, result.output


def test_single_run_prints_no_comparison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runs(monkeypatch, ["completed"])
    result = CliRunner().invoke(app, _run_args(tmp_path))
    assert result.exit_code == 0, result.output
    assert "comparison:" not in result.output


def test_run_accepts_a_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake_runs(monkeypatch, ["completed"])
    scenario = _scenario_file(tmp_path)
    args = _run_args(tmp_path)
    args[1] = str(scenario.parent)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert seen == ["clean"]


def test_run_unknown_preset_exits_2(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, _run_args(tmp_path, "telephone"))
    _assert_clean_exit_2(result)


def _run_dir_with_report(base: Path, run_id: str, preset: str) -> Path:
    run_dir = base / run_id
    run_dir.mkdir(parents=True)
    write_report_json(make_report(run_id=run_id, preset=preset), run_dir / "report.json")
    return run_dir


def test_compare_command(tmp_path: Path) -> None:
    base = tmp_path / "dir with space" / "runs"
    first = _run_dir_with_report(base, "aaaa1111", "clean")
    second = _run_dir_with_report(base, "bbbb2222", "phone")
    out = tmp_path / "dir with space" / "out"
    result = CliRunner().invoke(app, ["compare", str(first), str(second), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "compare.html").exists()
    assert (out / "compare.json").exists()
    default = CliRunner().invoke(app, ["compare", str(first), str(second)])
    assert default.exit_code == 0, default.output
    assert (base / "compare.html").exists()


def test_compare_command_bad_report_exits_2(tmp_path: Path) -> None:
    base = tmp_path / "dir with space" / "runs"
    good = _run_dir_with_report(base, "aaaa1111", "clean")
    bad = base / "bbbb2222"
    bad.mkdir()
    (bad / "report.json").write_text("{not json", encoding="utf-8")
    result = CliRunner().invoke(app, ["compare", str(good), str(bad)])
    _assert_clean_exit_2(result)
    assert "cannot read report.json" in result.output


def test_budget_prints_presets() -> None:
    example = Path(__file__).parents[2] / "scenarios" / "hinglish" / "clinic-book-hinglish-01.yaml"
    result = CliRunner().invoke(app, ["budget", str(example), "--preset", "all"])
    assert "presets: 5" in result.output
    assert (
        "noise presets can add STT requests when the agent's VAD reacts to noise" in result.output
    )


def test_batch_interrupt_without_comparison_file_prints_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_dir = tmp_path / "dir with space" / "b1"

    async def fake_run_batch(*_a: object, on_batch: Callable[[Path], None], **_k: object):
        on_batch(batch_dir)  # announced, but no run finished, so no compare.html
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "make_engine", lambda: FakeEngine())
    monkeypatch.setattr(cli, "run_batch", fake_run_batch)
    args = ["run", str(_scenario_file(tmp_path)), "--agent", "ws://127.0.0.1:1"]
    result = CliRunner().invoke(app, [*args, "--preset", "clean", "--preset", "phone"])
    assert result.exit_code == 2, result.output
    assert "comparison:" not in result.output
    assert "interrupted" in result.output


def _lsb_wav(path: Path, samples: int = 16000) -> Path:
    import numpy as np

    from parakh.audio import write_wav

    pcm = np.where(np.arange(samples) % 2 == 0, 2, -2).astype(np.int16)
    write_wav(path, pcm, 16000)
    return path


def test_degrade_near_silent_clip_with_noise_exits_2(tmp_path):
    clip = _lsb_wav(tmp_path / "dir with space" / "quiet.wav")
    result = CliRunner().invoke(app, ["degrade", str(clip), "--preset", "bad_line"])
    assert result.exit_code == 2
    assert "clip has no audio above -60 dBFS; SNR is undefined" in result.stderr


def test_degrade_empty_clip_with_noise_exits_2(tmp_path):
    import numpy as np

    from parakh.audio import write_wav

    clip = tmp_path / "dir with space" / "empty.wav"
    write_wav(clip, np.zeros(0, dtype=np.int16), 16000)
    result = CliRunner().invoke(app, ["degrade", str(clip), "--preset", "bad_line"])
    assert result.exit_code == 2
    assert "clip is empty" in result.stderr
    assert "noise has zero RMS" not in result.stderr


def test_batch_prints_each_summary_as_it_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_echo = cli.typer.echo

    def recording_echo(message: object = "", *a: Any, **k: Any) -> None:
        order.append(str(message))
        real_echo(message, *a, **k)

    async def fake(_path: Path, _url: str, *, preset: str, runs_dir: Path, **_k: object):
        order.append(f"start {preset}")
        run_dir = runs_dir / preset
        run_dir.mkdir(parents=True)
        return make_report(preset=preset, run_id=preset), run_dir

    monkeypatch.setattr(cli, "make_engine", lambda: FakeEngine())
    monkeypatch.setattr(run_module, "run_scenario", fake)
    monkeypatch.setattr(cli.typer, "echo", recording_echo)
    result = CliRunner().invoke(app, _run_args(tmp_path, "clean", "phone"))
    assert result.exit_code == 0, result.output
    first = order.index("s1 / clean")
    assert first < order.index("start phone") < order.index("s1 / phone")
    assert order[-1].startswith("comparison:")


def test_compare_default_out_is_common_parent(tmp_path: Path) -> None:
    base = tmp_path / "dir with space"
    first = _run_dir_with_report(base / "b 1", "aaaa1111", "clean")
    second = _run_dir_with_report(base / "b 2", "bbbb2222", "phone")
    result = CliRunner().invoke(app, ["compare", str(first), str(second)])
    assert result.exit_code == 0, result.output
    assert (base / "compare.html").exists()


def test_compare_single_dir_writes_to_its_parent(tmp_path: Path) -> None:
    base = tmp_path / "dir with space" / "runs"
    only = _run_dir_with_report(base, "aaaa1111", "clean")
    result = CliRunner().invoke(app, ["compare", str(only)])
    assert result.exit_code == 0, result.output
    assert (base / "compare.html").exists()


def test_compare_different_drives_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "dir with space" / "runs"
    first = _run_dir_with_report(base, "aaaa1111", "clean")
    second = _run_dir_with_report(base, "bbbb2222", "phone")

    def other_drive(*_a: object, **_k: object) -> str:
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr(cli.os.path, "commonpath", other_drive)
    result = CliRunner().invoke(app, ["compare", str(first), str(second)])
    _assert_clean_exit_2(result)
    assert "different drives; pass --out" in result.output

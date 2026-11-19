import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from parakh import __version__, cli
from parakh.cli import app
from tests.fakes import FakeEngine


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
    monkeypatch.setattr(cli, "run_scenario", fake_run_scenario)
    args = ["run", str(_scenario_file(tmp_path)), "--agent", "ws://127.0.0.1:1"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    assert result.output.count("run dir:") == 1
    assert result.output.index("run dir:") < result.output.index("interrupted")


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
    assert "snr n/a dB, lost frames 0/" in result.stdout


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

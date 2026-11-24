"""CLI run/report against the fake agent.

The fake agent is async, so it runs in a background thread with its own event loop;
the command's own asyncio.run then runs on the test thread without clashing.
"""

import asyncio
import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from parakh import cli
from parakh.cli import app
from parakh.run import run_scenario
from tests.fakes import FakeEngine
from tests.integration.fake_agent import FakeBehaviour, fake_agent

pytestmark = pytest.mark.integration

TOL_MS = 60 if os.environ.get("CI") else 20

if shutil.which("ffmpeg") is None:  # pragma: no cover
    pytest.skip("ffmpeg not installed", allow_module_level=True)

SCENARIO = """\
schema_version: 1
id: cli-run-01
title: CLI run test
language: hi-en
domain: clinic
clock: "2026-11-19T10:00:00+05:30"
agent_speaks_first: true
caller:
  voice: hi-IN-SwaraNeural
turns:
  - say: "one"
  - say: "two"
  - say: "three"
  - say: "four"
limits: { max_turns: 12, response_timeout_s: 1.5, call_timeout_s: 20 }
"""


@contextmanager
def background_agent(behaviour: FakeBehaviour) -> Iterator[str]:
    """Run fake_agent on its own loop in a thread; yield its URL."""
    loop = asyncio.new_event_loop()
    url_ready = threading.Event()
    stop = threading.Event()
    box: dict[str, str] = {}

    async def serve() -> None:
        async with fake_agent(behaviour) as url:
            box["url"] = url
            url_ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)

    thread = threading.Thread(target=lambda: loop.run_until_complete(serve()), daemon=True)
    thread.start()
    assert url_ready.wait(10)
    try:
        yield box["url"]
    finally:
        stop.set()
        thread.join(10)
        loop.close()


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "make_engine", lambda: FakeEngine())


def _invoke(tmp_path: Path, url: str, *extra: str):
    base = tmp_path / "dir with space"
    base.mkdir(exist_ok=True)
    scenario = base / "s.yaml"
    scenario.write_text(SCENARIO, encoding="utf-8")
    args = [
        "run",
        str(scenario),
        "--agent",
        url,
        "--cache-dir",
        str(base / "cache"),
        "--runs-dir",
        str(base / "runs"),
        *extra,
    ]
    return CliRunner().invoke(app, args), base / "runs"


def _only_run(runs: Path) -> Path:
    (run_dir,) = list(runs.iterdir())
    return run_dir


def test_run_writes_report(tmp_path: Path) -> None:
    behaviour = FakeBehaviour(transcripts=["one", "two", "three", "four"])
    with background_agent(behaviour) as url:
        result, runs = _invoke(tmp_path, url)
    assert result.exit_code == 0, result.output
    run_dir = _only_run(runs)
    for name in ("report.json", "report.html", "events.jsonl", "caller.wav", "agent.wav"):
        assert (run_dir / name).is_file(), name
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["latency"]["n"] == 4
    assert report["status"] == "completed"
    assert report["metrics"]["loose_wer"] == 0.0
    assert f"run dir: {run_dir}" in result.output
    assert "latency p50/p95:" in result.output
    assert "loose WER:" in result.output


def test_run_writes_report_on_disconnect(tmp_path: Path) -> None:
    info = {"name": "fake-agent", "version": "9"}
    with background_agent(FakeBehaviour(close_after_replies=1, agent_info=info)) as url:
        result, runs = _invoke(tmp_path, url)
    assert result.exit_code == 2, result.output
    run_dir = _only_run(runs)
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "agent_disconnected"
    assert (run_dir / "report.html").is_file()
    assert len(report["turns"]) == 4
    for name in ("events.jsonl", "caller.wav", "agent.wav"):
        assert (run_dir / name).is_file(), name
    assert report["agent_info"] == info


def test_run_hangup_exit_1(tmp_path: Path) -> None:
    with background_agent(FakeBehaviour(close_before_greeting=True)) as url:
        result, runs = _invoke(tmp_path, url)
    assert result.exit_code == 1, result.output
    assert (_only_run(runs) / "report.json").is_file()


def test_run_unreachable_exit_2(tmp_path: Path) -> None:
    result, runs = _invoke(tmp_path, "ws://127.0.0.1:1")
    assert result.exit_code == 2, result.output
    assert "could not connect" in result.output
    assert "127.0.0.1:1" in result.output
    assert (_only_run(runs) / "report.json").is_file()


def test_run_bad_url_exit_2_without_run_dir(tmp_path: Path) -> None:
    result, runs = _invoke(tmp_path, "http://127.0.0.1:1")
    assert result.exit_code == 2
    assert not runs.exists()


def test_run_unknown_preset_exit_2(tmp_path: Path) -> None:
    result, runs = _invoke(tmp_path, "ws://127.0.0.1:1", "--preset", "telephone")
    assert result.exit_code == 2
    assert "unknown preset 'telephone'; available: clean, phone" in result.output
    assert not runs.exists()


def test_run_without_ffmpeg_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result, _ = _invoke(tmp_path, "ws://127.0.0.1:1")
    assert result.exit_code == 2
    assert "winget install Gyan.FFmpeg" in result.output


def test_report_command_rerenders(tmp_path: Path) -> None:
    with background_agent(FakeBehaviour()) as url:
        result, runs = _invoke(tmp_path, url)
    assert result.exit_code == 0, result.output
    run_dir = _only_run(runs)
    (run_dir / "report.html").unlink()
    again = CliRunner().invoke(app, ["report", str(run_dir)])
    assert again.exit_code == 0, again.output
    assert (run_dir / "report.html").is_file()


def test_report_command_missing_dir_exit_2(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["report", str(tmp_path / "nope")])
    assert result.exit_code == 2


def test_run_unreachable_never_leaks_url_secret(tmp_path: Path) -> None:
    result, runs = _invoke(tmp_path, "ws://user:pw@127.0.0.1:1/ws?token=SECRET#frag")
    assert result.exit_code == 2
    run_dir = _only_run(runs)
    for name in ("report.json", "report.html", "events.jsonl"):
        text = (run_dir / name).read_text(encoding="utf-8")
        assert "SECRET" not in text and "user:pw" not in text, name
    assert "SECRET" not in result.output and "user:pw" not in result.output
    assert "127.0.0.1:1" in result.output


def test_run_bad_url_message_is_redacted(tmp_path: Path) -> None:
    result, _ = _invoke(tmp_path, "http://u:pw@127.0.0.1:1/?token=SECRET")
    assert result.exit_code == 2
    assert "SECRET" not in result.output and "u:pw" not in result.output


def test_run_without_port_uses_scheme_default(tmp_path: Path) -> None:
    result, _ = _invoke(tmp_path, "ws://127.0.0.1")
    assert "None" not in result.output
    assert "127.0.0.1:80" in result.output


def test_run_malformed_port_does_not_crash(tmp_path: Path) -> None:
    result, _ = _invoke(tmp_path, "ws://127.0.0.1:abc")
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_run_scoring_failure_still_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("scoring blew up")

    monkeypatch.setattr("parakh.report.build.response_latencies", boom)
    with background_agent(FakeBehaviour()) as url:
        result, runs = _invoke(tmp_path, url)
    assert result.exit_code == 2, result.output
    run_dir = _only_run(runs)
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "internal_error"
    assert any("RuntimeError" in w for w in report["warnings"])
    assert (run_dir / "report.html").is_file()


def test_run_with_preset_records_seed_and_degradation(tmp_path: Path) -> None:
    base = tmp_path / "dir with space"
    base.mkdir()
    scenario = base / "s.yaml"
    scenario.write_text(SCENARIO, encoding="utf-8")
    with background_agent(FakeBehaviour(transcripts=["one", "two", "three", "four"])) as url:
        report, run_dir = asyncio.run(
            run_scenario(
                scenario,
                url,
                preset="phone_lossy",
                runs_dir=base / "runs",
                engine=FakeEngine(),
                cache_dir=base / "cache",
            )
        )
    assert report.status == "completed"
    assert isinstance(report.seed, int)
    assert len(report.turns) == 4
    for turn in report.turns:
        assert turn.degradation is not None
        assert turn.degradation.frames > 0
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "phone_lossy" in html
    assert f"seed {report.seed}" in html
    assert "lost " in html


BARGE_SCENARIO = SCENARIO.replace(
    '  - say: "two"\n', '  - say: "two"\n    barge_in: { after_agent_ms: 1200 }\n'
)


async def test_barge_in_run_scores_stop_latency(tmp_path: Path) -> None:
    base = tmp_path / "dir with space"
    base.mkdir()
    scenario = base / "s.yaml"
    scenario.write_text(BARGE_SCENARIO, encoding="utf-8")
    behaviour = FakeBehaviour(
        burst=False,
        reply_ms=3000,
        yield_after_ms=300,
        send_interruption=True,
        user_started=True,
        transcripts=["one", "two", "three", "four"],
    )
    with background_agent(behaviour) as url:
        report, _run_dir = await run_scenario(
            scenario,
            url,
            preset="clean",
            runs_dir=base / "runs",
            engine=FakeEngine(),
            cache_dir=base / "cache",
        )
    assert report.status == "completed"
    barge = report.turns[1].barge_in
    assert barge is not None
    assert barge.result == "yielded"
    assert barge.via == "interruption"
    assert barge.stop_latency_ms is not None
    assert abs(barge.stop_latency_ms - 300) <= 2 * TOL_MS
    assert report.metrics.stop_latency is not None
    assert report.metrics.stop_latency.n == 1
    assert report.metrics.did_not_yield == 0
    assert report.metrics.false_barge_in_ms == []


async def test_pauses_inside_a_reply_are_not_a_yield(tmp_path: Path) -> None:
    base = tmp_path / "dir with space"
    base.mkdir()
    scenario = base / "s.yaml"
    scenario.write_text(BARGE_SCENARIO, encoding="utf-8")
    behaviour = FakeBehaviour(
        burst=False,
        reply_ms=6000,
        pause_every_ms=700,
        pause_ms=300,
        transcripts=["one", "two", "three", "four"],
    )
    with background_agent(behaviour) as url:
        report, _run_dir = await run_scenario(
            scenario,
            url,
            preset="clean",
            runs_dir=base / "runs",
            engine=FakeEngine(),
            cache_dir=base / "cache",
        )
    barge = report.turns[1].barge_in
    assert barge is not None
    assert barge.result == "did_not_yield"
    assert barge.stop_latency_ms is None
    assert report.metrics.did_not_yield == 1


def test_agent_429_ends_run_rate_limited(tmp_path: Path) -> None:
    behaviour = FakeBehaviour(rtvi_error=(1, "Error code: 429 - rate_limit_exceeded"))
    with background_agent(behaviour) as url:
        result, runs = _invoke(tmp_path, url)
    assert result.exit_code == 2, result.output
    assert "status: rate_limited" in result.output
    report = json.loads((_only_run(runs) / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "rate_limited"
    assert any(w.startswith("agent error") and "429" in w for w in report["warnings"])


# --- real recordings (D10, EC-60) --------------------------------------------------------


def _record_turns(base: Path) -> None:
    """data/real/cli-run-01/turn-0N.wav under base: loud 48 kHz stereo tones."""
    for n in range(1, 5):
        path = base / "data" / "real" / "cli-run-01" / f"turn-{n:02d}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i"]
            + ["sine=frequency=500:duration=0.6", "-ar", "48000", "-ac", "2", str(path)],
            check=True,
            capture_output=True,
        )


@pytest.fixture
def real_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "dir with space"
    base.mkdir()
    _record_turns(base)
    monkeypatch.chdir(base)

    def no_judge() -> None:
        raise AssertionError("a real run must not even create the judge")

    monkeypatch.setattr(cli, "make_judge", no_judge)

    monkeypatch.setattr(cli, "make_engine", lambda: _NoCallerTTS())
    return base


class _NoCallerTTS(FakeEngine):
    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        raise AssertionError(f"edge-tts must not be called for {text!r}")


def test_real_run_sends_no_audio_to_remote_stt_agent(real_base: Path) -> None:
    behaviour = FakeBehaviour(agent_info={"stt_model": "whisper-large-v3-turbo"})
    with background_agent(behaviour) as url:
        result, runs = _invoke(real_base, url, "--real")
    assert result.exit_code == 2, result.output
    report = json.loads((_only_run(runs) / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "real_data_refused"
    assert report["real_audio"] is True
    assert (
        "real data refused: agent stt_model 'whisper-large-v3-turbo' is not local"
        in report["warnings"]
    )
    assert all(t["transcript"] == "" for t in report["turns"])
    assert report["judge"] is None
    assert behaviour.received_dbfs, "the caller should still stream (silence and bed)"
    assert max(behaviour.received_dbfs) <= -45.0
    assert all(rate == 16000 for rate, _ in behaviour.received)
    assert "status: real_data_refused" in result.output


def test_real_run_refuses_an_agent_that_sends_no_info(real_base: Path) -> None:
    behaviour = FakeBehaviour()
    with background_agent(behaviour) as url:
        result, runs = _invoke(real_base, url, "--real")
    assert result.exit_code == 2, result.output
    report = json.loads((_only_run(runs) / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "real_data_refused"
    assert "real data refused: no agent info within 5.0 s" in report["warnings"]
    assert max(behaviour.received_dbfs) <= -45.0


def test_real_run_completes_with_local_stt_agent(real_base: Path) -> None:
    behaviour = FakeBehaviour(
        agent_info={"stt_model": "local:faster-whisper-small"},
        transcripts=["one", "two", "three", "four"],
    )
    with background_agent(behaviour) as url:
        result, runs = _invoke(real_base, url, "--real")
    assert result.exit_code == 0, result.output
    report = json.loads((_only_run(runs) / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["real_audio"] is True
    assert report["metrics"]["latency"]["n"] == 4  # the first turn was held, not played as silence
    assert report["judge"] is None
    assert sum(1 for level in behaviour.received_dbfs if level > -45.0) > 100
    html = (_only_run(runs) / "report.html").read_text(encoding="utf-8")
    assert "Real recording: audio stays on this machine" in html


def test_real_run_refuses_a_remote_url_before_anything_is_written(real_base: Path) -> None:
    result, runs = _invoke(real_base, "ws://10.0.0.5:8765", "--real")
    assert result.exit_code == 2, result.output
    assert "real recordings need an agent on this machine" in result.output
    assert not runs.exists()


def test_real_run_missing_recording_exits_2(real_base: Path) -> None:
    (real_base / "data" / "real" / "cli-run-01" / "turn-03.wav").unlink()
    result, runs = _invoke(real_base, "ws://127.0.0.1:1", "--real")
    assert result.exit_code == 2, result.output
    assert "turn-03.*" in result.output
    assert not runs.exists()

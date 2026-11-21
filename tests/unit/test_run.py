import json
import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from parakh import run as run_module
from parakh.caller.driver import CallResult
from parakh.caller.pacer import JitterStats
from parakh.report import build as build_module
from parakh.report.build import _git_sha, _ttfb_ms, build_report
from parakh.report.model import JitterModel, LatencyStatsModel, Metrics, Report, write_report_json
from parakh.run import exit_code, run_batch, run_scenario
from parakh.scenario import Scenario, ScenarioError
from parakh.score.wer import NO_TRANSCRIPT_REASON
from parakh.transport.ws import redact_url, redact_urls
from tests.fakes import FakeEngine, make_report


def test_ttfb_ms_converts_and_skips_malformed():
    data: dict[str, Any] = {
        "ttfb": [
            {"value": 0.25},
            {"value": 1},
            {"value": True},
            {"value": "0.3"},
            {"value": math.nan},
            {"value": math.inf},
            {"value": -0.1},
            {"processor": "x"},
            "junk",
            None,
        ]
    }
    assert _ttfb_ms(data) == [250.0, 1000.0]
    assert _ttfb_ms({"ttfb": "nope"}) == []
    assert _ttfb_ms({}) == []
    assert _ttfb_ms(None) == []


def _report(status: str, unreliable: bool = False) -> Report:
    return Report(
        parakh_version="0",
        git_sha=None,
        run_id="r",
        created_at="t",
        scenario_id="s",
        scenario_title="s",
        language="en",
        preset="clean",
        seed=None,
        agent_url="ws://h",
        agent_info={},
        status=status,
        timing_unreliable=unreliable,
        jitter=JitterModel(n=0, p50_ms=0, p99_ms=0, max_ms=0),
        cpu_max_percent=0,
        turns=[],
        metrics=Metrics(
            latency=LatencyStatsModel(n=0, p50_ms=None, p90_ms=None, p95_ms=None, max_ms=None),
            strict_wer=None,
            loose_wer=None,
            loose_cer=None,
            wer_reason=None,
        ),
        warnings=[],
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("completed", 0),
        ("agent_hung_up_early", 1),
        ("turn_timeout", 2),
        ("call_timeout", 2),
        ("agent_disconnected", 2),
        ("agent_unreachable", 2),
        ("protocol_error", 2),
        ("internal_error", 2),
        ("interrupted", 2),
    ],
)
def test_exit_code_by_status(status: str, code: int):
    assert exit_code(_report(status)) == code


def test_exit_code_timing_unreliable_is_2_even_when_completed():
    assert exit_code(_report("completed", unreliable=True)) == 2


def test_git_sha_none_when_git_fails(monkeypatch: pytest.MonkeyPatch):
    def boom(*_a: Any, **_k: Any):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert _git_sha() is None
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 128, b"", b"fatal")
    )
    assert _git_sha() is None


def test_greeting_items_are_dropped_not_given_to_turn_0():
    scenario = Scenario.model_validate(
        {
            "schema_version": 1,
            "id": "s",
            "title": "s",
            "language": "en",
            "domain": "d",
            "clock": "2026-11-19T10:00:00+05:30",
            "caller": {"voice": "v"},
            "turns": [{"say": "one"}, {"say": "two"}],
        }
    )
    jitter = JitterStats(n=0, p50_ms=0.0, p99_ms=0.0, max_ms=0.0)
    result = CallResult("completed", Path("."), 2, jitter, False, 0.0, {}, [])
    events: list[dict[str, Any]] = [
        {"kind": "bot_output", "t_ms": 100.0, "text": "hello greeting"},
        {"kind": "agent_metrics", "t_ms": 110.0, "data": {"ttfb": [{"value": 0.5}]}},
        {"kind": "caller_turn_start", "t_ms": 1000.0, "turn": 0},
        {"kind": "bot_output", "t_ms": 1500.0, "text": "reply one"},
        {"kind": "agent_metrics", "t_ms": 1510.0, "data": {"ttfb": [{"value": 0.2}]}},
        {"kind": "caller_turn_start", "t_ms": 3000.0, "turn": 1},
    ]
    report = build_report(scenario, result, events, run_id="r", agent_url="ws://h", preset="clean")
    assert report.turns[0].agent_text == "reply one"
    assert report.turns[0].agent_ttfb_ms == [200.0]
    assert report.turns[1].agent_text == ""


def test_redact_url():
    assert redact_url("wss://user:pw@h.example:8443/ws?token=abc#x") == "wss://h.example:8443/ws"
    assert redact_url("ws://h.example") == "ws://h.example"


def _three_turn_scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 1,
            "id": "s",
            "title": "s",
            "language": "en",
            "domain": "d",
            "clock": "2026-11-19T10:00:00+05:30",
            "caller": {"voice": "v"},
            "turns": [{"say": "one two"}, {"say": "three four"}, {"say": "five"}],
        }
    )


def _wer_report(events: list[dict[str, Any]]) -> Report:
    jitter = JitterStats(n=0, p50_ms=0.0, p99_ms=0.0, max_ms=0.0)
    result = CallResult("turn_timeout", Path("."), 2, jitter, False, 0.0, {}, [])
    return build_report(
        _three_turn_scenario(), result, events, run_id="r", agent_url="ws://h", preset="clean"
    )


def test_reached_turn_with_empty_transcript_has_wer_1():
    # EC-46: an empty hypothesis gives WER 1.0. The agent exposes a transcript (turn 0
    # has one), so turn 1, reached but unheard, is a full miss, not "no data".
    events: list[dict[str, Any]] = [
        {"kind": "caller_turn_start", "t_ms": 1000.0, "turn": 0},
        {"kind": "caller_transcript", "t_ms": 1800.0, "text": "one two", "final": True},
        {"kind": "caller_turn_start", "t_ms": 3000.0, "turn": 1},
    ]
    report = _wer_report(events)
    assert (report.turns[0].strict_wer, report.turns[0].loose_wer) == (0.0, 0.0)
    assert (report.turns[1].strict_wer, report.turns[1].loose_wer) == (1.0, 1.0)
    assert report.turns[1].transcript == ""
    # Turn 2 was never reached: no WER.
    assert (report.turns[2].strict_wer, report.turns[2].loose_wer) == (None, None)
    assert report.turns[2].latency_reason == "turn not reached"
    assert report.metrics.wer_reason is None


def test_no_caller_transcript_at_all_keeps_wer_null_with_reason():
    events: list[dict[str, Any]] = [
        {"kind": "caller_turn_start", "t_ms": 1000.0, "turn": 0},
        {"kind": "caller_turn_start", "t_ms": 3000.0, "turn": 1},
    ]
    report = _wer_report(events)
    assert all(t.strict_wer is None and t.loose_wer is None for t in report.turns)
    assert report.metrics.wer_reason == NO_TRANSCRIPT_REASON


def test_redact_urls_in_free_text():
    text = "failed: https://u:pw@api.example/v1/x?key=SECRET and ws://h:1/p#frag, done"
    assert redact_urls(text) == "failed: https://api.example/v1/x and ws://h:1/p, done"
    assert redact_urls("no url here") == "no url here"


_SCENARIO_YAML = """\
schema_version: 1
id: run-int-01
title: Interrupt
language: en
domain: clinic
clock: "2026-11-19T10:00:00+05:30"
caller:
  voice: v
turns:
  - say: "one two"
  - say: "three four"
"""


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    base = tmp_path / "dir with space"
    base.mkdir()
    scenario = base / "s.yaml"
    scenario.write_text(_SCENARIO_YAML, encoding="utf-8")
    return scenario, base / "runs", base / "cache"


def _write_events(run_dir: Path, events: list[dict[str, Any]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in events]
    (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _interrupted(scenario: Path, runs: Path, cache: Path) -> None:
    await run_scenario(
        scenario, "ws://127.0.0.1:1", runs_dir=runs, engine=FakeEngine(), cache_dir=cache
    )


async def test_interrupt_writes_partial_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scenario, runs, cache = _setup(tmp_path)

    async def fake_run_call(_url: str, _scn: Scenario, _clips: Any, run_dir: Path, **_k: Any):
        _write_events(
            run_dir,
            [
                {"kind": "call_start", "t_ms": 0.0},
                {"kind": "agent_info", "t_ms": 1.0, "info": {"name": "bot"}},
                {"kind": "warning", "t_ms": 2.0, "message": "cpu high"},
                {"kind": "caller_turn_start", "t_ms": 100.0, "turn": 0},
                {"kind": "caller_speech_end", "t_ms": 600.0, "turn": 0},
                {"kind": "agent_audio", "t_ms": 900.0, "dbfs": -10.0, "duration_ms": 20},
                {"kind": "caller_transcript", "t_ms": 1000.0, "text": "one two", "final": True},
            ],
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "run_call", fake_run_call)
    with pytest.raises(KeyboardInterrupt):
        await _interrupted(scenario, runs, cache)
    (run_dir,) = list(runs.iterdir())
    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert data["status"] == "interrupted"
    assert data["turns"][0]["transcript"] == "one two"
    assert data["turns"][0]["latency_ms"] is not None
    assert data["turns"][1]["latency_reason"] == "turn not reached"
    assert data["agent_info"] == {"name": "bot"}
    assert data["warnings"] == ["cpu high", "interrupted by the user"]
    assert (run_dir / "report.html").exists()


async def test_interrupt_before_events_writes_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    scenario, runs, cache = _setup(tmp_path)

    async def fake_run_call(*_a: Any, **_k: Any):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "run_call", fake_run_call)
    with pytest.raises(KeyboardInterrupt):
        await _interrupted(scenario, runs, cache)
    (run_dir,) = list(runs.iterdir())
    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert data["status"] == "interrupted"
    assert data["warnings"] == ["interrupted by the user"]


async def test_interrupt_survives_report_write_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    scenario, runs, cache = _setup(tmp_path)

    async def fake_run_call(*_a: Any, **_k: Any):
        raise KeyboardInterrupt

    def bad_write(*_a: Any, **_k: Any):
        raise OSError("disk full")

    monkeypatch.setattr(run_module, "run_call", fake_run_call)
    monkeypatch.setattr(run_module, "_write", bad_write)
    with pytest.raises(KeyboardInterrupt):
        await _interrupted(scenario, runs, cache)


async def test_on_start_called_once_with_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scenario, runs, cache = _setup(tmp_path)
    seen: list[Path] = []

    async def fake_run_call(_url: str, _scn: Scenario, _clips: Any, run_dir: Path, **_k: Any):
        assert seen == [run_dir]
        _write_events(run_dir, [{"kind": "call_start", "t_ms": 0.0}])
        jitter = JitterStats(n=0, p50_ms=0.0, p99_ms=0.0, max_ms=0.0)
        return CallResult("completed", run_dir, 0, jitter, False, 0.0, {}, [])

    monkeypatch.setattr(run_module, "run_call", fake_run_call)
    _report_obj, run_dir = await run_scenario(
        scenario,
        "ws://127.0.0.1:1",
        runs_dir=runs,
        engine=FakeEngine(),
        cache_dir=cache,
        on_start=seen.append,
    )
    assert seen == [run_dir]


def test_git_sha_none_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "no git here"
    root.mkdir()
    monkeypatch.setattr(build_module, "_REPO_ROOT", root)

    def boom(*_a: Any, **_k: Any):
        raise AssertionError("git must not run outside a repo")

    monkeypatch.setattr(subprocess, "run", boom)
    assert _git_sha() is None


def test_git_sha_none_on_timeout(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, Any] = {}

    def slow(*_a: Any, **kwargs: Any):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired("git", 5)

    monkeypatch.setattr(subprocess, "run", slow)
    monkeypatch.setattr(build_module, "_installed_from_repo", lambda: True)
    assert _git_sha() is None
    assert seen["timeout"] == 5


async def test_unsupported_agent_rate_rejected(tmp_path: Path):
    scenario, runs, cache = _setup(tmp_path)
    with pytest.raises(ValueError, match="agent_rate"):
        await run_scenario(
            scenario,
            "ws://127.0.0.1:1",
            runs_dir=runs,
            agent_rate=16001,
            engine=FakeEngine(),
            cache_dir=cache,
        )
    assert not runs.exists() or not list(runs.iterdir())


# Batch runs: run_scenario is replaced by a recorder that returns fixture reports.


def _batch_fake(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[str] | None = None,
    interrupt_at: int = -1,
    error_at: int = -1,
    error: Exception | None = None,
) -> list[tuple[str, str, Path]]:
    calls: list[tuple[str, str, Path]] = []

    async def fake(path: Path, _url: str, *, preset: str, runs_dir: Path, **_k: Any):
        n = len(calls)
        calls.append((path.stem, preset, runs_dir))
        status = statuses[n] if statuses else "completed"
        report = make_report(scenario_id=path.stem, preset=preset, status=status, run_id=f"r{n}")
        if n == error_at and error is not None:
            raise error  # before the call starts: no run dir, no report
        run_dir = runs_dir / f"r{n}"
        run_dir.mkdir(parents=True)
        if n == interrupt_at:
            report = make_report(scenario_id=path.stem, preset=preset, status="interrupted")
            write_report_json(report, run_dir / "report.json")
            raise KeyboardInterrupt
        write_report_json(report, run_dir / "report.json")
        return report, run_dir

    monkeypatch.setattr(run_module, "run_scenario", fake)
    return calls


async def _batch(
    tmp_path: Path,
    presets: list[str],
    names: tuple[str, ...] = ("s1", "s2"),
    on_batch: Callable[[Path], None] | None = None,
    gap_s: float = 0.0,
):
    base = tmp_path / "dir with space"
    base.mkdir(exist_ok=True)
    return await run_batch(
        [base / f"{n}.yaml" for n in names],
        "ws://127.0.0.1:1",
        presets,
        runs_dir=base / "runs",
        agent_rate=16000,
        engine=FakeEngine(),
        cache_dir=base / "cache",
        on_batch=on_batch,
        gap_s=gap_s,
    )


async def test_batch_runs_presets_back_to_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls = _batch_fake(monkeypatch)
    results, batch_dir = await _batch(tmp_path, ["clean", "phone"])
    assert [(s, p) for s, p, _ in calls] == [
        ("s1", "clean"),
        ("s1", "phone"),
        ("s2", "clean"),
        ("s2", "phone"),
    ]
    assert batch_dir is not None
    assert all(d == batch_dir for _, _, d in calls)
    assert len(batch_dir.name) == 8
    assert (batch_dir / "compare.html").exists()
    assert (batch_dir / "compare.json").exists()
    assert len(results) == 4


async def test_single_run_has_no_batch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls = _batch_fake(monkeypatch)
    results, batch_dir = await _batch(tmp_path, ["clean"], names=("s1",))
    assert batch_dir is None
    assert calls[0][2] == tmp_path / "dir with space" / "runs"
    assert len(results) == 1
    assert not list((tmp_path / "dir with space" / "runs").glob("compare.*"))


async def test_batch_continues_after_failed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls = _batch_fake(monkeypatch, statuses=["completed", "agent_unreachable", "completed"])
    results, batch_dir = await _batch(tmp_path, ["clean", "phone", "bad_line"], names=("s1",))
    assert len(calls) == 3
    assert batch_dir is not None
    rows = json.loads((batch_dir / "compare.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 3
    assert "agent_unreachable" in [r["status"] for r in rows]
    assert [r.status for r, _ in results] == ["completed", "agent_unreachable", "completed"]


async def test_batch_interrupt_writes_compare_for_finished_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls = _batch_fake(monkeypatch, interrupt_at=1)
    with pytest.raises(KeyboardInterrupt):
        await _batch(tmp_path, ["clean", "phone"])
    assert len(calls) == 2
    batch_dir = calls[0][2]
    rows = json.loads((batch_dir / "compare.json").read_text(encoding="utf-8"))["rows"]
    assert sorted(r["status"] for r in rows) == ["completed", "interrupted"]
    assert (batch_dir / "compare.html").exists()


@pytest.mark.parametrize("error", [ValueError("bad preset"), ScenarioError("bad scenario")])
async def test_batch_pre_call_error_writes_compare_for_finished_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
):
    calls = _batch_fake(monkeypatch, error_at=1, error=error)
    seen: list[Path] = []
    with pytest.raises(type(error)):
        await _batch(tmp_path, ["clean", "phone"], on_batch=seen.append)
    assert len(calls) == 2
    batch_dir = calls[0][2]
    assert seen == [batch_dir]
    rows = json.loads((batch_dir / "compare.json").read_text(encoding="utf-8"))["rows"]
    assert [r["status"] for r in rows] == ["completed"]
    assert (batch_dir / "compare.html").exists()


async def test_single_run_does_not_call_on_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _batch_fake(monkeypatch)
    seen: list[Path] = []
    await _batch(tmp_path, ["clean"], names=("s1",), on_batch=seen.append)
    assert seen == []


async def test_batch_pauses_between_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # The agent may still be finishing the previous call (a segment its VAD was hearing
    # when the caller hung up); the pause lets that land before the next caller connects.
    _batch_fake(monkeypatch)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(run_module.asyncio, "sleep", fake_sleep)
    base = tmp_path / "dir with space"
    base.mkdir()
    # No gap_s argument: the CLI relies on the default, so the default is what is pinned.
    await run_batch(
        [base / "s1.yaml", base / "s2.yaml"],
        "ws://127.0.0.1:1",
        ["clean", "phone"],
        runs_dir=base / "runs",
        engine=FakeEngine(),
        cache_dir=base / "cache",
    )
    assert sleeps == [3.0, 3.0, 3.0]  # 4 runs, 3 gaps, none before the first or after the last

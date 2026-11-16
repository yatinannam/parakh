import math
import subprocess
from pathlib import Path
from typing import Any

import pytest

from parakh.caller.driver import CallResult
from parakh.caller.pacer import JitterStats
from parakh.report.model import JitterModel, LatencyStatsModel, Metrics, Report
from parakh.run import _build_report, _git_sha, _ttfb_ms, exit_code
from parakh.scenario import Scenario
from parakh.transport.ws import redact_url


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
    report = _build_report(scenario, result, events, run_id="r", agent_url="ws://h", preset="clean")
    assert report.turns[0].agent_text == "reply one"
    assert report.turns[0].agent_ttfb_ms == [200.0]
    assert report.turns[1].agent_text == ""


def test_redact_url():
    assert redact_url("wss://user:pw@h.example:8443/ws?token=abc#x") == "wss://h.example:8443/ws"
    assert redact_url("ws://h.example") == "ws://h.example"

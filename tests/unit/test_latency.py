from typing import Any

import pytest

from parakh.score.bargein import StopLatency
from parakh.score.latency import LatencyStats, TurnLatency, latency_stats, response_latencies


def _end(t: float, turn: int = 0) -> dict[str, Any]:
    return {"kind": "caller_speech_end", "t_ms": t, "turn": turn}


def _start(t: float, turn: int) -> dict[str, Any]:
    return {"kind": "caller_turn_start", "t_ms": t, "turn": turn}


def _audio(t: float, dbfs: float) -> dict[str, Any]:
    return {
        "kind": "agent_audio",
        "t_ms": t,
        "duration_ms": 20.0,
        "dbfs": dbfs,
        "sample_rate": 8000,
    }


def test_exact_latency_from_timeline() -> None:
    events = [_start(0.0, 0), _end(1000.0), _audio(1350.0, -20.0)]
    assert response_latencies(events) == [TurnLatency(0, 350.0, None)]


def test_silent_frames_are_ignored() -> None:
    events = [_end(1000.0), _audio(1100.0, -60.0), _audio(1400.0, -20.0)]
    assert response_latencies(events)[0].latency_ms == 400.0


def test_audio_before_speech_end_ignored() -> None:
    events = [_audio(900.0, -20.0), _end(1000.0), _audio(1500.0, -20.0)]
    assert response_latencies(events)[0].latency_ms == 500.0


def test_no_reply_gives_none() -> None:
    events = [_end(1000.0), _audio(1100.0, -60.0), _start(2000.0, 1), _audio(2500.0, -20.0)]
    assert response_latencies(events) == [TurnLatency(0, None, "no agent audio")]


def test_threshold_is_strict_and_out_of_order_events_ok() -> None:
    events = [_audio(1500.0, -20.0), _audio(1200.0, -45.0), _end(1000.0)]
    assert response_latencies(events)[0].latency_ms == 500.0


def test_turns_ordered_and_bounded_by_next_turn() -> None:
    events = [
        _end(3000.0, 1),
        _end(1000.0, 0),
        _start(2000.0, 1),
        _audio(1300.0, -20.0),
        _audio(3200.0, -20.0),
    ]
    assert response_latencies(events) == [
        TurnLatency(0, 300.0, None),
        TurnLatency(1, 200.0, None),
    ]


def test_stats() -> None:
    lats = [TurnLatency(i, v, None) for i, v in enumerate([100.0, 200.0, 300.0, 400.0])]
    lats.append(TurnLatency(4, None, "no agent audio"))
    s = latency_stats(lats)
    assert s.n == 4
    assert s.p50_ms == pytest.approx(250.0)
    assert s.p90_ms == pytest.approx(370.0)
    assert s.p95_ms == pytest.approx(385.0)
    assert s.max_ms == 400.0
    assert all(type(v) is float for v in (s.p50_ms, s.p90_ms, s.p95_ms, s.max_ms))


def test_stats_empty() -> None:
    assert latency_stats([]) == LatencyStats(0, None, None, None, None)


def _stop(
    turn: int, onset: float | None, stop: float | None, result: str, via: str | None
) -> StopLatency:
    return StopLatency(turn, 1000.0, onset, stop, result, via)  # type: ignore[arg-type]


def test_barge_turn_latency_skips_old_reply() -> None:
    # The old reply plays until onset + 340 = 5340, past the speech end at 5200.
    events = [
        _start(5000.0, 1),
        _end(5200.0, 1),
        _audio(5300.0, -20.0),
        _audio(5340.0, -20.0),
        _audio(5900.0, -20.0),
    ]
    assert response_latencies(events)[0].latency_ms == 100.0
    stops = [_stop(1, 5000.0, 340.0, "yielded", "audio")]
    assert response_latencies(events, stops=stops) == [TurnLatency(1, 700.0, None)]


def test_did_not_yield_turn_has_no_latency() -> None:
    events = [_start(5000.0, 1), _end(5200.0, 1), _audio(5300.0, -20.0)]
    stops = [_stop(1, 5000.0, None, "did_not_yield", None)]
    assert response_latencies(events, stops=stops) == [TurnLatency(1, None, "agent did not yield")]


def test_agent_finished_first_turn_is_measured_as_usual() -> None:
    events = [_start(5000.0, 1), _end(5200.0, 1), _audio(5300.0, -20.0)]
    stops = [_stop(1, None, None, "agent_finished_first", None)]
    assert response_latencies(events, stops=stops)[0].latency_ms == 100.0

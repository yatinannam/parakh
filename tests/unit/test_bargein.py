from typing import Any

from parakh.score.bargein import StopLatency, false_barge_ins, stop_latencies

ONSET = 5000.0


def _barge(t: float = ONSET, turn: int = 1) -> dict[str, Any]:
    return {"kind": "barge_in", "t_ms": t, "turn": turn, "after_agent_ms": 1200.0}


def _audio(play_ms: float | None, duration_ms: float = 20.0, dbfs: float = -20.0) -> dict[str, Any]:
    return {
        "kind": "agent_audio",
        "t_ms": 0.0 if play_ms is None else play_ms,
        "duration_ms": duration_ms,
        "dbfs": dbfs,
        "sample_rate": 8000,
        "play_ms": play_ms,
    }


def _run(start: float, end: float) -> list[dict[str, Any]]:
    """Contiguous 20 ms loud frames covering [start, end)."""
    n = round((end - start) / 20)
    return [_audio(start + 20.0 * i) for i in range(n)]


def _interruption(t: float) -> dict[str, Any]:
    return {"kind": "agent_interruption", "t_ms": t, "flushed_ms": 100.0}


def _only(events: list[dict[str, Any]]) -> StopLatency:
    (stop,) = stop_latencies(events)
    return stop


def test_stop_by_interruption() -> None:
    events = [_barge(), *_run(4000.0, 7000.0), _interruption(5340.0)]
    stop = _only(events)
    assert stop == StopLatency(1, 1200.0, ONSET, 340.0, "yielded", "interruption")


def test_stop_by_audio_gap() -> None:
    events = [_barge(), *_run(4000.0, 5340.0), *_run(5700.0, 5800.0)]
    stop = _only(events)
    assert stop.stop_latency_ms == 340.0
    assert stop.via == "audio"
    assert stop.result == "yielded"


def test_first_of_interruption_and_gap() -> None:
    events = [_barge(), *_run(4000.0, 5300.0), *_run(5700.0, 6000.0), _interruption(5450.0)]
    stop = _only(events)
    assert stop.stop_latency_ms == 300.0
    assert stop.via == "audio"


def test_tie_prefers_interruption() -> None:
    events = [_barge(), *_run(4000.0, 5300.0), _interruption(5300.0)]
    assert _only(events).via == "interruption"


def test_interruption_before_onset_is_ignored() -> None:
    events = [_barge(), *_run(4000.0, 5300.0), _interruption(4900.0)]
    assert _only(events).via == "audio"


def test_short_gap_does_not_end_stop() -> None:
    events = [_barge(), *_run(4000.0, 5200.0), *_run(5360.0, 5600.0), *_run(5900.0, 6000.0)]
    stop = _only(events)
    assert stop.stop_latency_ms == 600.0
    assert stop.via == "audio"


def test_did_not_yield_after_2s() -> None:
    events = [_barge(), *_run(4000.0, 7100.0)]
    stop = _only(events)
    assert stop.result == "did_not_yield"
    assert stop.stop_latency_ms is None
    assert stop.via is None
    assert stop.onset_ms == ONSET


def test_agent_finished_first() -> None:
    missed = {"kind": "barge_in_missed", "t_ms": 5000.0, "turn": 2, "after_agent_ms": 900.0}
    assert _only([missed]) == StopLatency(2, 900.0, None, None, "agent_finished_first", None)


def test_silent_and_unplaced_frames_ignored() -> None:
    events = [
        _barge(),
        *_run(4000.0, 5100.0),
        _audio(5100.0, 500.0, dbfs=-60.0),
        _audio(None, 500.0),
        _audio(5150.0, 500.0, dbfs=-60.0),
    ]
    assert _only(events).stop_latency_ms == 100.0


def test_one_result_per_event_in_order() -> None:
    events = [_barge(5000.0, 1), {**_barge(9000.0, 3)}, *_run(4000.0, 5100.0)]
    assert [s.turn for s in stop_latencies(events)] == [1, 3]


def _turn(turn: int, start: float, end: float) -> list[dict[str, Any]]:
    return [
        {"kind": "caller_turn_start", "t_ms": start, "turn": turn},
        {"kind": "caller_turn_end", "t_ms": end, "turn": turn},
    ]


def _user_started(t: float) -> dict[str, Any]:
    return {"kind": "user_started", "t_ms": t}


def test_false_barge_in_outside_turns() -> None:
    events = [
        *_turn(0, 1000.0, 3000.0),
        _user_started(2000.0),
        _user_started(3300.0),
        _user_started(3900.0),
    ]
    assert false_barge_ins(events) == [3900.0]


def test_false_barge_in_falls_back_to_interruptions() -> None:
    events = [*_turn(0, 1000.0, 3000.0), _interruption(2000.0), _interruption(4000.0)]
    assert false_barge_ins(events) == [4000.0]


def test_user_started_wins_over_interruptions() -> None:
    events = [*_turn(0, 1000.0, 3000.0), _user_started(2000.0), _interruption(4000.0)]
    assert false_barge_ins(events) == []


def test_false_barge_in_before_first_turn() -> None:
    events = [*_turn(0, 1000.0, 3000.0), _user_started(200.0)]
    assert false_barge_ins(events) == [200.0]

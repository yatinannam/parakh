"""Per-turn response latency and percentile summary over recorded call events."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from parakh.audio import SPEECH_DBFS
from parakh.score.bargein import StopLatency


@dataclass(frozen=True)
class TurnLatency:
    turn: int
    latency_ms: float | None
    reason: str | None


@dataclass(frozen=True)
class LatencyStats:
    n: int
    p50_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    max_ms: float | None


def response_latencies(
    events: list[dict[str, Any]],
    threshold_dbfs: float = SPEECH_DBFS,
    stops: Sequence[StopLatency] = (),
) -> list[TurnLatency]:
    """Latency from each caller speech end to the first loud agent audio after it.

    A barge-in turn whose agent yielded counts the reply from the moment the old
    reply stopped; one whose agent did not yield has no latency.
    """
    by_turn = {s.turn: s for s in stops}
    turn_starts = [float(e["t_ms"]) for e in events if e["kind"] == "caller_turn_start"]
    audio = sorted(
        float(e["t_ms"])
        for e in events
        if e["kind"] == "agent_audio" and e["dbfs"] > threshold_dbfs
    )
    ends = sorted(
        (e for e in events if e["kind"] == "caller_speech_end"),
        key=lambda e: int(e["turn"]),
    )
    results: list[TurnLatency] = []
    for end in ends:
        turn = int(end["turn"])
        end_ms = float(end["t_ms"])
        stop = by_turn.get(turn)
        if stop is not None and stop.result == "did_not_yield":
            results.append(TurnLatency(turn, None, "agent did not yield"))
            continue
        # A yielded agent's old reply may still be arriving past the speech end.
        search_from = end_ms
        if stop is not None and stop.onset_ms is not None and stop.stop_latency_ms is not None:
            search_from = max(end_ms, stop.onset_ms + stop.stop_latency_ms)
        limit = min((t for t in turn_starts if t > end_ms), default=float("inf"))
        reply = next((t for t in audio if search_from < t < limit), None)
        if reply is None:
            results.append(TurnLatency(turn, None, "no agent audio"))
        else:
            results.append(TurnLatency(turn, reply - end_ms, None))
    return results


def latency_stats(latencies: list[TurnLatency]) -> LatencyStats:
    values = [x.latency_ms for x in latencies if x.latency_ms is not None]
    if not values:
        return LatencyStats(0, None, None, None, None)
    p50, p90, p95 = (float(v) for v in np.percentile(values, [50, 90, 95]))
    return LatencyStats(len(values), p50, p90, p95, float(max(values)))

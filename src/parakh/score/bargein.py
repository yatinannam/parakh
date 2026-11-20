"""Barge-in scoring: how fast the agent stops talking, and interruptions nobody asked for."""

from dataclasses import dataclass
from typing import Any, Literal

from parakh.audio import SPEECH_DBFS

STOP_GAP_MS = 200.0
DID_NOT_YIELD_MS = 2000.0
FALSE_BARGE_IN_GRACE_MS = 500.0


@dataclass(frozen=True)
class StopLatency:
    turn: int
    after_agent_ms: float
    onset_ms: float | None
    stop_latency_ms: float | None
    result: Literal["yielded", "did_not_yield", "agent_finished_first"]
    via: Literal["interruption", "audio"] | None


def _audio_stop(events: list[dict[str, Any]], onset: float, threshold_dbfs: float) -> float:
    """End of the agent's continuous loud audio that is still playing at the onset."""
    frames = sorted(
        (float(e["play_ms"]), float(e["duration_ms"]))
        for e in events
        if e["kind"] == "agent_audio"
        and e["dbfs"] > threshold_dbfs
        and e.get("play_ms") is not None
        and float(e["play_ms"]) + float(e["duration_ms"]) > onset
    )
    end = onset
    for start, duration in frames:
        if start - end >= STOP_GAP_MS:
            break
        end = max(end, start + duration)
    return end


def stop_latencies(
    events: list[dict[str, Any]], threshold_dbfs: float = SPEECH_DBFS
) -> list[StopLatency]:
    """One result per barge_in / barge_in_missed event, in event order."""
    results: list[StopLatency] = []
    for e in events:
        if e["kind"] == "barge_in_missed":
            results.append(
                StopLatency(
                    int(e["turn"]),
                    float(e["after_agent_ms"]),
                    None,
                    None,
                    "agent_finished_first",
                    None,
                )
            )
        elif e["kind"] == "barge_in":
            onset = float(e["t_ms"])
            audio = _audio_stop(events, onset, threshold_dbfs)
            cut = min(
                (
                    float(x["t_ms"])
                    for x in events
                    if x["kind"] == "agent_interruption" and float(x["t_ms"]) >= onset
                ),
                default=None,
            )
            via: Literal["interruption", "audio"] = (
                "interruption" if cut is not None and cut <= audio else "audio"
            )
            stop = (audio if cut is None else min(audio, cut)) - onset
            yielded = stop <= DID_NOT_YIELD_MS
            results.append(
                StopLatency(
                    int(e["turn"]),
                    float(e["after_agent_ms"]),
                    onset,
                    stop if yielded else None,
                    "yielded" if yielded else "did_not_yield",
                    via if yielded else None,
                )
            )
    return results


def false_barge_ins(
    events: list[dict[str, Any]], grace_ms: float = FALSE_BARGE_IN_GRACE_MS
) -> list[float]:
    """Times the agent heard a user outside any caller turn (plus a grace after each).

    Candidates are the agent's user-started messages when it sent any, else its
    interruption frames.
    """
    starts = {int(e["turn"]): float(e["t_ms"]) for e in events if e["kind"] == "caller_turn_start"}
    ends = {int(e["turn"]): float(e["t_ms"]) for e in events if e["kind"] == "caller_turn_end"}
    spans = [(s, ends.get(t, float("inf")) + grace_ms) for t, s in starts.items()]
    kind = (
        "user_started" if any(e["kind"] == "user_started" for e in events) else "agent_interruption"
    )
    times = [float(e["t_ms"]) for e in events if e["kind"] == kind]
    return [t for t in times if not any(s <= t <= end for s, end in spans)]

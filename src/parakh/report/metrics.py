"""Metrics read from the agent's RTVI metrics events."""

import math
from typing import Any


def ttfb_ms(data: Any) -> list[float]:
    """Every numeric `value` (seconds) in data["ttfb"], in ms; malformed entries are skipped."""
    if not isinstance(data, dict):
        return []
    entries = data.get("ttfb")
    if not isinstance(entries, list):
        return []
    out: list[float] = []
    for entry in entries:
        value = entry.get("value") if isinstance(entry, dict) else None
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        ):
            out.append(float(value) * 1000)
    return out


def agent_token_usage(events: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """(total tokens, LLM requests) summed from agent_metrics events' data["tokens"].

    One entry is one LLM completion. An entry counts only when it is a dict with a
    numeric, non-negative, non-bool total_tokens. None, None when nothing counts.
    """
    total = requests = 0
    for event in events:
        data = event.get("data")
        if event["kind"] != "agent_metrics" or not isinstance(data, dict):
            continue
        entries = data.get("tokens")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            value = entry.get("total_tokens") if isinstance(entry, dict) else None
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            if not math.isfinite(value) or value < 0:
                continue
            total += int(value)
            requests += 1
    return (total, requests) if requests else (None, None)

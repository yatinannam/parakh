from typing import Any

from parakh.report.model import (
    NO_DATA,
    TURN_NOT_REACHED,
    BargeInReport,
    Report,
    TurnReport,
)
from tests.fakes import make_report


def turn(
    index: int,
    *,
    say: str = "namaste",
    heard: str = "namaste",
    reply: str = "Hello, how can I help?",
    reason: str | None = None,
    barge_in: BargeInReport | None = None,
) -> TurnReport:
    return TurnReport(
        index=index,
        say=say,
        reference=say,
        transcript=heard,
        latency_ms=700.0,
        latency_reason=reason,
        strict_wer=0.0,
        loose_wer=0.0,
        agent_text=reply,
        agent_ttfb_ms=[],
        barge_in=barge_in,
    )


def not_reached(index: int) -> TurnReport:
    t = turn(index, heard="", reply="", reason=TURN_NOT_REACHED)
    return t.model_copy(update={"latency_ms": None})


def no_data(index: int) -> TurnReport:
    return not_reached(index).model_copy(update={"latency_reason": NO_DATA})


def report(
    *turns: TurnReport,
    goal: str | None = "Book a slot",
    status: str = "completed",
    title: str = "Scenario one",
    agent_url: str = "ws://h",
    agent_info: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> Report:
    base = make_report(status=status, title=title)
    return base.model_copy(
        update={
            "turns": list(turns),
            "scenario_goal": goal,
            "agent_url": agent_url,
            "agent_info": agent_info or {},
            "warnings": warnings or [],
        }
    )

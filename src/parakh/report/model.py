"""Versioned pydantic schema for report.json."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatencyStatsModel(_Strict):
    n: int
    p50_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    max_ms: float | None


class JitterModel(_Strict):
    n: int
    p50_ms: float
    p99_ms: float
    max_ms: float


class TurnReport(_Strict):
    index: int
    say: str
    reference: str
    transcript: str
    latency_ms: float | None
    latency_reason: str | None
    strict_wer: float | None
    loose_wer: float | None
    agent_text: str
    # TTFB values from RTVI metrics messages during the turn, converted from seconds to ms.
    agent_ttfb_ms: list[float]


class Metrics(_Strict):
    latency: LatencyStatsModel
    strict_wer: float | None
    loose_wer: float | None
    loose_cer: float | None
    wer_reason: str | None


class Report(_Strict):
    schema_version: Literal[1] = 1
    parakh_version: str
    git_sha: str | None
    run_id: str
    created_at: str
    scenario_id: str
    scenario_title: str
    language: str
    preset: str
    seed: int | None
    agent_url: str
    agent_info: dict[str, Any]
    status: str
    timing_unreliable: bool
    jitter: JitterModel
    cpu_max_percent: float
    turns: list[TurnReport]
    metrics: Metrics
    task_success: None = None
    judge: None = None
    warnings: list[str]


def write_report_json(report: Report, path: Path) -> None:
    # model_dump_json keeps non-ASCII text as-is, so Devanagari stays readable.
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_report(path: Path) -> Report:
    return Report.model_validate_json(path.read_text(encoding="utf-8"))

"""Versioned pydantic schema for report.json."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from parakh.judge.model import JudgeScores


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


class TurnDegradation(_Strict):
    snr_db: float | None
    frames: int
    lost_frames: int
    clipped_samples: int


class BargeInReport(_Strict):
    after_agent_ms: float
    onset_ms: float | None
    stop_latency_ms: float | None
    result: Literal["yielded", "did_not_yield", "agent_finished_first"]
    via: Literal["interruption", "audio"] | None


# latency_reason values that mean a turn never ran: the caller did not get to it, or a
# fallback report has no data at all.
TURN_NOT_REACHED = "turn not reached"
NO_DATA = "no data"


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
    # Default so reports written before presets existed still load under schema_version 1.
    degradation: TurnDegradation | None = None
    barge_in: BargeInReport | None = None


class Metrics(_Strict):
    latency: LatencyStatsModel
    strict_wer: float | None
    loose_wer: float | None
    loose_cer: float | None
    wer_reason: str | None
    # Defaults so reports written before barge-in scoring still load under schema_version 1.
    # stop_latency is None when the scenario has no barge-in.
    stop_latency: LatencyStatsModel | None = None
    did_not_yield: int = 0
    false_barge_in_ms: list[float] = []
    # Turn indices whose transcript holds Urdu (Perso-Arabic) script: no loose WER (EC-41).
    script_unsupported_turns: list[int] = []
    # Summed from the agent's RTVI LLM usage metrics; None when it reports none.
    agent_llm_tokens: int | None = None
    agent_llm_requests: int | None = None


class JudgeReport(_Strict):
    status: Literal["ok", "judge_error", "rate_limited", "skipped"]
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    prompt_version: str
    scores: JudgeScores | None = None
    attempts: int = 0
    cached: bool = False
    tokens: int | None = None
    reason: str | None = None


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
    judge: JudgeReport | None = None
    warnings: list[str]
    # Default so reports written before the judge existed still load under schema_version 1.
    scenario_goal: str | None = None


def write_report_json(report: Report, path: Path) -> None:
    # model_dump_json keeps non-ASCII text as-is, so Devanagari stays readable.
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_report(path: Path) -> Report:
    return Report.model_validate_json(path.read_text(encoding="utf-8"))

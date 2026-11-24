"""Report assembly: the scored report, the interrupted partial report and the fallback."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import parakh
from parakh import __version__
from parakh.budget.quota import looks_rate_limited
from parakh.caller.driver import CallResult
from parakh.caller.line import CallerLine
from parakh.caller.pacer import JitterStats
from parakh.caller.recorder import read_events
from parakh.report.metrics import agent_token_usage, ttfb_ms
from parakh.report.model import (
    NO_DATA,
    TURN_NOT_REACHED,
    BargeInReport,
    JitterModel,
    LatencyStatsModel,
    Metrics,
    Report,
    TurnDegradation,
    TurnReport,
)
from parakh.scenario import Scenario
from parakh.score.bargein import false_barge_ins, stop_latencies
from parakh.score.latency import TurnLatency, latency_stats, response_latencies
from parakh.score.wer import conversation_wer, group_by_turn, loose_wer, strict_wer
from parakh.transport.ws import redact_url

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _installed_from_repo() -> bool:
    """True when parakh was imported from this checkout's src directory."""
    try:
        Path(parakh.__file__).resolve().relative_to((_REPO_ROOT / "src").resolve())
    except ValueError:
        return False
    return True


def _git_sha() -> str | None:
    """Short sha of the checkout parakh runs from; None for an installed copy or a git failure."""
    if not (_REPO_ROOT / ".git").exists() or not _installed_from_repo():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = result.stdout.decode("utf-8", "replace").strip()
    return sha if result.returncode == 0 and sha else None


def _degradation(line: CallerLine | None, index: int) -> TurnDegradation | None:
    if line is None or index >= len(line.turns):
        return None
    s = line.turns[index].stats
    if s is None:
        return None
    return TurnDegradation(
        snr_db=s.snr_db,
        frames=s.frames,
        lost_frames=s.lost_frames,
        clipped_samples=s.clipped_samples,
    )


def _status(result: CallResult) -> str:
    """The call's status, or rate_limited when the agent itself reported a 429 (EC-11)."""
    if result.status in ("turn_timeout", "call_timeout") and any(
        w.startswith("agent error") and looks_rate_limited(w) for w in result.warnings
    ):
        return "rate_limited"
    return result.status


def build_report(
    scenario: Scenario,
    result: CallResult,
    events: list[dict[str, Any]],
    *,
    run_id: str,
    agent_url: str,
    preset: str,
    line: CallerLine | None = None,
) -> Report:
    count = len(scenario.turns)
    starts = [float(e["t_ms"]) for e in events if e["kind"] == "caller_turn_start"]

    def grouped(items: list[tuple[float, Any]]) -> list[list[Any]]:
        groups = group_by_turn(starts, items)
        return groups + [[] for _ in range(count - len(groups))]

    finals = [
        (float(e["t_ms"]), str(e.get("text", "")))
        for e in events
        if e["kind"] == "caller_transcript" and e.get("final")
    ]
    bot = [
        (float(e["t_ms"]), str(e.get("text", "")))
        for e in events
        if e["kind"] == "bot_output" and e.get("text")
    ]
    ttfb = [
        (float(e["t_ms"]), v)
        for e in events
        if e["kind"] == "agent_metrics"
        for v in ttfb_ms(e.get("data"))
    ]
    # The greeting and anything else before the first caller turn belongs to no turn.
    first = starts[0] if starts else float("inf")
    transcripts = grouped(finals)
    agent_text = grouped([(t, v) for t, v in bot if t >= first])
    agent_ttfb = grouped([(t, v) for t, v in ttfb if t >= first])
    stops = stop_latencies(events)
    stop_by_turn = {s.turn: s for s in stops}
    latencies = response_latencies(events, stops=stops)
    by_turn = {x.turn: x for x in latencies}
    # Per-turn WER needs a reached turn and an agent that exposes a transcript at all
    # (otherwise metrics.wer_reason says why). A reached turn with an empty transcript
    # is then a full miss: strict_wer and loose_wer give 1.0 for it (EC-46).
    any_transcript = any(text.strip() for _t, text in finals)

    turns: list[TurnReport] = []
    for index, turn in enumerate(scenario.turns):
        text = " ".join(transcripts[index])
        lat = by_turn.get(index)
        reached = index < len(starts)
        scored = reached and any_transcript
        if not reached:
            reason: str | None = TURN_NOT_REACHED
        else:
            reason = None if lat is None else lat.reason
        stop = stop_by_turn.get(index)
        turns.append(
            TurnReport(
                index=index,
                say=turn.say,
                reference=turn.reference,
                transcript=text,
                latency_ms=None if lat is None else lat.latency_ms,
                latency_reason=reason,
                strict_wer=strict_wer(turn.reference, text) if scored else None,
                loose_wer=loose_wer(turn.reference, text) if scored else None,
                agent_text=" ".join(agent_text[index]),
                agent_ttfb_ms=list(agent_ttfb[index]),
                degradation=_degradation(line, index) if reached else None,
                barge_in=None
                if stop is None
                else BargeInReport(
                    after_agent_ms=stop.after_agent_ms,
                    onset_ms=stop.onset_ms,
                    stop_latency_ms=stop.stop_latency_ms,
                    result=stop.result,
                    via=stop.via,
                ),
            )
        )
    wer = conversation_wer([t.reference for t in scenario.turns], transcripts)
    stats = latency_stats(latencies)
    jitter = result.jitter
    stop_stats = latency_stats(
        [TurnLatency(s.turn, s.stop_latency_ms, None) for s in stops if s.result == "yielded"]
    )
    llm_tokens, llm_requests = agent_token_usage(events)
    return Report(
        parakh_version=__version__,
        git_sha=_git_sha(),
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        scenario_id=scenario.id,
        scenario_title=scenario.title,
        language=scenario.language,
        preset=preset,
        seed=None if line is None else line.seed,
        agent_url=redact_url(agent_url),
        agent_info=result.agent_info,
        status=_status(result),
        timing_unreliable=result.timing_unreliable,
        jitter=JitterModel(
            n=jitter.n, p50_ms=jitter.p50_ms, p99_ms=jitter.p99_ms, max_ms=jitter.max_ms
        ),
        cpu_max_percent=result.cpu_max_percent,
        turns=turns,
        metrics=Metrics(
            latency=LatencyStatsModel(
                n=stats.n,
                p50_ms=stats.p50_ms,
                p90_ms=stats.p90_ms,
                p95_ms=stats.p95_ms,
                max_ms=stats.max_ms,
            ),
            strict_wer=wer.strict_wer,
            loose_wer=wer.loose_wer,
            loose_cer=wer.loose_cer,
            wer_reason=wer.reason,
            stop_latency=None
            if not stops
            else LatencyStatsModel(
                n=stop_stats.n,
                p50_ms=stop_stats.p50_ms,
                p90_ms=stop_stats.p90_ms,
                p95_ms=stop_stats.p95_ms,
                max_ms=stop_stats.max_ms,
            ),
            did_not_yield=sum(1 for s in stops if s.result == "did_not_yield"),
            false_barge_in_ms=false_barge_ins(events),
            script_unsupported_turns=wer.script_unsupported_turns,
            agent_llm_tokens=llm_tokens,
            agent_llm_requests=llm_requests,
        ),
        warnings=result.warnings,
        scenario_goal=scenario.goal,
    )


INTERRUPT_WARNING = "interrupted by the user"


def interrupted_report(
    scenario: Scenario,
    run_id: str,
    run_dir: Path,
    agent_url: str,
    preset: str,
    line: CallerLine | None = None,
) -> Report:
    """Partial report from the events recorded so far; the minimal fallback without any."""
    try:
        events = read_events(run_dir)
    except (OSError, ValueError):
        events = []
    if not events:
        return fallback_report(
            scenario, run_id, agent_url, preset, "interrupted", [INTERRUPT_WARNING]
        )
    try:
        infos = [
            e["info"]
            for e in events
            if e["kind"] == "agent_info" and isinstance(e.get("info"), dict)
        ]
        warnings = [str(e["message"]) for e in events if e["kind"] == "warning" and "message" in e]
        starts = sum(1 for e in events if e["kind"] == "caller_turn_start")
        stand_in = CallResult(
            status="interrupted",
            run_dir=run_dir,
            turns_started=starts,
            jitter=JitterStats(n=0, p50_ms=0.0, p99_ms=0.0, max_ms=0.0),
            timing_unreliable=False,
            cpu_max_percent=0.0,
            agent_info=infos[-1] if infos else {},
            warnings=[*warnings, INTERRUPT_WARNING],
        )
        return build_report(
            scenario, stand_in, events, run_id=run_id, agent_url=agent_url, preset=preset, line=line
        )
    except Exception as exc:  # a half-written event must not lose the interrupt
        return fallback_report(
            scenario,
            run_id,
            agent_url,
            preset,
            "interrupted",
            [INTERRUPT_WARNING, f"partial report failed: {type(exc).__name__}"],
        )


def fallback_report(
    scenario: Scenario,
    run_id: str,
    agent_url: str,
    preset: str,
    status: str,
    warnings: list[str],
) -> Report:
    """Minimal report for a run that failed outside the call itself."""
    return Report(
        parakh_version=__version__,
        git_sha=_git_sha(),
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        scenario_id=scenario.id,
        scenario_title=scenario.title,
        language=scenario.language,
        preset=preset,
        seed=None,
        agent_url=redact_url(agent_url),
        agent_info={},
        status=status,
        timing_unreliable=False,
        jitter=JitterModel(n=0, p50_ms=0.0, p99_ms=0.0, max_ms=0.0),
        cpu_max_percent=0.0,
        turns=[
            TurnReport(
                index=i,
                say=t.say,
                reference=t.reference,
                transcript="",
                latency_ms=None,
                latency_reason=NO_DATA,
                strict_wer=None,
                loose_wer=None,
                agent_text="",
                agent_ttfb_ms=[],
            )
            for i, t in enumerate(scenario.turns)
        ],
        metrics=Metrics(
            latency=LatencyStatsModel(n=0, p50_ms=None, p90_ms=None, p95_ms=None, max_ms=None),
            strict_wer=None,
            loose_wer=None,
            loose_cer=None,
            wer_reason=None,
        ),
        warnings=warnings,
        scenario_goal=scenario.goal,
    )

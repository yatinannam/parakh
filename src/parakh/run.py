"""One scored run: synthesize caller audio, drive the call, score, write the reports."""

import asyncio
import math
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parakh import __version__
from parakh.caller.driver import CallResult, run_call
from parakh.caller.recorder import read_events
from parakh.report.html import write_report_html
from parakh.report.model import (
    JitterModel,
    LatencyStatsModel,
    Metrics,
    Report,
    TurnReport,
    write_report_json,
)
from parakh.scenario import Scenario, load_scenario
from parakh.score.latency import latency_stats, response_latencies
from parakh.score.wer import conversation_wer, group_by_turn, loose_wer, strict_wer
from parakh.transport.codec import ProtocolError
from parakh.transport.ws import check_agent_url, redact_url
from parakh.tts.cache import DEFAULT_CACHE_ROOT, TTSCache, build_scenario_audio
from parakh.tts.engine import EdgeTTSEngine, TTSEngine
from parakh.tts.ffmpeg import require_ffmpeg

PRESETS = ("clean",)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def exit_code(report: Report) -> int:
    """0 completed, 1 agent hung up before the first turn, 2 anything else."""
    if report.timing_unreliable:
        return 2
    if report.status == "completed":
        return 0
    return 1 if report.status == "agent_hung_up_early" else 2


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    sha = result.stdout.decode("utf-8", "replace").strip()
    return sha if result.returncode == 0 and sha else None


def _ttfb_ms(data: Any) -> list[float]:
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


def _build_report(
    scenario: Scenario,
    result: CallResult,
    events: list[dict[str, Any]],
    *,
    run_id: str,
    agent_url: str,
    preset: str,
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
        for v in _ttfb_ms(e.get("data"))
    ]
    # The greeting and anything else before the first caller turn belongs to no turn.
    first = starts[0] if starts else float("inf")
    transcripts = grouped(finals)
    agent_text = grouped([(t, v) for t, v in bot if t >= first])
    agent_ttfb = grouped([(t, v) for t, v in ttfb if t >= first])
    latencies = response_latencies(events)
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
            reason: str | None = "turn not reached"
        else:
            reason = None if lat is None else lat.reason
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
            )
        )
    wer = conversation_wer([t.reference for t in scenario.turns], transcripts)
    stats = latency_stats(latencies)
    jitter = result.jitter
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
        agent_info=result.agent_info,
        status=result.status,
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
        ),
        warnings=result.warnings,
    )


async def run_scenario(
    scenario_path: Path,
    agent_url: str,
    *,
    preset: str = "clean",
    runs_dir: Path = Path("runs"),
    agent_rate: int = 16000,
    engine: TTSEngine | None = None,
    cache_dir: Path = DEFAULT_CACHE_ROOT,
) -> tuple[Report, Path]:
    """Run one scenario against an agent; always write report.json and report.html.

    Raises ValueError (unknown preset, bad agent URL), ScenarioError and FfmpegMissing
    before anything is written to runs_dir.
    """
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; available: {', '.join(PRESETS)}")
    check_agent_url(agent_url)
    scenario = load_scenario(scenario_path)
    require_ffmpeg()
    clips, _ = await build_scenario_audio(
        scenario, TTSCache(cache_dir), engine if engine is not None else EdgeTTSEngine()
    )
    run_id = secrets.token_hex(4)
    run_dir = runs_dir / run_id
    try:
        result = await run_call(agent_url, scenario, clips, run_dir, agent_rate=agent_rate)
        report = _build_report(
            scenario,
            result,
            read_events(run_dir),
            run_id=run_id,
            agent_url=agent_url,
            preset=preset,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        _write(_fallback_report(scenario, run_id, agent_url, preset, "interrupted", []), run_dir)
        raise
    except Exception as exc:
        status = "protocol_error" if isinstance(exc, ProtocolError) else "internal_error"
        message = str(exc).replace(agent_url, redact_url(agent_url))
        warning = f"{type(exc).__name__}: {message}"
        report = _fallback_report(scenario, run_id, agent_url, preset, status, [warning])
    _write(report, run_dir)
    return report, run_dir


def _write(report: Report, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_report_json(report, run_dir / "report.json")
    write_report_html(report, run_dir)


def _fallback_report(
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
                latency_reason="no data",
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
    )

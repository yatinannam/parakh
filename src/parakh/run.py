"""One scored run: synthesize caller audio, drive the call, score, write the reports."""

import asyncio
import contextlib
import secrets
from collections.abc import Callable
from pathlib import Path

from parakh.audio import SUPPORTED_RATES
from parakh.batch import BATCH_GAP_S, preflight, run_batch
from parakh.caller.driver import run_call
from parakh.caller.line import CallerLine, build_line
from parakh.caller.recorder import read_events
from parakh.degrade import get_preset
from parakh.judge.providers import load_config
from parakh.judge.runner import JudgeRunner
from parakh.report.build import (
    build_report,
    fallback_report,
    interrupted_report,
)
from parakh.report.html import write_report_html
from parakh.report.model import JudgeReport, Report, write_report_json
from parakh.scenario import Scenario, load_scenario
from parakh.transport.codec import ProtocolError
from parakh.transport.ws import check_agent_url, check_local_agent_url, redact_url
from parakh.tts.cache import DEFAULT_CACHE_ROOT, TTSCache, build_scenario_audio
from parakh.tts.engine import EdgeTTSEngine, TTSEngine
from parakh.tts.ffmpeg import require_ffmpeg
from parakh.tts.recordings import REAL_ROOT, load_recorded_clips

__all__ = ["BATCH_GAP_S", "exit_code", "preflight", "run_batch", "run_scenario"]


def exit_code(report: Report) -> int:
    """0 completed, 1 agent hung up before the first turn, 2 anything else."""
    if report.timing_unreliable:
        return 2
    if report.status == "completed":
        return 0
    return 1 if report.status == "agent_hung_up_early" else 2


async def run_scenario(
    scenario_path: Path,
    agent_url: str,
    *,
    preset: str = "clean",
    runs_dir: Path = Path("runs"),
    agent_rate: int = 16000,
    engine: TTSEngine | None = None,
    cache_dir: Path = DEFAULT_CACHE_ROOT,
    on_start: Callable[[Path], None] | None = None,
    judge: JudgeRunner | None = None,
    real: bool = False,
    real_root: Path = REAL_ROOT,
) -> tuple[Report, Path]:
    """Run one scenario against an agent; always write report.json and report.html.

    Raises ValueError (unknown preset, bad agent URL, unsupported agent_rate, a
    DegradeError such as a silent scenario under a noise preset), ScenarioError and
    FfmpegMissing before anything is written to runs_dir.
    on_start is called once with the run directory just before the call starts.
    On Ctrl+C a partial report is written (status "interrupted") and the interrupt
    is re-raised.
    judge, when given, rates every report (a fallback one is skipped by the judge itself)
    before it is written. It is advisory: a crash in it becomes judge_error and never
    changes the run's status.
    real plays the recordings under real_root (D10) instead of synthesised caller turns.
    The agent URL must then be loopback (ValueError), a missing, undecodable or silent
    recording raises RecordingError, and the call sends silence until the agent proves
    its STT is local. The report is marked real_audio, which makes the judge skip it.
    """
    get_preset(preset)  # ValueError for an unknown preset
    if agent_rate not in SUPPORTED_RATES:
        rates = ", ".join(str(r) for r in SUPPORTED_RATES)
        raise ValueError(f"agent_rate {agent_rate} is not supported; use one of: {rates}")
    check_agent_url(agent_url)
    if real:
        check_local_agent_url(agent_url)
    scenario = load_scenario(scenario_path)
    require_ffmpeg()
    run_id = secrets.token_hex(4)
    run_dir = runs_dir / run_id
    cache = TTSCache(cache_dir)
    tts = engine if engine is not None else EdgeTTSEngine()
    try:
        if real:
            clips = load_recorded_clips(scenario, real_root)
        else:
            clips, _ = await build_scenario_audio(scenario, cache, tts)
        line = await build_line(scenario, clips, preset, agent_rate, cache=cache, engine=tts)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _write_interrupted(scenario, run_id, run_dir, agent_url, preset, None, real)
        raise
    try:
        if on_start is not None:
            on_start(run_dir)
        result = await run_call(agent_url, scenario, line, run_dir, real=real)
        report = build_report(
            scenario,
            result,
            read_events(run_dir),
            run_id=run_id,
            agent_url=agent_url,
            preset=preset,
            line=line,
            real=real,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        _write_interrupted(scenario, run_id, run_dir, agent_url, preset, line, real)
        raise
    except Exception as exc:
        status = "protocol_error" if isinstance(exc, ProtocolError) else "internal_error"
        message = str(exc).replace(agent_url, redact_url(agent_url))
        warning = f"{type(exc).__name__}: {message}"
        report = fallback_report(scenario, run_id, agent_url, preset, status, [warning], real)
    if judge is not None:
        try:
            report = report.model_copy(update={"judge": await _judged(report, judge)})
        except (KeyboardInterrupt, asyncio.CancelledError):
            _write(report, run_dir)
            raise
    _write(report, run_dir)
    return report, run_dir


async def _judged(report: Report, judge: JudgeRunner) -> JudgeReport:
    """The judge's verdict; any unexpected exception becomes judge_error (never a crash)."""
    try:
        return await judge.judge(report)
    except Exception as exc:
        return JudgeReport(
            status="judge_error",
            prompt_version=load_config().prompt_version,
            reason=f"internal: {type(exc).__name__}",
        )


def _write_interrupted(
    scenario: Scenario,
    run_id: str,
    run_dir: Path,
    agent_url: str,
    preset: str,
    line: CallerLine | None = None,
    real: bool = False,
) -> None:
    """Write the partial report; a failure here must never mask the interrupt.

    line is None when Ctrl+C landed while the caller audio was still being rendered.
    """
    with contextlib.suppress(Exception):
        report = interrupted_report(scenario, run_id, run_dir, agent_url, preset, line, real)
        _write(report, run_dir)


def _write(report: Report, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_report_json(report, run_dir / "report.json")
    write_report_html(report, run_dir)

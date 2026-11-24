"""One scored run: synthesize caller audio, drive the call, score, write the reports."""

import asyncio
import contextlib
import secrets
from collections.abc import Callable
from pathlib import Path

from parakh.audio import SUPPORTED_RATES
from parakh.caller.driver import run_call
from parakh.caller.line import CallerLine, build_line
from parakh.caller.recorder import read_events
from parakh.degrade import get_preset
from parakh.degrade.track import noise_track
from parakh.judge.providers import load_config
from parakh.judge.runner import JudgeRunner
from parakh.report.build import (
    build_report,
    fallback_report,
    interrupted_report,
)
from parakh.report.compare import build_comparison, write_comparison
from parakh.report.html import write_report_html
from parakh.report.model import JudgeReport, Report, load_report, write_report_json
from parakh.scenario import Scenario, ScenarioError, load_scenario
from parakh.transport.codec import ProtocolError
from parakh.transport.ws import check_agent_url, redact_url
from parakh.tts.cache import DEFAULT_CACHE_ROOT, TTSCache, build_scenario_audio
from parakh.tts.engine import EdgeTTSEngine, TTSEngine
from parakh.tts.ffmpeg import require_ffmpeg

# Seconds between batch runs. The clinic agent's VAD can still be "hearing" the noise
# bed when a caller hangs up; Pipecat closes that segment about 0.4 s later and Groq
# transcribes it in under a second, so 3 s lets it land before the next call resets.
BATCH_GAP_S = 3.0


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
    """
    get_preset(preset)  # ValueError for an unknown preset
    if agent_rate not in SUPPORTED_RATES:
        rates = ", ".join(str(r) for r in SUPPORTED_RATES)
        raise ValueError(f"agent_rate {agent_rate} is not supported; use one of: {rates}")
    check_agent_url(agent_url)
    scenario = load_scenario(scenario_path)
    require_ffmpeg()
    run_id = secrets.token_hex(4)
    run_dir = runs_dir / run_id
    cache = TTSCache(cache_dir)
    tts = engine if engine is not None else EdgeTTSEngine()
    try:
        clips, _ = await build_scenario_audio(scenario, cache, tts)
        line = await build_line(scenario, clips, preset, agent_rate, cache=cache, engine=tts)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _write_interrupted(scenario, run_id, run_dir, agent_url, preset)
        raise
    try:
        if on_start is not None:
            on_start(run_dir)
        result = await run_call(agent_url, scenario, line, run_dir)
        report = build_report(
            scenario,
            result,
            read_events(run_dir),
            run_id=run_id,
            agent_url=agent_url,
            preset=preset,
            line=line,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        _write_interrupted(scenario, run_id, run_dir, agent_url, preset, line)
        raise
    except Exception as exc:
        status = "protocol_error" if isinstance(exc, ProtocolError) else "internal_error"
        message = str(exc).replace(agent_url, redact_url(agent_url))
        warning = f"{type(exc).__name__}: {message}"
        report = fallback_report(scenario, run_id, agent_url, preset, status, [warning])
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
) -> None:
    """Write the partial report; a failure here must never mask the interrupt.

    line is None when Ctrl+C landed while the caller audio was still being rendered.
    """
    with contextlib.suppress(Exception):
        report = interrupted_report(scenario, run_id, run_dir, agent_url, preset, line)
        _write(report, run_dir)


def _write(report: Report, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_report_json(report, run_dir / "report.json")
    write_report_html(report, run_dir)


async def preflight(
    scenario_paths: list[Path],
    presets: list[str],
    agent_url: str,
    agent_rate: int,
    *,
    engine: TTSEngine,
    cache_dir: Path,
) -> list[Scenario]:
    """Check everything a batch needs before its first call, so a late typo costs nothing.

    Validates presets, agent rate and URL, loads every scenario (a ScenarioError names its
    file), checks ffmpeg, then builds every caller clip and, when a preset uses babble,
    the babble talkers. Raises before anything is written to runs_dir.
    """
    specs = [get_preset(name) for name in presets]
    if agent_rate not in SUPPORTED_RATES:
        rates = ", ".join(str(r) for r in SUPPORTED_RATES)
        raise ValueError(f"agent_rate {agent_rate} is not supported; use one of: {rates}")
    check_agent_url(agent_url)
    scenarios = [load_scenario(path) for path in scenario_paths]
    seen: dict[str, Path] = {}
    for path, scenario in zip(scenario_paths, scenarios, strict=True):
        if scenario.id in seen:
            raise ScenarioError(
                f"scenario id {scenario.id!r} is used by both {seen[scenario.id]} and {path}"
            )
        seen[scenario.id] = path
    require_ffmpeg()
    cache = TTSCache(cache_dir)
    for scenario in scenarios:
        await build_scenario_audio(scenario, cache, engine)
    babble = next((s for s in specs if s.noise is not None and s.noise.kind == "babble"), None)
    if babble is not None:
        await noise_track(babble, 0, cache, engine)
    return scenarios


async def run_batch(
    scenario_paths: list[Path],
    agent_url: str,
    presets: list[str],
    *,
    runs_dir: Path,
    agent_rate: int = 16000,
    engine: TTSEngine | None = None,
    cache_dir: Path = DEFAULT_CACHE_ROOT,
    on_start: Callable[[Path], None] | None = None,
    on_batch: Callable[[Path], None] | None = None,
    gap_s: float = BATCH_GAP_S,
    on_done: Callable[[Report, Path], None] | None = None,
    on_warning: Callable[[str], None] | None = None,
    resume: Path | None = None,
    on_skip: Callable[[str, str], None] | None = None,
    judge: JudgeRunner | None = None,
) -> tuple[list[tuple[Report, Path]], Path | None]:
    """Run every scenario under every preset, back to back, in scenario then preset order.

    One pair runs like run_scenario (runs_dir/<run_id>, no comparison, batch dir None).
    More than one: runs go in runs_dir/<batch_id>/<run_id>/ and compare.html plus
    compare.json are rewritten after every run, so a stopped batch keeps its page.
    The comparison is built from every report.json in the batch directory, newest per
    (scenario id, preset), so it also shows runs from before a resume.
    A run that ends in any status does not stop the batch. Ctrl+C and errors raised
    before a call starts write the comparison for every run with a report, then re-raise.
    on_batch gets the batch dir once, before the first run, so a caller can show it
    even when the batch ends in an exception. Runs are gap_s apart, so an agent can
    finish what the previous call left (a segment its VAD was still hearing when the
    caller hung up) before the next caller connects and the agent resets its state.
    preflight runs first (also for one run); on_done gets (report, run_dir) after each run's reports
    are written; an OSError writing the comparison goes to on_warning and the batch goes on.

    resume is an existing batch directory: it becomes the batch directory, and every pair
    whose newest report there is clean (`exit_code` 0) is skipped (on_skip gets its scenario id and
    preset; on_done is not called). Only the runs made in this call are returned. Raises
    ValueError when resume holds no report.json. judge goes to every run_scenario call.
    """
    if resume is not None and not any(resume.glob("*/report.json")):
        raise ValueError(f"not a batch directory: {resume}")
    tts = engine if engine is not None else EdgeTTSEngine()
    scenarios = await preflight(
        scenario_paths, presets, agent_url, agent_rate, engine=tts, cache_dir=cache_dir
    )
    pairs = [
        (path, scenario.id, preset)
        for path, scenario in zip(scenario_paths, scenarios, strict=True)
        for preset in presets
    ]
    if resume is None and len(pairs) == 1:
        path, _, preset = pairs[0]
        single = await run_scenario(
            path,
            agent_url,
            preset=preset,
            runs_dir=runs_dir,
            agent_rate=agent_rate,
            engine=tts,
            cache_dir=cache_dir,
            on_start=on_start,
            judge=judge,
        )
        if on_done is not None:
            on_done(*single)
        return [single], None
    batch_dir = resume if resume is not None else runs_dir / secrets.token_hex(4)
    warned: set[str] = set()

    def warn(message: str) -> None:
        if on_warning is not None and message not in warned:
            warned.add(message)
            on_warning(message)

    completed: set[tuple[str, str]] = set()
    if resume is not None:
        completed = {
            (r.scenario_id, r.preset)
            for r, _ in _batch_reports(batch_dir, warn)
            if exit_code(r) == 0
        }
    done: list[tuple[Report, Path]] = []
    if on_batch is not None:
        on_batch(batch_dir)
    try:
        for path, scenario_id, preset in pairs:
            if (scenario_id, preset) in completed:
                if on_skip is not None:
                    on_skip(scenario_id, preset)
                continue
            if done and gap_s > 0:
                await asyncio.sleep(gap_s)
            done.append(
                await run_scenario(
                    path,
                    agent_url,
                    preset=preset,
                    runs_dir=batch_dir,
                    agent_rate=agent_rate,
                    engine=tts,
                    cache_dir=cache_dir,
                    on_start=on_start,
                    judge=judge,
                )
            )
            if on_done is not None:
                on_done(*done[-1])
            _write_comparison(_batch_reports(batch_dir, warn), batch_dir, on_warning)
        if not done:
            _write_comparison(_batch_reports(batch_dir, warn), batch_dir, on_warning)
    except BaseException:
        # The interrupted run has a partial report on disk but never returned.
        with contextlib.suppress(Exception):
            _write_comparison(_batch_reports(batch_dir, warn), batch_dir, on_warning)
        raise
    return done, batch_dir


def _batch_reports(
    batch_dir: Path, on_warning: Callable[[str], None] | None = None
) -> list[tuple[Report, Path]]:
    """Every readable */report.json in batch_dir, the newest per (scenario id, preset).

    Newest is by created_at; a tie goes to the later run directory name. Unreadable
    files go to on_warning.
    """
    newest: dict[tuple[str, str], tuple[tuple[str, str], Report, Path]] = {}
    for report_path in sorted(batch_dir.glob("*/report.json")):
        try:
            report = load_report(report_path)
        except (OSError, ValueError) as exc:
            if on_warning is not None:
                on_warning(f"skipped unreadable {report_path}: {type(exc).__name__}")
            continue
        key = (report.scenario_id, report.preset)
        rank = (report.created_at, report_path.parent.name)
        if key not in newest or rank > newest[key][0]:
            newest[key] = (rank, report, report_path.parent)
    return [(report, run_dir) for _, report, run_dir in newest.values()]


def _write_comparison(
    runs: list[tuple[Report, Path]],
    batch_dir: Path,
    on_warning: Callable[[str], None] | None = None,
) -> None:
    if not runs:
        return
    try:
        write_comparison(build_comparison(runs, batch_dir), batch_dir)
    except OSError as exc:
        if on_warning is not None:
            on_warning(f"could not write the comparison: {exc}")

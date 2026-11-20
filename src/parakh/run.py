"""One scored run: synthesize caller audio, drive the call, score, write the reports."""

import asyncio
import contextlib
import secrets
from collections.abc import Callable
from pathlib import Path

from parakh.audio import SUPPORTED_RATES
from parakh.caller.driver import run_call
from parakh.caller.line import build_line
from parakh.caller.recorder import read_events
from parakh.degrade import get_preset
from parakh.report.build import (
    build_report,
    fallback_report,
    interrupted_report,
)
from parakh.report.compare import build_comparison, write_comparison
from parakh.report.html import write_report_html
from parakh.report.model import Report, load_report, write_report_json
from parakh.scenario import Scenario, load_scenario
from parakh.transport.codec import ProtocolError
from parakh.transport.ws import check_agent_url, redact_url
from parakh.tts.cache import DEFAULT_CACHE_ROOT, TTSCache, build_scenario_audio
from parakh.tts.engine import EdgeTTSEngine, TTSEngine
from parakh.tts.ffmpeg import require_ffmpeg


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
) -> tuple[Report, Path]:
    """Run one scenario against an agent; always write report.json and report.html.

    Raises ValueError (unknown preset, bad agent URL, unsupported agent_rate, a
    DegradeError such as a silent scenario under a noise preset), ScenarioError and
    FfmpegMissing before anything is written to runs_dir.
    on_start is called once with the run directory just before the call starts.
    On Ctrl+C a partial report is written (status "interrupted") and the interrupt
    is re-raised.
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
        _write_interrupted(scenario, run_id, run_dir, agent_url, preset)
        raise
    except Exception as exc:
        status = "protocol_error" if isinstance(exc, ProtocolError) else "internal_error"
        message = str(exc).replace(agent_url, redact_url(agent_url))
        warning = f"{type(exc).__name__}: {message}"
        report = fallback_report(scenario, run_id, agent_url, preset, status, [warning])
    _write(report, run_dir)
    return report, run_dir


def _write_interrupted(
    scenario: Scenario, run_id: str, run_dir: Path, agent_url: str, preset: str
) -> None:
    """Write the partial report; a failure here must never mask the interrupt."""
    with contextlib.suppress(Exception):
        _write(interrupted_report(scenario, run_id, run_dir, agent_url, preset), run_dir)


def _write(report: Report, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_report_json(report, run_dir / "report.json")
    write_report_html(report, run_dir)


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
) -> tuple[list[tuple[Report, Path]], Path | None]:
    """Run every scenario under every preset, back to back, in scenario then preset order.

    One pair runs like run_scenario (runs_dir/<run_id>, no comparison, batch dir None).
    More than one: runs go in runs_dir/<batch_id>/<run_id>/ and compare.html plus
    compare.json are rewritten after every run, so a stopped batch keeps its page.
    A run that ends in any status does not stop the batch. Ctrl+C and errors raised
    before a call starts write the comparison for every run with a report, then re-raise.
    """
    pairs = [(path, preset) for path in scenario_paths for preset in presets]
    if len(pairs) == 1:
        path, preset = pairs[0]
        single = await run_scenario(
            path,
            agent_url,
            preset=preset,
            runs_dir=runs_dir,
            agent_rate=agent_rate,
            engine=engine,
            cache_dir=cache_dir,
            on_start=on_start,
        )
        return [single], None
    batch_dir = runs_dir / secrets.token_hex(4)
    done: list[tuple[Report, Path]] = []
    try:
        for path, preset in pairs:
            done.append(
                await run_scenario(
                    path,
                    agent_url,
                    preset=preset,
                    runs_dir=batch_dir,
                    agent_rate=agent_rate,
                    engine=engine,
                    cache_dir=cache_dir,
                    on_start=on_start,
                )
            )
            _write_comparison(done, batch_dir)
    except BaseException:
        # The interrupted run has a partial report on disk but never returned.
        known = {run_dir for _, run_dir in done}
        for report_path in sorted(batch_dir.glob("*/report.json")):
            if report_path.parent not in known:
                with contextlib.suppress(Exception):
                    done.append((load_report(report_path), report_path.parent))
        with contextlib.suppress(Exception):
            _write_comparison(done, batch_dir)
        raise
    return done, batch_dir


def _write_comparison(runs: list[tuple[Report, Path]], batch_dir: Path) -> None:
    if runs:
        write_comparison(build_comparison(runs, batch_dir), batch_dir)

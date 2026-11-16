"""Command-line entry point for Parakh."""

import asyncio
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import aiohttp
import typer
from edge_tts.exceptions import EdgeTTSException
from pydantic import ValidationError

from parakh import __version__
from parakh.budget.estimate import GROQ_LLM_ASSUMED, GROQ_STT_LIMITS, estimate
from parakh.console import configure_console
from parakh.report.html import write_report_html
from parakh.report.model import load_report
from parakh.run import exit_code, run_scenario
from parakh.scenario import ScenarioError, load_scenario
from parakh.tts.cache import DEFAULT_CACHE_ROOT, TTSCache, build_scenario_audio
from parakh.tts.engine import EdgeTTSEngine, TTSEngine
from parakh.tts.ffmpeg import FfmpegMissing

app = typer.Typer(help="Test voice agents on Indian speech.", no_args_is_help=True)
tts_app = typer.Typer(help="Caller audio commands.", no_args_is_help=True)
app.add_typer(tts_app, name="tts")


@app.callback()
def main() -> None:
    """Parakh command-line interface."""
    configure_console()


@app.command()
def version() -> None:
    """Print the Parakh version."""
    typer.echo(f"parakh {__version__}")


def make_engine() -> TTSEngine:
    """Create the caller TTS engine. Tests monkeypatch this."""
    return EdgeTTSEngine()


def _scenario_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.yaml")))
        else:
            files.append(path)
    return files


@tts_app.command("build")
def tts_build(
    paths: Annotated[list[Path], typer.Argument(help="Scenario files or directories.")],
    cache_dir: Annotated[Path, typer.Option(help="TTS cache directory.")] = DEFAULT_CACHE_ROOT,
) -> None:
    """Synthesize and cache caller audio for scenarios."""
    cache = TTSCache(cache_dir)
    engine = make_engine()

    async def run() -> tuple[int, int]:
        total = built = 0
        for file in _scenario_files(paths):
            clips, n_built = await build_scenario_audio(load_scenario(file), cache, engine)
            total += len(clips)
            built += n_built
        return total, built

    try:
        total, built = asyncio.run(run())
    except FfmpegMissing as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    except (OSError, EdgeTTSException, aiohttp.ClientError) as exc:
        typer.echo(f"tts build failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"{total} clips ({built} built, {total - built} cached)")


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(2)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(help="Scenario YAML file.")],
    agent: Annotated[str, typer.Option(help="Agent WebSocket URL, ws:// or wss://.")],
    preset: Annotated[str, typer.Option(help="Audio degradation preset.")] = "clean",
    runs_dir: Annotated[Path, typer.Option(help="Where run directories go.")] = Path("runs"),
    agent_rate: Annotated[int, typer.Option(help="Sample rate sent to the agent.")] = 16000,
    cache_dir: Annotated[Path, typer.Option(help="TTS cache directory.")] = DEFAULT_CACHE_ROOT,
) -> None:
    """Run one scenario against an agent and write report.json and report.html."""
    try:
        result, run_dir = asyncio.run(
            run_scenario(
                scenario,
                agent,
                preset=preset,
                runs_dir=runs_dir,
                agent_rate=agent_rate,
                engine=make_engine(),
                cache_dir=cache_dir,
            )
        )
    except (ValueError, ScenarioError, FfmpegMissing) as exc:
        raise _fail(str(exc)) from exc
    except (OSError, EdgeTTSException, aiohttp.ClientError) as exc:
        raise _fail(f"run failed: {type(exc).__name__}: {exc}") from exc
    latency = result.metrics.latency
    typer.echo(f"run dir: {run_dir}")
    typer.echo(f"status: {result.status}")
    if result.status == "agent_unreachable":
        parts = urlsplit(agent)
        typer.echo(f"could not connect to {parts.hostname}:{parts.port}")
    typer.echo(f"latency p50/p95: {_ms(latency.p50_ms)} / {_ms(latency.p95_ms)} ms")
    typer.echo(f"loose WER: {_pct(result.metrics.loose_wer)}")
    if result.timing_unreliable:
        typer.echo("timing unreliable: the caller could not keep its 20 ms pace")
    raise typer.Exit(exit_code(result))


@app.command()
def report(
    run_dir: Annotated[Path, typer.Argument(help="Run directory with report.json.")],
) -> None:
    """Re-render report.html from report.json."""
    try:
        loaded = load_report(run_dir / "report.json")
    except (OSError, ValidationError) as exc:
        raise _fail(f"cannot read report.json in {run_dir}: {exc}") from exc
    typer.echo(str(write_report_html(loaded, run_dir)))


@app.command()
def budget(
    paths: Annotated[list[Path], typer.Argument(help="Scenario files or directories.")],
) -> None:
    """Estimate Groq free-tier usage for scenarios."""
    try:
        scenarios = [load_scenario(file) for file in _scenario_files(paths)]
    except ScenarioError as exc:
        raise _fail(str(exc)) from exc
    est = estimate(scenarios)
    typer.echo(f"scenarios: {est.scenarios}")
    typer.echo(f"STT calls: {est.stt_calls} (limits {GROQ_STT_LIMITS})")
    typer.echo(f"LLM calls: {est.llm_calls} (assumed limits {GROQ_LLM_ASSUMED}; check the console)")
    typer.echo(f"audio seconds: {est.audio_seconds:.0f}")
    if est.within_limits:
        typer.echo("within limits")
        return
    for note in est.notes:
        typer.echo(note)
    raise typer.Exit(2)

"""Command-line entry point for Parakh."""

import asyncio
import os
import wave
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import aiohttp
import numpy as np
import typer
from edge_tts.exceptions import EdgeTTSException

from parakh import __version__
from parakh.audio import (
    SAMPLE_RATE,
    SUPPORTED_RATES,
    is_silent,
    read_wav,
    resample,
    write_wav,
)
from parakh.budget.estimate import GROQ_LLM_ASSUMED, GROQ_STT_LIMITS, estimate
from parakh.console import configure_console
from parakh.degrade.chain import degrade as degrade_clip
from parakh.degrade.filters import peak_normalise
from parakh.degrade.noise import DegradeError, noise_scale, noise_slice
from parakh.degrade.presets import expand_presets, get_preset
from parakh.degrade.seeds import part_rng
from parakh.degrade.track import noise_track
from parakh.report.compare import build_comparison, write_comparison
from parakh.report.html import write_report_html
from parakh.report.model import Report, load_report
from parakh.run import exit_code, run_batch
from parakh.scenario import ScenarioError, load_scenario
from parakh.transport.ws import redact_url
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
    except (FfmpegMissing, ScenarioError) as exc:
        raise _fail(str(exc)) from exc
    # ValueError: edge-tts rejects a malformed rate or pitch. RuntimeError: ffmpeg
    # could not decode the synthesised audio.
    except (OSError, EdgeTTSException, aiohttp.ClientError, ValueError, RuntimeError) as exc:
        raise _fail(f"tts build failed: {_describe(exc)}") from exc
    typer.echo(f"{total} clips ({built} built, {total - built} cached)")


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(2)


def _describe(exc: Exception) -> str:
    """Exception type and message on one line (ffmpeg errors span several)."""
    return f"{type(exc).__name__}: {' '.join(str(exc).split())}"


def _endpoint(url: str) -> str:
    """host:port of a ws URL, using the scheme default port when it has none."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return redact_url(url)
    if parts.hostname is None:
        return redact_url(url)
    port = port or (443 if parts.scheme == "wss" else 80)
    return f"{parts.hostname}:{port}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def _echo_comparison(batch_dirs: list[Path]) -> None:
    """Show where a stopped batch left its comparison page, if one was written."""
    if batch_dirs and (batch_dirs[0] / "compare.html").is_file():
        typer.echo(f"comparison: {batch_dirs[0] / 'compare.html'}", err=True)


def _echo_summary(result: Report, agent: str, *, batched: bool) -> None:
    """Print one run's summary; called as each run finishes."""
    latency = result.metrics.latency
    if batched:
        typer.echo(f"{result.scenario_id} / {result.preset}")
    typer.echo(f"status: {result.status}")
    if result.status == "agent_unreachable":
        typer.echo(f"could not connect to {_endpoint(agent)}")
    typer.echo(f"latency p50/p95: {_ms(latency.p50_ms)} / {_ms(latency.p95_ms)} ms")
    typer.echo(f"loose WER: {_pct(result.metrics.loose_wer)}")
    if result.timing_unreliable:
        typer.echo("timing unreliable: the caller could not keep its 20 ms pace")


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(help="Scenario YAML file or directory.")],
    agent: Annotated[str, typer.Option(help="Agent WebSocket URL, ws:// or wss://.")],
    preset: Annotated[
        list[str] | None,
        typer.Option(help="Degradation preset; repeat for several, or `all`. Default: clean."),
    ] = None,
    runs_dir: Annotated[Path, typer.Option(help="Where run directories go.")] = Path("runs"),
    agent_rate: Annotated[int, typer.Option(help="Sample rate sent to the agent.")] = 16000,
    cache_dir: Annotated[Path, typer.Option(help="TTS cache directory.")] = DEFAULT_CACHE_ROOT,
) -> None:
    """Run scenarios against an agent and write report.json and report.html per run.

    More than one run (several scenarios or presets) also writes compare.html.
    """
    batch_dirs: list[Path] = []

    def on_done(result: Report, _run_dir: Path) -> None:
        _echo_summary(result, agent, batched=len(batch_dirs) > 0)

    try:
        presets = expand_presets(preset or ["clean"])
        files = _scenario_files([scenario])
        if not files:
            raise ValueError(f"no scenario files found in {scenario}")
        results, batch_dir = asyncio.run(
            run_batch(
                files,
                agent,
                presets,
                runs_dir=runs_dir,
                agent_rate=agent_rate,
                engine=make_engine(),
                cache_dir=cache_dir,
                on_start=lambda run_dir: typer.echo(f"run dir: {run_dir}"),
                on_batch=batch_dirs.append,
                on_done=on_done,
                on_warning=lambda message: typer.echo(message, err=True),
            )
        )
    except KeyboardInterrupt:
        _echo_comparison(batch_dirs)
        # Click's default "Aborted!" exits 1, which would read as a failed task.
        typer.echo("interrupted", err=True)
        raise typer.Exit(2) from None
    except (ValueError, ScenarioError, FfmpegMissing) as exc:
        _echo_comparison(batch_dirs)
        raise _fail(str(exc)) from exc
    # RuntimeError: ffmpeg could not decode the synthesised caller audio.
    except (OSError, EdgeTTSException, aiohttp.ClientError, RuntimeError) as exc:
        _echo_comparison(batch_dirs)
        raise _fail(f"run failed: {_describe(exc)}") from exc
    if batch_dir is not None and (batch_dir / "compare.html").is_file():
        typer.echo(f"comparison: {batch_dir / 'compare.html'}")
    raise typer.Exit(max(exit_code(result) for result, _ in results))


def _default_compare_dir(run_dirs: list[Path]) -> Path:
    """Common parent of the run directories; one level up when it is itself a run."""
    resolved = [d.resolve() for d in run_dirs]
    try:
        common = Path(os.path.commonpath(resolved))
    except ValueError as exc:
        raise _fail("run directories are on different drives; pass --out") from exc
    return common.parent if common in resolved else common


@app.command()
def compare(
    run_dirs: Annotated[list[Path], typer.Argument(help="Run directories with report.json.")],
    out: Annotated[
        Path | None,
        typer.Option(help="Where compare.html goes (default: the common parent of the runs)."),
    ] = None,
) -> None:
    """Build compare.html and compare.json from existing run directories."""
    runs: list[tuple[Report, Path]] = []
    for run_dir in run_dirs:
        try:
            runs.append((load_report(run_dir / "report.json"), run_dir))
        # ValueError covers non-UTF-8 text and pydantic's ValidationError.
        except (OSError, ValueError) as exc:
            raise _fail(f"cannot read report.json in {run_dir}: {exc}") from exc
    target = out if out is not None else _default_compare_dir(run_dirs)
    typer.echo(str(write_comparison(build_comparison(runs, target), target)))


@app.command("degrade")
def degrade_command(
    clip: Annotated[Path, typer.Argument(help="16-bit mono WAV to degrade.")],
    preset: Annotated[str, typer.Option(help="Degradation preset.")],
    out: Annotated[Path | None, typer.Option(help="Output WAV path.")] = None,
    rate: Annotated[int, typer.Option(help="Output sample rate.")] = 16000,
    seed: Annotated[int, typer.Option(help="Call seed.")] = 0,
    cache_dir: Annotated[Path, typer.Option(help="TTS cache directory.")] = DEFAULT_CACHE_ROOT,
) -> None:
    """Degrade one WAV with a preset and write the result."""
    try:
        spec = get_preset(preset)
        if rate not in SUPPORTED_RATES:
            raise ValueError(f"--rate {rate} is not supported; use one of {SUPPORTED_RATES}")
        pcm, src_rate = read_wav(clip)
        if src_rate not in SUPPORTED_RATES:
            raise ValueError(f"{clip} has unsupported sample rate {src_rate}")
        pcm = resample(pcm, src_rate, SAMPLE_RATE)
        if spec.noise is not None:
            if len(pcm) == 0:
                raise DegradeError("clip is empty")
            if is_silent(pcm, SAMPLE_RATE):
                raise DegradeError("clip has no audio above -60 dBFS; SNR is undefined")
        track = asyncio.run(noise_track(spec, seed, TTSCache(cache_dir), make_engine()))
        rng = part_rng(seed, "turn-0")
        noise = None
        if spec.noise is not None and track is not None:
            piece = noise_slice(track, len(pcm), rng)
            gain = noise_scale(
                [peak_normalise(pcm.astype(np.float64))], piece, SAMPLE_RATE, spec.noise.snr_db
            )
            noise = gain * piece
        result = degrade_clip(pcm, SAMPLE_RATE, spec, out_rate=rate, noise=noise, rng=rng)
        target = out if out is not None else clip.with_name(f"{clip.stem}.{preset}.wav")
        write_wav(target, result.pcm, rate)
    except (ValueError, FfmpegMissing, wave.Error, DegradeError) as exc:
        raise _fail(str(exc)) from exc
    except (OSError, EdgeTTSException, aiohttp.ClientError, RuntimeError) as exc:
        raise _fail(f"degrade failed: {_describe(exc)}") from exc
    stats = result.stats
    snr = "n/a" if stats is None or stats.snr_db is None else f"{stats.snr_db:.1f} dB"
    lost, frames = (0, len(result.lost)) if stats is None else (stats.lost_frames, stats.frames)
    clipped = 0 if stats is None else stats.clipped_samples
    typer.echo(f"wrote {target}")
    typer.echo(f"snr {snr}, lost frames {lost}/{frames}, clipped samples {clipped}")


@app.command()
def report(
    run_dir: Annotated[Path, typer.Argument(help="Run directory with report.json.")],
) -> None:
    """Re-render report.html from report.json."""
    try:
        loaded = load_report(run_dir / "report.json")
    # ValueError covers a file that is not UTF-8 (UnicodeDecodeError) and pydantic's
    # ValidationError for JSON that is not a valid report.
    except (OSError, ValueError) as exc:
        raise _fail(f"cannot read report.json in {run_dir}: {exc}") from exc
    typer.echo(str(write_report_html(loaded, run_dir)))


@app.command()
def budget(
    paths: Annotated[list[Path], typer.Argument(help="Scenario files or directories.")],
    preset: Annotated[
        list[str] | None,
        typer.Option(help="Degradation preset; repeat for several, or `all`. Default: clean."),
    ] = None,
) -> None:
    """Estimate Groq free-tier usage for scenarios."""
    try:
        presets = expand_presets(preset or ["clean"])
        scenarios = [load_scenario(file) for file in _scenario_files(paths)]
    except (ScenarioError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    est = estimate(scenarios, presets=len(presets))
    typer.echo(f"scenarios: {est.scenarios}")
    typer.echo(f"presets: {len(presets)}")
    typer.echo(f"STT calls: {est.stt_calls} (limits {GROQ_STT_LIMITS})")
    typer.echo(f"LLM calls: {est.llm_calls} (assumed limits {GROQ_LLM_ASSUMED}; check the console)")
    typer.echo(f"audio seconds: {est.audio_seconds:.0f}")
    typer.echo("RPM is not estimated")
    typer.echo("noise presets can add STT requests when the agent's VAD reacts to noise")
    if est.within_limits:
        typer.echo("within limits")
        return
    for note in est.notes:
        typer.echo(note)
    raise typer.Exit(2)

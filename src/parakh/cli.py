"""Command-line entry point for Parakh."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from parakh import __version__
from parakh.scenario import load_scenario
from parakh.tts.cache import DEFAULT_CACHE_ROOT, TTSCache, build_scenario_audio
from parakh.tts.engine import EdgeTTSEngine, TTSEngine

app = typer.Typer(help="Test voice agents on Indian speech.", no_args_is_help=True)
tts_app = typer.Typer(help="Caller audio commands.", no_args_is_help=True)
app.add_typer(tts_app, name="tts")


@app.callback()
def main() -> None:
    """Parakh command-line interface."""


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

    total, built = asyncio.run(run())
    typer.echo(f"{total} clips ({built} built, {total - built} cached)")

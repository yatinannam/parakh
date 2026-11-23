"""Commands that read finished runs: compare, report, judge. Registered on the main app."""

import asyncio
import os
from pathlib import Path
from typing import Annotated

import typer

from parakh.cli_util import fail, judge_detail
from parakh.judge.providers import load_config
from parakh.report.compare import build_comparison, write_comparison
from parakh.report.html import write_report_html
from parakh.report.model import JudgeReport, Report, load_report, write_report_json


def _default_compare_dir(run_dirs: list[Path]) -> Path:
    """Common parent of the run directories; one level up when it is itself a run."""
    resolved = [d.resolve() for d in run_dirs]
    try:
        common = Path(os.path.commonpath(resolved))
    except ValueError as exc:
        raise fail("run directories are on different drives; pass --out") from exc
    return common.parent if common in resolved else common


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
            raise fail(f"cannot read report.json in {run_dir}: {exc}") from exc
    target = out if out is not None else _default_compare_dir(run_dirs)
    typer.echo(str(write_comparison(build_comparison(runs, target), target)))


def report(
    run_dir: Annotated[Path, typer.Argument(help="Run directory with report.json.")],
) -> None:
    """Re-render report.html from report.json."""
    try:
        loaded = load_report(run_dir / "report.json")
    # ValueError covers a file that is not UTF-8 (UnicodeDecodeError) and pydantic's
    # ValidationError for JSON that is not a valid report.
    except (OSError, ValueError) as exc:
        raise fail(f"cannot read report.json in {run_dir}: {exc}") from exc
    typer.echo(str(write_report_html(loaded, run_dir)))


def judge(
    run_dirs: Annotated[list[Path], typer.Argument(help="Run directories with report.json.")],
    force: Annotated[bool, typer.Option(help="Ask again even when a verdict is cached.")] = False,
) -> None:
    """Judge finished runs, then rewrite report.json and report.html.

    Exits 2 when any run ends judge_error or rate_limited, or a report.json is unreadable.
    """
    from parakh import cli  # late: cli registers this module, and tests patch cli.make_judge

    runner = cli.make_judge()
    failed = False

    async def run_all() -> None:
        nonlocal failed
        for run_dir in run_dirs:
            try:
                loaded = load_report(run_dir / "report.json")
            except (OSError, ValueError) as exc:
                typer.echo(f"cannot read report.json in {run_dir}: {exc}", err=True)
                failed = True
                continue
            try:
                verdict = await runner.judge(loaded, force=force)
            except Exception as exc:
                verdict = JudgeReport(
                    status="judge_error",
                    prompt_version=load_config().prompt_version,
                    reason=f"internal: {type(exc).__name__}",
                )
            updated = loaded.model_copy(update={"judge": verdict})
            try:
                write_report_json(updated, run_dir / "report.json")
                write_report_html(updated, run_dir)
            except OSError as exc:
                typer.echo(f"cannot write the report in {run_dir}: {type(exc).__name__}", err=True)
                failed = True
                continue
            typer.echo(f"{run_dir}: {judge_detail(verdict)}")
            if verdict.status in ("judge_error", "rate_limited"):
                failed = True

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        typer.echo("interrupted", err=True)
        raise typer.Exit(2) from None
    if failed:
        raise typer.Exit(2)


def register(app: typer.Typer) -> None:
    app.command()(compare)
    app.command()(report)
    app.command()(judge)

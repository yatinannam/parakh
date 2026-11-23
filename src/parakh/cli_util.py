"""Small helpers shared by the command modules."""

import typer

from parakh.report.model import JudgeReport


def fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(2)


def describe(exc: Exception) -> str:
    """Exception type and message on one line (ffmpeg errors span several)."""
    return f"{type(exc).__name__}: {' '.join(str(exc).split())}"


def judge_detail(judge: JudgeReport) -> str:
    """One-line verdict: `ok, mean 4.2 (groq model)`, `skipped (reason)`, `judge_error (reason)`.

    The reason was scrubbed of key values when the judge produced it.
    """
    if judge.status == "ok" and judge.mean is not None:
        return f"ok, mean {judge.mean:.1f} ({judge.provider} {judge.model})"
    return f"{judge.status} ({judge.reason})" if judge.reason else judge.status

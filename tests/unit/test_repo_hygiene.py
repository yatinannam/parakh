"""Repository rules that protect secrets: ignore patterns and CI hardening."""

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT, capture_output=True
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.parametrize("path", [".env", ".env.local", ".env.production", "sub/.env"])
def test_env_files_are_ignored(path):
    assert _ignored(path)


def test_env_example_is_not_ignored():
    assert not _ignored(".env.example")


def _ci_jobs():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    return workflow["jobs"]


def test_ci_checkouts_do_not_persist_credentials():
    checkouts = [
        step
        for job in _ci_jobs().values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    assert all(step.get("with", {}).get("persist-credentials") is False for step in checkouts)


def test_ci_jobs_have_timeouts():
    jobs = _ci_jobs()
    assert {name: isinstance(job.get("timeout-minutes"), int) for name, job in jobs.items()} == {
        name: True for name in jobs
    }

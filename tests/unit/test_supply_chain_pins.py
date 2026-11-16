"""EC-75: third-party code that runs in CI or on the dev laptop is pinned to a commit SHA."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SHA = re.compile(r"^[0-9a-f]{40}$")


def test_pre_commit_revs_are_commit_shas():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    remote = [r for r in config["repos"] if r["repo"] not in ("local", "meta")]
    assert remote
    unpinned = [f"{r['repo']}@{r['rev']}" for r in remote if not SHA.match(str(r["rev"]))]
    assert unpinned == []


def test_workflow_actions_are_commit_shas():
    uses = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in wf.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", line)
            if m and not m.group(1).startswith("./"):
                uses.append((wf.name, m.group(1)))
    assert uses
    unpinned = [f"{name}: {ref}" for name, ref in uses if not SHA.match(ref.rpartition("@")[2])]
    assert unpinned == []

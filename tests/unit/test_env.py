from pathlib import Path

import pytest

from parakh import env
from parakh.env import load_env as real_load_env  # bound before the conftest patch
from parakh.judge.providers import load_config


def test_judge_keys_returns_only_set_nonempty_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "not-a-real-key")
    monkeypatch.setenv("GEMINI_API_KEY", "  ")
    assert env.judge_keys(load_config()) == {"GROQ_API_KEY": "not-a-real-key"}


def test_judge_keys_empty_without_env() -> None:
    assert env.judge_keys(load_config()) == {}


def test_load_env_reads_cwd_dotenv_without_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    folder = tmp_path / "dir with space"
    folder.mkdir()
    (folder / ".env").write_text("GEMINI_API_KEY=from-file\nGROQ_API_KEY=from-file\n")
    monkeypatch.chdir(folder)
    monkeypatch.setenv("GROQ_API_KEY", "already-set")
    try:
        real_load_env()
        assert os.environ["GEMINI_API_KEY"] == "from-file"
        assert os.environ["GROQ_API_KEY"] == "already-set"
    finally:
        os.environ.pop("GEMINI_API_KEY", None)

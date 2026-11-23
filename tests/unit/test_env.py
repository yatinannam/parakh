import os
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


def _utf16_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "dir with space"
    folder.mkdir()
    path = folder / ".env"
    path.write_text("GEMINI_API_KEY=utf16-secret-value", encoding="utf-16")
    monkeypatch.chdir(folder)
    return path


def test_unreadable_env_warns_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _utf16_env(tmp_path, monkeypatch)
    real_load_env()
    err = capsys.readouterr().err
    assert str(path) in err and "not UTF-8" in err and "judge keys not loaded" in err
    assert "utf16-secret-value" not in err
    assert "GEMINI_API_KEY" not in os.environ


def test_version_runs_with_unreadable_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from parakh.cli import app

    _utf16_env(tmp_path, monkeypatch)
    monkeypatch.setattr(env, "load_env", real_load_env)
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert "parakh " in result.output
    assert "GEMINI_API_KEY" not in os.environ

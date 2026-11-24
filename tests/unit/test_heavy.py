import json
import os
import subprocess
import sys
from pathlib import Path

import psutil
import pytest
from typer.testing import CliRunner

from parakh import heavy
from parakh.cli import app


def _lock(tmp_path: Path) -> Path:
    return tmp_path / "dir with space" / "locks" / "heavy-model.lock"


def _dead_pid() -> int:
    pid = 4_000_000
    while psutil.pid_exists(pid):
        pid += 1
    return pid


def _write(path: Path, pid: int, owner: str = "other job") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": pid, "owner": owner, "started": "2026-11-24T10:00:00"}),
        encoding="utf-8",
    )


def test_lock_acquire_and_release(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    with heavy.heavy_model_lock("parler bench", path):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        assert data["owner"] == "parler bench"
        assert data["started"]
    assert not path.exists()


def test_live_holder_blocks(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    _write(path, os.getpid(), owner="whisper agent")
    with pytest.raises(heavy.HeavyModelBusy) as err, heavy.heavy_model_lock("parler bench", path):
        pass
    message = str(err.value)
    assert "whisper agent" in message
    assert f"pid {os.getpid()}" in message
    assert "2026-11-24T10:00:00" in message
    assert path.exists()


def test_stale_lock_taken_over(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    _write(path, _dead_pid())
    with heavy.heavy_model_lock("new owner", path):
        assert json.loads(path.read_text(encoding="utf-8"))["owner"] == "new owner"
    assert not path.exists()


def test_release_keeps_foreign_lock(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    with heavy.heavy_model_lock("first", path):
        _write(path, _dead_pid() + 1, owner="someone else")
    assert json.loads(path.read_text(encoding="utf-8"))["owner"] == "someone else"


def test_unreadable_lock_replaced(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe not json")
    with heavy.heavy_model_lock("fresh", path):
        assert json.loads(path.read_text(encoding="utf-8"))["owner"] == "fresh"


def test_run_locked_returns_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = heavy.run_locked("job", [sys.executable, "-c", "raise SystemExit(7)"])
    assert code == 7
    assert not (tmp_path / heavy.LOCK_PATH).exists()


def test_run_locked_holds_lock_while_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    script = (
        "import json,sys;"
        "d=json.load(open('.cache/locks/heavy-model.lock',encoding='utf-8'));"
        "sys.exit(0 if d['owner']=='job' else 1)"
    )
    assert heavy.run_locked("job", [sys.executable, "-c", script]) == 0


def test_run_locked_busy_does_not_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / heavy.LOCK_PATH, os.getpid())
    marker = tmp_path / "ran.txt"
    argv = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]
    with pytest.raises(heavy.HeavyModelBusy):
        heavy.run_locked("job", argv)
    assert not marker.exists()


def test_heavy_run_busy_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / heavy.LOCK_PATH, os.getpid(), owner="whisper agent")
    result = CliRunner().invoke(app, ["heavy", "run", "bench", "--", sys.executable, "-V"])
    assert result.exit_code == 2
    assert "whisper agent" in result.output


def test_heavy_run_passes_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    argv = ["heavy", "run", "bench", "--", sys.executable, "-c", "raise SystemExit(3)"]
    assert CliRunner().invoke(app, argv).exit_code == 3


def test_subprocess_import_smoke() -> None:
    out = subprocess.run(
        [sys.executable, "-c", "import parakh.heavy"], capture_output=True, check=False
    )
    assert out.returncode == 0

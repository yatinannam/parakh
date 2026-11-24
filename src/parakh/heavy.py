"""One lock for the models too heavy to load together (EC-04).

Indic Parler-TTS and faster-whisper each take several GB on a 16 GB laptop. Every process
that loads either holds this lock, so a second one fails fast and names the first.
"""

import json
import os
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psutil

LOCK_PATH = Path(".cache/locks/heavy-model.lock")


class HeavyModelBusy(RuntimeError):
    """Another live process holds the heavy-model lock."""


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pid"), int):
        return None
    return data


def _create(path: Path, owner: str) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    info = {"pid": os.getpid(), "owner": owner, "started": datetime.now().isoformat()}
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(info, handle)


@contextmanager
def heavy_model_lock(owner: str, path: Path = LOCK_PATH) -> Iterator[None]:
    """Hold the lock for the block; raise HeavyModelBusy if a live process has it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Two tries: the second follows removing a stale or unreadable lock.
    for attempt in range(2):
        try:
            _create(path, owner)
            break
        except FileExistsError:
            held = _read(path)
            if held is not None and psutil.pid_exists(held["pid"]):
                raise HeavyModelBusy(
                    f"{held.get('owner', 'unknown')} (pid {held['pid']}) holds the "
                    f"heavy-model lock since {held.get('started', 'unknown')}"
                ) from None
            if attempt == 1:
                raise
            path.unlink(missing_ok=True)
    try:
        yield
    finally:
        held = _read(path)
        if held is not None and held["pid"] == os.getpid():
            path.unlink(missing_ok=True)


def run_locked(owner: str, argv: Sequence[str]) -> int:
    """Run a command under the lock and return its exit code."""
    with heavy_model_lock(owner):
        return subprocess.run(list(argv), check=False).returncode

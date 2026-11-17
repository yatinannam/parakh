import asyncio
import warnings
from typing import Any

import pytest

# pipecat's websockets import warns at import time; ignore exactly that message.
_WS = r"websockets\.(WebSocketServerProtocol|legacy) is deprecated"
pytestmark = pytest.mark.filterwarnings(f"ignore:{_WS}:DeprecationWarning")
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=_WS, category=DeprecationWarning)
    from agents.clinic_agent import __main__ as clinic_main


builds = 0


def clinic_main_builds() -> int:
    return builds


class _SwallowingRunner:
    """Stands in for WorkerRunner: run() swallows a cancellation, as the real one does."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def add_workers(self, *workers: Any) -> None:
        pass

    async def run(self) -> None:
        if clinic_main_builds() > 1:
            raise AssertionError("_serve built a second pipeline after the cancel")
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return


async def test_serve_stops_on_first_cancel(monkeypatch: pytest.MonkeyPatch):
    global builds
    builds = 0

    def fake_build_task(*args: Any, **kwargs: Any) -> tuple[object, object]:
        global builds
        builds += 1
        return object(), object()

    monkeypatch.setattr(clinic_main, "build_task", fake_build_task)
    monkeypatch.setattr(clinic_main, "WorkerRunner", _SwallowingRunner)

    serving = asyncio.ensure_future(clinic_main._serve(None, "key", "127.0.0.1", 0))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    serving.cancel()
    await asyncio.wait_for(asyncio.shield(serving), timeout=2)
    assert builds == 1

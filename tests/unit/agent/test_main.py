import asyncio
import warnings
from typing import Any

import pytest

from parakh.heavy import LOCK_PATH

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


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> dict[str, Any]:
    """Run main() with the network, the lock path and the server stubbed out."""
    seen: dict[str, Any] = {"served": [], "models": []}
    monkeypatch.setattr("sys.argv", ["clinic_agent", *argv])
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(clinic_main, "dotenv_values", lambda *_a, **_k: {})

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {"data": [{"id": "openai/gpt-oss-20b"}]}  # no Groq STT model listed

    monkeypatch.setattr(clinic_main.httpx, "get", lambda *_a, **_k: _Response())

    async def fake_serve(
        config: Any, key: str, host: str, port: int, stt_mode: str = "groq"
    ) -> None:
        seen["served"].append(stt_mode)
        seen["lock_held"] = LOCK_PATH.exists()

    monkeypatch.setattr(clinic_main, "_serve", fake_serve)
    return seen


def test_local_stt_skips_groq_stt_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    seen = _run_main(monkeypatch, ["--stt", "local"])
    clinic_main.main()
    assert seen["served"] == ["local"]


def test_groq_stt_still_checked(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    seen = _run_main(monkeypatch, [])
    with pytest.raises(SystemExit) as err:
        clinic_main.main()
    assert err.value.code == 2
    assert seen["served"] == []


def test_local_stt_takes_heavy_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    seen = _run_main(monkeypatch, ["--stt", "local"])
    clinic_main.main()
    assert seen["lock_held"] is True
    assert not (tmp_path / LOCK_PATH).exists()


def test_local_stt_busy_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    import json
    import os

    monkeypatch.chdir(tmp_path)
    seen = _run_main(monkeypatch, ["--stt", "local"])
    lock = tmp_path / LOCK_PATH
    lock.parent.mkdir(parents=True)
    info = {"pid": os.getpid(), "owner": "parler bench", "started": "t0"}
    lock.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(SystemExit) as err:
        clinic_main.main()
    assert err.value.code == 2
    assert "parler bench" in capsys.readouterr().err
    assert seen["served"] == []

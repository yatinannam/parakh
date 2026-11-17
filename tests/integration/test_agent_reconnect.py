"""Back-to-back calls to one clinic agent pipeline over its real Pipecat transport.

Nothing reaches Groq or edge-tts: LLM inference is stubbed, and no caller audio is
sent, so STT and TTS never run. Each call is a WebSocket client that waits for the
agent_info message the agent sends to every new caller.
"""

import asyncio
import socket
import time
import warnings
from typing import Any

import pytest
from pipecat.frames.protobufs import frames_pb2
from pipecat.services.openai.base_llm import BaseOpenAILLMService
from pipecat.workers.runner import WorkerRunner
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from agents.clinic_agent.config import load_config

# Pipecat's websocket transport touches a websockets API that is deprecated upstream.
_WS = r"websockets\.(WebSocketServerProtocol|legacy) is deprecated"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings(f"ignore:{_WS}:DeprecationWarning"),
]
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=_WS, category=DeprecationWarning)
    from agents.clinic_agent import bot

_Frame: Any = frames_pb2.Frame  # type: ignore[attr-defined]


async def _no_inference(self: Any, context: Any) -> None:
    """Stub for the Groq request: the greeting is never generated."""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_listening(port: int, timeout_s: float = 20.0) -> None:
    deadline = time.perf_counter() + timeout_s
    while True:
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            assert time.perf_counter() < deadline, "the agent never started listening"
            await asyncio.sleep(0.05)
            continue
        writer.close()
        await writer.wait_closed()
        return


async def _call(url: str, wait_s: float = 5.0) -> str:
    """One call: connect, wait for agent_info, hang up. Returns what happened."""
    try:
        ws = await connect(url, max_size=None, open_timeout=2)
    except (OSError, TimeoutError) as exc:
        return f"refused: {type(exc).__name__}"
    try:
        async with asyncio.timeout(wait_s):
            while True:
                frame = _Frame.FromString(await ws.recv())
                if frame.WhichOneof("frame") == "message" and "agent_info" in frame.message.data:
                    return "served"
    except ConnectionClosed:
        return "closed before agent_info"
    except TimeoutError:
        return "no agent_info"
    finally:
        await ws.close()


async def test_next_call_right_after_a_hang_up_is_served(monkeypatch: pytest.MonkeyPatch) -> None:
    # Finding 3 of the M1 final review: the agent ended its pipeline on each hang-up
    # and built a new one, so a caller that connected at once was accepted by the
    # ending server and cut off (agent_hung_up_early) or refused (agent_unreachable).
    monkeypatch.setattr(BaseOpenAILLMService, "_process_context", _no_inference)
    port = _free_port()
    task, _transport = bot.build_task(load_config(), "test-key", port=port)
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(task)
    running = asyncio.create_task(runner.run())
    try:
        await _wait_listening(port)
        outcomes = [await _call(f"ws://127.0.0.1:{port}") for _ in range(4)]
    finally:
        await task.cancel()
        await asyncio.wait_for(running, 20)
    assert outcomes == ["served"] * 4

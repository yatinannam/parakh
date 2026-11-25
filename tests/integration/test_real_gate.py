"""The real-data gate against a live driver: redirects, remote peers and a late agent_info."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from parakh.caller.driver import run_call
from parakh.caller.recorder import read_events
from tests.integration.fake_agent import FakeBehaviour, fake_agent
from tests.integration.test_driver import _line, _scenario, _write_clips

pytestmark = pytest.mark.integration

LOCAL = {"stt_model": "local:faster-whisper-small"}


@asynccontextmanager
async def redirecting_server(location: str) -> AsyncIterator[tuple[str, list[bytes]]]:
    """A server on 127.0.0.1 that answers every request with a 301 to location."""
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        head = (
            f"HTTP/1.1 301 Moved Permanently\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n"
        )
        writer.write(head.encode())
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}", requests
    finally:
        server.close()
        await server.wait_closed()


async def _real_call(base: Path, url: str, turns: int = 2):
    clips = _write_clips(base / "clips", turns)
    scenario = _scenario(turns, True, 20.0)
    line = await _line(base, clips, scenario)
    return await run_call(url, scenario, line, base / "run", real=True)


async def test_redirect_to_another_agent_is_refused(tmp_path: Path) -> None:
    base = tmp_path / "dir with space"
    behaviour = FakeBehaviour(agent_info=LOCAL)  # a "remote" agent claiming local STT
    async with fake_agent(behaviour) as target, redirecting_server(target) as (url, requests):
        result = await _real_call(base, url)
    assert len(requests) == 1  # the redirect was answered once and never followed
    assert result.status == "real_data_refused"
    assert any("real data refused: the agent redirected" in w for w in result.warnings)
    assert behaviour.received == []  # nothing, not even silence, reached the target
    assert read_events(result.run_dir)[-1]["status"] == "real_data_refused"


async def test_remote_url_is_refused_inside_the_driver(tmp_path: Path) -> None:
    result = await _real_call(tmp_path / "dir with space", "ws://10.0.0.5:8765")
    assert result.status == "real_data_refused"
    assert result.warnings == ["real data refused: agent ws://10.0.0.5:8765 is not on this machine"]


async def test_first_turn_waits_for_a_late_agent_info(tmp_path: Path) -> None:
    behaviour = FakeBehaviour(agent_info=LOCAL, agent_info_delay_ms=1000, greet_ms=300)
    base = tmp_path / "dir with space"
    clips = _write_clips(base / "clips", 2)
    scenario = _scenario(2, True, 20.0)
    line = await _line(base, clips, scenario)
    async with fake_agent(behaviour) as url:
        result = await run_call(url, scenario, line, base / "run", real=True)
    assert result.status == "completed"
    cut = behaviour.frames_at_info
    assert cut is not None and cut > 20  # the caller was streaming (bed) before the info
    assert max(behaviour.received_dbfs[:cut]) <= -45.0  # no recorded audio before it
    loud_after = sum(1 for level in behaviour.received_dbfs[cut:] if level > -45.0)
    assert loud_after >= 2 * 15  # both 400 ms turns then played in full, not as silence
    assert result.turns_started == 2

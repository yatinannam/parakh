"""WebSocket connection to an agent that speaks Pipecat's protobuf protocol."""

from __future__ import annotations

import contextlib
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from parakh.transport.codec import AgentEvent, ProtocolError, decode_frame, encode_audio


class AgentUnreachable(ConnectionError):
    """The agent's WebSocket could not be opened."""


def check_agent_url(url: str) -> None:
    """Raise ValueError unless url is a ws:// or wss:// URL."""
    if urlsplit(url).scheme not in ("ws", "wss"):
        raise ValueError(f"agent URL must start with ws:// or wss://, got {url!r}")


class AgentConnection:
    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws

    @classmethod
    async def connect(cls, url: str, open_timeout_s: float = 5.0) -> AgentConnection:
        """Open the WebSocket. Only ws:// and wss:// URLs are accepted."""
        check_agent_url(url)
        try:
            ws = await connect(url, max_size=None, open_timeout=open_timeout_s)
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise AgentUnreachable(f"cannot connect to the agent at {url}: {exc}") from exc
        return cls(ws)

    async def send_audio(self, pcm: bytes, sample_rate: int) -> None:
        """Send one caller audio frame. Once the socket is closed this does nothing;
        recv() reports the close."""
        with contextlib.suppress(ConnectionClosed):
            await self._ws.send(encode_audio(pcm, sample_rate))

    async def recv(self) -> AgentEvent | None:
        """Next agent event, or None once the socket has closed (cleanly or not).

        Raises ProtocolError for anything that is not a binary Pipecat frame.
        """
        try:
            data = await self._ws.recv()
        except ConnectionClosed:
            return None
        if isinstance(data, str):
            raise ProtocolError(
                "agent sent a text WebSocket message; Pipecat protobuf frames are binary"
            )
        return decode_frame(data)

    async def close(self) -> None:
        """Close the socket; errors from an already broken connection are ignored."""
        with contextlib.suppress(OSError, WebSocketException):
            await self._ws.close()

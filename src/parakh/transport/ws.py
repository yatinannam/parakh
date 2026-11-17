"""WebSocket connection to an agent that speaks Pipecat's protobuf protocol."""

from __future__ import annotations

import contextlib
import re
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from parakh.transport.codec import AgentEvent, ProtocolError, decode_frame, encode_audio


class AgentUnreachable(ConnectionError):
    """The agent's WebSocket could not be opened."""


def redact_url(url: str) -> str:
    """Keep scheme, host, port and path; drop userinfo, query and fragment."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable url>"
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


_URL_IN_TEXT = re.compile(r"\b(?:wss?|https?)://[^\s'\"<>]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}"


def redact_urls(text: str) -> str:
    """Apply redact_url() to every ws, wss, http or https URL inside free text."""

    def redact(match: re.Match[str]) -> str:
        url = match.group(0)
        stripped = url.rstrip(_TRAILING_PUNCTUATION)
        return redact_url(stripped) + url[len(stripped) :]

    return _URL_IN_TEXT.sub(redact, text)


def check_agent_url(url: str) -> None:
    """Raise ValueError unless url is a ws:// or wss:// URL."""
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        scheme = ""
    if scheme not in ("ws", "wss"):
        raise ValueError(f"agent URL must start with ws:// or wss://, got {redact_url(url)!r}")


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
            safe = redact_url(url)
            reason = str(exc).replace(url, safe)
            raise AgentUnreachable(f"cannot connect to the agent at {safe}: {reason}") from exc
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

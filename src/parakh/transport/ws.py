"""WebSocket connection to an agent that speaks Pipecat's protobuf protocol."""

from __future__ import annotations

import contextlib
import ipaddress
import re
from typing import ClassVar, Literal
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from parakh.transport.codec import AgentEvent, ProtocolError, decode_frame, encode_audio


class AgentUnreachable(ConnectionError):
    """The agent's WebSocket could not be opened."""

    status: ClassVar[Literal["agent_unreachable"]] = "agent_unreachable"


class AgentNotLocal(ConnectionError):
    """A local-only connection reached, or was sent towards, another machine."""

    status: ClassVar[Literal["real_data_refused"]] = "real_data_refused"


class _NoRedirect(connect):
    """connect() that never follows a redirect: a 3xx answer raises InvalidStatus."""

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


def _peer_is_loopback(ws: ClientConnection) -> str | None:
    """None when the connected peer is on this machine, else the peer's host (or a reason)."""
    peer = ws.transport.get_extra_info("peername")
    host = str(peer[0]) if peer else "unknown"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return None if address.is_loopback else host


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


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def is_loopback(url: str) -> bool:
    """True when the URL's host is this machine: 127.0.0.1, localhost or ::1."""
    try:
        return urlsplit(url).hostname in _LOOPBACK_HOSTS
    except ValueError:
        return False


def check_local_agent_url(url: str) -> None:
    """Raise ValueError unless the agent is on this machine (real recordings stay here)."""
    if not is_loopback(url):
        raise ValueError(
            "real recordings need an agent on this machine (127.0.0.1, localhost or ::1), "
            f"got {redact_url(url)}"
        )


class AgentConnection:
    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws

    @classmethod
    async def connect(
        cls, url: str, open_timeout_s: float = 5.0, *, local_only: bool = False
    ) -> AgentConnection:
        """Open the WebSocket. Only ws:// and wss:// URLs are accepted.

        local_only (real recordings): the URL host must be loopback, a redirect is never
        followed, and the connected peer's address must be loopback; otherwise AgentNotLocal.
        """
        check_agent_url(url)
        if local_only and not is_loopback(url):
            raise AgentNotLocal(
                f"real data refused: agent {redact_url(url)} is not on this machine"
            )
        try:
            # A loopback agent is never reached through a system proxy.
            proxy = None if is_loopback(url) else True
            opener = _NoRedirect if local_only else connect
            ws = await opener(url, max_size=None, open_timeout=open_timeout_s, proxy=proxy)
        except InvalidStatus as exc:
            if local_only and 300 <= exc.response.status_code < 400:
                raise AgentNotLocal(
                    "real data refused: the agent redirected the connection"
                ) from exc
            raise AgentUnreachable(
                f"cannot connect to the agent at {redact_url(url)}: {exc}"
            ) from exc
        except (OSError, TimeoutError, WebSocketException) as exc:
            safe = redact_url(url)
            reason = str(exc).replace(url, safe)
            raise AgentUnreachable(f"cannot connect to the agent at {safe}: {reason}") from exc
        if local_only and (remote := _peer_is_loopback(ws)) is not None:
            ws.transport.abort()
            raise AgentNotLocal(f"real data refused: agent peer {remote} is not on this machine")
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

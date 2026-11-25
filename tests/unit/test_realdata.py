"""The real-data gate: recorded audio goes only to an agent that proved its STT is local."""

import asyncio
from typing import Any, cast

import numpy as np
import pytest

from parakh.audio import PCM
from parakh.caller.realdata import REAL_INFO_TIMEOUT_S, RealDataGate
from parakh.transport.ws import (
    AgentConnection,
    AgentNotLocal,
    _peer_is_loopback,
    check_local_agent_url,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000

    def __call__(self) -> int:
        return self.now


def loud() -> PCM:
    return np.full(320, 9000, dtype=np.int16)


def test_gate_opens_on_local_stt() -> None:
    clock = Clock()
    gate = RealDataGate(clock.now, clock=clock)
    assert gate.poll() == "pending"
    guarded = gate.guard(loud())
    assert len(guarded) == 320 and not guarded.any()  # silence of the same size while pending
    gate.on_agent_info({"stt_model": "local:faster-whisper-small"})
    assert gate.poll() == "open"
    assert gate.guard(loud()).any()
    clock.now += int((REAL_INFO_TIMEOUT_S + 1) * 1e9)
    assert gate.poll() == "open"  # the timeout only matters while pending


def test_real_run_refuses_remote_stt() -> None:
    gate = RealDataGate(0, clock=Clock())
    gate.on_agent_info({"stt_model": "whisper-large-v3-turbo"})
    assert gate.poll() == "refused"
    assert gate.warning == (
        "real data refused: agent stt_model 'whisper-large-v3-turbo' is not local"
    )
    assert not gate.guard(loud()).any()
    gate.on_agent_info({"stt_model": "local:x"})  # a refusal is final
    assert gate.poll() == "refused"


@pytest.mark.parametrize(
    "info", [{}, {"stt_model": None}, {"stt_model": 3}, {"stt_model": "Local:x"}]
)
def test_gate_refuses_missing_or_odd_stt(info: dict[str, Any]) -> None:
    gate = RealDataGate(0, clock=Clock())
    gate.on_agent_info(info)
    assert gate.poll() == "refused"
    assert not gate.guard(loud()).any()


def test_real_run_refuses_without_agent_info() -> None:
    clock = Clock()
    gate = RealDataGate(clock.now, clock=clock)
    clock.now += int(4.9e9)
    assert gate.poll() == "pending"
    clock.now += int(0.2e9)
    assert gate.poll() == "refused"
    assert gate.warning == "real data refused: no agent info within 5.0 s"
    assert not gate.guard(loud()).any()
    gate.on_agent_info({"stt_model": "local:x"})
    assert gate.poll() == "refused"


def test_open_gate_refuses_a_later_remote_report() -> None:
    gate = RealDataGate(0, clock=Clock())
    gate.on_agent_info({"stt_model": "local:x"})
    gate.on_agent_info({"stt_model": "whisper-large-v3-turbo"})
    assert gate.poll() == "refused"


@pytest.mark.parametrize(
    "url", ["ws://127.0.0.1:8765", "ws://localhost:1/x", "ws://[::1]:8765", "wss://LOCALHOST"]
)
def test_loopback_urls_pass(url: str) -> None:
    check_local_agent_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "ws://10.0.0.5:8765",
        "ws://example.com",
        "ws://127.0.0.1.evil.com:8765",
        "ws://127.0.0.1@evil.com:8765",
        "ws://127.0.0.2:1",
        "ws://0.0.0.0:1",
    ],
)
def test_other_urls_refused(url: str) -> None:
    with pytest.raises(ValueError, match=r"real recordings need an agent on this machine"):
        check_local_agent_url(url)


def test_refusal_message_redacts_credentials() -> None:
    with pytest.raises(ValueError) as info:
        check_local_agent_url("ws://user:secret@10.0.0.5:8765/p?token=abc")
    assert "secret" not in str(info.value)
    assert "token" not in str(info.value)
    assert str(info.value).endswith("got ws://10.0.0.5:8765/p")


class _Transport:
    def __init__(self, peer: object) -> None:
        self._peer = peer

    def get_extra_info(self, _name: str) -> object:
        return self._peer


class _Ws:
    def __init__(self, peer: object) -> None:
        self.transport = _Transport(peer)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_loopback_peers_pass(host: str) -> None:
    assert _peer_is_loopback(cast(Any, _Ws((host, 1)))) is None


@pytest.mark.parametrize(
    "peer", [("10.0.0.5", 1), ("fe80::1%eth0", 1), ("::ffff:10.0.0.5", 1), None]
)
def test_other_peers_are_named(peer: object) -> None:
    assert _peer_is_loopback(cast(Any, _Ws(peer))) is not None


def test_local_only_connect_refuses_a_remote_host_without_connecting() -> None:
    with pytest.raises(AgentNotLocal, match="real data refused: agent ws://10.0.0.5:1 is not on"):
        asyncio.run(AgentConnection.connect("ws://10.0.0.5:1", local_only=True))

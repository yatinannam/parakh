"""Agent event mapping: audio normalisation and the event kinds the driver records."""

import numpy as np
import pytest

from parakh.audio import SUPPORTED_RATES
from parakh.caller import events
from parakh.transport.codec import (
    AgentAudio,
    AgentEvent,
    AgentInterruption,
    AgentText,
    AgentTranscription,
    ProtocolError,
    RtviMessage,
    RtviRepeats,
)


def _pcm(*samples: int) -> bytes:
    return np.array(samples, dtype="<i2").tobytes()


def test_supported_rates() -> None:
    assert SUPPORTED_RATES == (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000)


@pytest.mark.parametrize(
    ("audio", "match"),
    [
        (AgentAudio(b"\x00\x00" * 4, 16000, 3), "channel"),
        (AgentAudio(b"\x00\x00\x00", 16000, 1), "odd"),
    ],
)
def test_malformed_agent_audio_is_protocol_error(audio: AgentAudio, match: str) -> None:
    with pytest.raises(ProtocolError, match=match):
        events.agent_pcm(audio)


def test_unset_channel_count_is_mono() -> None:
    assert events.agent_pcm(AgentAudio(b"\x01\x00\x02\x00", 16000, 0)).tolist() == [1, 2]


def test_stereo_is_downmixed() -> None:
    audio = AgentAudio(_pcm(100, 300, -50, -150), 16000, 2)
    assert events.agent_pcm(audio).tolist() == [200, -100]


def test_odd_stereo_samples_is_protocol_error() -> None:
    with pytest.raises(ProtocolError, match="stereo"):
        events.agent_pcm(AgentAudio(_pcm(1, 2, 3), 16000, 2))


@pytest.mark.parametrize("rate", [0, 16001, 96000])
def test_unsupported_agent_rate_is_protocol_error(rate: int) -> None:
    with pytest.raises(ProtocolError, match="sample rate"):
        events.agent_pcm(AgentAudio(_pcm(1, 2), rate, 1))


def _rtvi(kind: str, **data: object) -> RtviMessage:
    return RtviMessage(kind, dict(data), {})


def _map(event: AgentEvent) -> events.Mapped:
    return events.map_event(event, RtviRepeats())


def test_map_event_kinds() -> None:
    assert _map(AgentText("hi")) == events.Mapped("bot_output", {"text": "hi"})
    assert _map(AgentTranscription("kal", "u", "t")) == events.Mapped(
        "caller_transcript", {"text": "kal", "final": True}
    )
    assert _map(AgentInterruption()) == events.Mapped("agent_interruption", {}, interruption=True)
    got = _map(_rtvi("user-input", input_type="transcription", text="haan", final=False))
    assert got == events.Mapped("caller_transcript", {"text": "haan", "final": False})
    info = {"llm_model": "x"}
    got = _map(_rtvi("server-message", agent_info=info))
    assert got == events.Mapped("agent_info", {"info": info}, agent_info=info)
    assert _map(_rtvi("bot-started-speaking")) == events.Mapped("bot_started", {})
    assert _map(_rtvi("bot-stopped-speaking")) == events.Mapped("bot_stopped", {}, bot_stopped=True)
    assert _map(_rtvi("bot-output", text="hello")) == events.Mapped("bot_output", {"text": "hello"})
    assert _map(_rtvi("bot-output", text=5)) == events.Mapped("bot_output", {"text": ""})
    assert _map(_rtvi("metrics", a=1)) == events.Mapped("agent_metrics", {"data": {"a": 1}})
    assert _map(_rtvi("user-started-speaking")) == events.Mapped("user_started", {})
    assert _map(_rtvi("user-stopped-speaking")) == events.Mapped("user_stopped", {})
    assert _map(_rtvi("mystery")) == events.Mapped("rtvi_unknown", {"type": "mystery"})


def test_map_event_error_is_a_warning_with_url_redacted() -> None:
    msg = _rtvi("error", error="no audio from wss://tts.example/v1?Token=SECRET#x", fatal=True)
    got = _map(msg)
    assert got.kind is None
    assert got.fields == {}
    assert got.warning == "agent error (fatal): no audio from wss://tts.example/v1"


def test_map_event_repeats() -> None:
    repeats = RtviRepeats()
    stamp = "2026-11-19T10:00:01"
    first = events.map_event(AgentTranscription("haan", "u", stamp), repeats)
    assert first.kind == "caller_transcript"
    twin = _rtvi("user-input", input_type="transcription", text="haan", final=True, timestamp=stamp)
    assert events.map_event(twin, repeats) == events.Mapped("rtvi_repeat", {"type": "user-input"})
    out = _rtvi("bot-output", text="x", segment_id=1)
    assert events.map_event(out, repeats).kind == "bot_output"
    assert events.map_event(out, repeats).kind == "rtvi_repeat"

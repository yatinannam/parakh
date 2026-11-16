import json

import pytest

from parakh.transport.codec import (
    AgentAudio,
    AgentInterruption,
    AgentText,
    AgentTranscription,
    Frame,
    ProtocolError,
    RtviMessage,
    agent_info,
    caller_transcript,
    decode_frame,
    encode_audio,
)


def _rtvi(payload: dict) -> RtviMessage:
    frame = Frame()
    frame.message.data = json.dumps(payload)
    event = decode_frame(frame.SerializeToString())
    assert isinstance(event, RtviMessage)
    return event


def test_encode_audio_round_trip() -> None:
    pcm = b"\x01\x00" * 320
    frame = Frame.FromString(encode_audio(pcm, 16000))
    assert frame.WhichOneof("frame") == "audio"
    assert frame.audio.sample_rate == 16000
    assert frame.audio.num_channels == 1
    assert frame.audio.audio == pcm


def test_decode_audio() -> None:
    frame = Frame()
    frame.audio.audio = b"\x02\x00" * 10
    frame.audio.sample_rate = 24000
    frame.audio.num_channels = 1
    event = decode_frame(frame.SerializeToString())
    assert event == AgentAudio(pcm=b"\x02\x00" * 10, sample_rate=24000, num_channels=1)


def test_decode_text_transcription_interruption() -> None:
    f = Frame()
    f.text.text = "namaste"
    assert decode_frame(f.SerializeToString()) == AgentText(text="namaste")

    f = Frame()
    f.transcription.text = "kal"
    f.transcription.user_id = "u"
    f.transcription.timestamp = "t"
    assert decode_frame(f.SerializeToString()) == AgentTranscription(
        text="kal", user_id="u", timestamp="t"
    )

    f = Frame()
    f.interruption.SetInParent()
    assert decode_frame(f.SerializeToString()) == AgentInterruption()


def test_decode_garbage_raises() -> None:
    with pytest.raises(ProtocolError, match="not Pipecat protobuf"):
        decode_frame(b"\xff\x00 not protobuf")


def test_decode_empty_frame_raises() -> None:
    with pytest.raises(ProtocolError, match="not Pipecat protobuf"):
        decode_frame(Frame().SerializeToString())


def test_user_input_transcript() -> None:
    msg = _rtvi(
        {
            "label": "rtvi-ai",
            "type": "user-input",
            "data": {"text": "हाँ", "input_type": "transcription", "final": True, "timestamp": "t"},
        }
    )
    assert caller_transcript(msg) == ("हाँ", True)
    chat = _rtvi({"type": "user-input", "data": {"text": "x", "input_type": "chat", "final": True}})
    assert caller_transcript(chat) is None


def test_deprecated_user_transcription() -> None:
    msg = _rtvi(
        {
            "type": "user-transcription",
            "data": {"text": "kal", "user_id": "u", "timestamp": "t", "final": False},
        }
    )
    assert caller_transcript(msg) == ("kal", False)


def test_message_not_json() -> None:
    frame = Frame()
    frame.message.data = "not json"
    event = decode_frame(frame.SerializeToString())
    assert event == RtviMessage(type="", data={}, raw="not json")


def test_agent_info() -> None:
    msg = _rtvi({"type": "server-message", "data": {"agent_info": {"llm_model": "x"}}})
    assert agent_info(msg) == {"llm_model": "x"}
    assert agent_info(_rtvi({"type": "server-message", "data": {}})) is None


def test_malformed_rtvi_fields_are_tolerated() -> None:
    assert caller_transcript(_rtvi({"type": "user-input", "data": "oops"})) is None
    assert (
        caller_transcript(_rtvi({"type": "user-input", "data": {"input_type": "transcription"}}))
        is None
    )
    assert _rtvi({"type": 5, "data": []}).type == ""

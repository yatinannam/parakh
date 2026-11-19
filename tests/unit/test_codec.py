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
    RtviRepeats,
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


def _transcript(msg_type: str, text: str, timestamp: str, final: bool = True) -> RtviMessage:
    data: dict = {"text": text, "final": final, "timestamp": timestamp, "user_id": ""}
    if msg_type == "user-input":
        data["input_type"] = "transcription"
    return _rtvi({"type": msg_type, "data": data})


def test_user_transcription_twin_of_user_input_is_a_repeat() -> None:
    # Pipecat 1.13 and later send each transcription as user-input, then again as
    # the deprecated user-transcription with the same text, final flag and timestamp.
    repeats = RtviRepeats()
    assert not repeats.is_repeat(_transcript("user-input", "हाँ", "06:10:00"))
    assert repeats.is_repeat(_transcript("user-transcription", "हाँ", "06:10:00"))
    # The same words said again later are new speech, not a repeat.
    assert not repeats.is_repeat(_transcript("user-input", "हाँ", "06:10:05"))
    assert repeats.is_repeat(_transcript("user-transcription", "हाँ", "06:10:05"))


def test_transcript_twin_order_does_not_matter() -> None:
    repeats = RtviRepeats()
    assert not repeats.is_repeat(_transcript("user-transcription", "kal", "t1"))
    assert repeats.is_repeat(_transcript("user-input", "kal", "t1"))


def test_transcripts_of_one_message_type_are_never_repeats() -> None:
    # An agent that sends only one of the two types: every transcript counts, even
    # one that matches the last, and an interim one followed by its final one.
    repeats = RtviRepeats()
    assert not repeats.is_repeat(_transcript("user-transcription", "haan", "t1"))
    assert not repeats.is_repeat(_transcript("user-transcription", "haan", "t1"))
    assert not repeats.is_repeat(_transcript("user-input", "kal", "t2", final=False))
    assert not repeats.is_repeat(_transcript("user-input", "kal", "t2"))
    assert not repeats.is_repeat(_transcript("user-transcription", "kal", "t2", final=False))


def _bot_output(
    segment_id: object, status: str, text: str = "Hello, Parakh Clinic."
) -> RtviMessage:
    data = {"text": text, "segment_id": segment_id, "spoken_status": status}
    return _rtvi({"type": "bot-output", "data": data})


def test_bot_output_segment_is_reported_once() -> None:
    # Pipecat reports a spoken segment when it starts ("new") and again once spoken
    # ("completed", with "in-progress" between them for TTS with word timestamps).
    repeats = RtviRepeats()
    assert not repeats.is_repeat(_bot_output(7, "new"))
    assert repeats.is_repeat(_bot_output(7, "in-progress"))
    assert repeats.is_repeat(_bot_output(7, "completed"))
    assert not repeats.is_repeat(_bot_output(8, "new", "How can I help you today?"))


def test_bot_output_without_a_usable_segment_id_is_never_a_repeat() -> None:
    repeats = RtviRepeats()
    plain = _rtvi({"type": "bot-output", "data": {"text": "Bye!"}})
    assert not repeats.is_repeat(plain)
    assert not repeats.is_repeat(plain)
    assert not repeats.is_repeat(_bot_output(True, "new"))
    assert not repeats.is_repeat(_bot_output(True, "completed"))
    assert not repeats.is_repeat(_rtvi({"type": "bot-started-speaking"}))


def test_deeply_nested_json_is_protocol_error() -> None:
    frame = Frame()
    frame.message.data = "[" * 100_000
    with pytest.raises(ProtocolError):
        decode_frame(frame.SerializeToString())


def test_repeated_haan_without_timestamps_is_kept() -> None:
    repeats = RtviRepeats()

    def msg(kind: str) -> RtviMessage:
        data: dict = {"text": "haan", "final": True}
        if kind == "user-input":
            data["input_type"] = "transcription"
        return _rtvi({"type": kind, "data": data})

    got = [
        repeats.is_repeat(msg(k))
        for k in ("user-input", "user-transcription", "user-input", "user-transcription")
    ]
    assert got == [False, True, False, True]


def test_protobuf_transcription_twin_of_rtvi_is_repeat() -> None:
    repeats = RtviRepeats()
    stamp = "2026-11-19T10:00:01"
    assert not repeats.is_repeat(AgentTranscription("haan", "u", stamp))
    assert repeats.is_repeat(_transcript("user-input", "haan", stamp))

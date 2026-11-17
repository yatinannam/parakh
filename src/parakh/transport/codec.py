"""Pipecat protobuf frame codec and defensive RTVI message parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError
from pipecat.frames.protobufs import frames_pb2

# Generated protobuf classes are created dynamically, so pyright cannot see them.
Frame: Any = frames_pb2.Frame  # type: ignore[attr-defined]

BOT_STOPPED = "bot-stopped-speaking"
BOT_STARTED = "bot-started-speaking"
BOT_OUTPUT = "bot-output"
METRICS = "metrics"
ERROR = "error"  # RTVI error: data {"error": str, "fatal": bool}


class ProtocolError(ValueError):
    """The agent sent something that is not a Pipecat protobuf frame."""


@dataclass(frozen=True)
class AgentAudio:
    pcm: bytes
    sample_rate: int
    num_channels: int


@dataclass(frozen=True)
class AgentText:
    text: str


@dataclass(frozen=True)
class AgentTranscription:
    text: str
    user_id: str
    timestamp: str


@dataclass(frozen=True)
class AgentInterruption:
    pass


@dataclass(frozen=True)
class RtviMessage:
    type: str
    data: dict[str, Any]
    raw: object


AgentEvent = AgentAudio | AgentText | AgentTranscription | AgentInterruption | RtviMessage


def encode_audio(pcm: bytes, sample_rate: int, num_channels: int = 1) -> bytes:
    frame = Frame()
    frame.audio.audio = pcm
    frame.audio.sample_rate = sample_rate
    frame.audio.num_channels = num_channels
    return frame.SerializeToString()


def _parse_message(text: str) -> RtviMessage:
    try:
        obj = json.loads(text)
    except ValueError:
        return RtviMessage(type="", data={}, raw=text)
    if not isinstance(obj, dict):
        return RtviMessage(type="", data={}, raw=text)
    msg_type = obj.get("type")
    data = obj.get("data")
    return RtviMessage(
        type=msg_type if isinstance(msg_type, str) else "",
        data=data if isinstance(data, dict) else {},
        raw=obj,
    )


def decode_frame(data: bytes) -> AgentEvent:
    frame = Frame()
    try:
        frame.ParseFromString(data)
    except DecodeError as exc:
        raise ProtocolError(f"agent sent a frame that is not Pipecat protobuf: {exc}") from exc
    kind = frame.WhichOneof("frame")
    if kind == "audio":
        a = frame.audio
        return AgentAudio(pcm=a.audio, sample_rate=a.sample_rate, num_channels=a.num_channels)
    if kind == "text":
        return AgentText(text=frame.text.text)
    if kind == "transcription":
        t = frame.transcription
        return AgentTranscription(text=t.text, user_id=t.user_id, timestamp=t.timestamp)
    if kind == "interruption":
        return AgentInterruption()
    if kind == "message":
        return _parse_message(frame.message.data)
    raise ProtocolError("agent sent a frame that is not Pipecat protobuf: no frame field set")


def caller_transcript(msg: RtviMessage) -> tuple[str, bool] | None:
    """Return (text, final) for the caller's speech transcript, else None."""
    if msg.type == "user-input" and msg.data.get("input_type") != "transcription":
        return None
    if msg.type not in ("user-input", "user-transcription"):
        return None
    text = msg.data.get("text")
    if not isinstance(text, str):
        return None
    return text, msg.data.get("final") is True


class RtviRepeats:
    """Spots RTVI messages that repeat one already received, so each is recorded once.

    Pipecat 1.13 and later send every transcription twice: as user-input and as its
    deprecated twin user-transcription, with the same text, final flag and timestamp.
    They report every spoken bot-output segment at least twice under one segment_id:
    when it starts ("new") and once it is spoken ("completed", with "in-progress"
    between them for TTS services with word timestamps). The first message counts.
    """

    def __init__(self) -> None:
        self._segments: set[int | str] = set()
        self._last_transcript: tuple[str, tuple[object, ...]] | None = None

    def is_repeat(self, msg: RtviMessage) -> bool:
        if msg.type == BOT_OUTPUT:
            segment = msg.data.get("segment_id")
            if isinstance(segment, bool) or not isinstance(segment, int | str):
                return False
            if segment in self._segments:
                return True
            self._segments.add(segment)
            return False
        if caller_transcript(msg) is None:
            return False
        data = msg.data
        key = (data.get("text"), data.get("final") is True, data.get("timestamp"))
        last, self._last_transcript = self._last_transcript, (msg.type, key)
        return last is not None and last[0] != msg.type and last[1] == key


def agent_info(msg: RtviMessage) -> dict[str, Any] | None:
    if msg.type != "server-message":
        return None
    info = msg.data.get("agent_info")
    return info if isinstance(info, dict) else None

"""Map agent events to the events the call driver records.

Pure functions: no clock, no recorder. The driver applies a Mapped to its state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from parakh.audio import PCM, SUPPORTED_RATES
from parakh.transport.codec import (
    BOT_OUTPUT,
    BOT_STARTED,
    BOT_STOPPED,
    ERROR,
    METRICS,
    USER_STARTED,
    USER_STOPPED,
    AgentAudio,
    AgentEvent,
    AgentInterruption,
    AgentText,
    AgentTranscription,
    ProtocolError,
    RtviMessage,
    RtviRepeats,
    agent_info,
    caller_transcript,
)
from parakh.transport.ws import redact_urls

CallStatus = Literal[
    # The turn machine finished, or the agent closed the socket after replying to the
    # last caller turn the script plays.
    "completed",
    "turn_timeout",  # no agent audio within response_timeout_s of a wait starting
    "call_timeout",  # call_timeout_s since t0
    "agent_disconnected",  # socket closed after the first caller turn, before completion
    "agent_hung_up_early",  # socket closed before the first caller turn
    "agent_unreachable",  # the WebSocket could not be opened
    "protocol_error",  # the agent sent something that is not a valid Pipecat frame
    "interrupted",  # Ctrl+C; only the run layer builds a result with this status
    "real_data_refused",  # a real run, and the agent is not provably local (parakh.caller.realdata)
]


@dataclass(frozen=True)
class Mapped:
    kind: str | None  # event kind to record, or None to record none
    fields: dict[str, Any]
    warning: str | None = None
    agent_info: dict[str, Any] | None = None
    bot_stopped: bool = False
    interruption: bool = False


def agent_pcm(audio: AgentAudio) -> PCM:
    """Mono int16 samples of an agent audio frame; ProtocolError if it is malformed."""
    if audio.sample_rate not in SUPPORTED_RATES:
        raise ProtocolError(f"agent sent audio with unsupported sample rate {audio.sample_rate}")
    # 0 means the field was left unset; Pipecat's default is mono.
    if audio.num_channels not in (0, 1, 2):
        raise ProtocolError(f"agent sent {audio.num_channels}-channel audio; expected mono")
    if len(audio.pcm) % 2:
        raise ProtocolError("agent sent 16-bit audio with an odd number of bytes")
    pcm = np.frombuffer(audio.pcm, dtype="<i2").astype(np.int16)
    if audio.num_channels != 2:
        return pcm
    if len(pcm) % 2:
        raise ProtocolError("agent sent stereo audio with an odd number of samples")
    pairs = pcm.reshape(-1, 2).astype(np.int32)
    return ((pairs[:, 0] + pairs[:, 1] + 1) >> 1).astype(np.int16)


def agent_error_text(msg: RtviMessage) -> str:
    """Warning text for an RTVI error message, with any URL in it redacted (EC-82)."""
    text = msg.data.get("error")
    detail = redact_urls(text) if isinstance(text, str) and text.strip() else "(no message)"
    fatal = " (fatal)" if msg.data.get("fatal") is True else ""
    return f"agent error{fatal}: {detail}"


def map_event(event: AgentEvent, repeats: RtviRepeats) -> Mapped:
    """Map any agent event except AgentAudio."""
    if isinstance(event, AgentAudio):
        raise TypeError("AgentAudio is handled by the driver")
    if isinstance(event, AgentText):
        return Mapped("bot_output", {"text": event.text})
    if isinstance(event, AgentInterruption):
        return Mapped("agent_interruption", {}, interruption=True)
    if isinstance(event, AgentTranscription):
        if repeats.is_repeat(event):
            return Mapped("rtvi_repeat", {"type": "transcription"})
        return Mapped("caller_transcript", {"text": event.text, "final": True})
    return _map_rtvi(event, repeats)


def _map_rtvi(msg: RtviMessage, repeats: RtviRepeats) -> Mapped:
    if repeats.is_repeat(msg):
        return Mapped("rtvi_repeat", {"type": msg.type})
    transcript = caller_transcript(msg)
    info = agent_info(msg)
    if transcript is not None:
        text, final = transcript
        return Mapped("caller_transcript", {"text": text, "final": final})
    if info is not None:
        return Mapped("agent_info", {"info": info}, agent_info=info)
    if msg.type == BOT_STARTED:
        return Mapped("bot_started", {})
    if msg.type == BOT_STOPPED:
        return Mapped("bot_stopped", {}, bot_stopped=True)
    if msg.type == BOT_OUTPUT:
        text = msg.data.get("text")
        return Mapped("bot_output", {"text": text if isinstance(text, str) else ""})
    if msg.type == METRICS:
        return Mapped("agent_metrics", {"data": msg.data})
    if msg.type == USER_STARTED:
        return Mapped("user_started", {})
    if msg.type == USER_STOPPED:
        return Mapped("user_stopped", {})
    if msg.type == ERROR:
        return Mapped(None, {}, warning=agent_error_text(msg))
    return Mapped("rtvi_unknown", {"type": msg.type})


def barge_event(
    barge: bool | None, turn: int, after_ms: int | None, onset_ms: float
) -> tuple[str, dict[str, Any]] | None:
    """The event for how a turn with a barge-in began: barge_in, barge_in_missed, or none."""
    if barge is True:
        return "barge_in", {
            "turn": turn,
            "after_agent_ms": after_ms,
            "agent_onset_ms": round(onset_ms, 3),
        }
    if barge is False:
        return "barge_in_missed", {"turn": turn, "after_agent_ms": after_ms}
    return None

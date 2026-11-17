"""Driver logic that needs no socket: agent audio checks, URL checks, bot-stopped handling."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from parakh.caller import driver
from parakh.caller.recorder import Recorder, read_events
from parakh.caller.turns import TurnState
from parakh.scenario import CallerVoice, Limits, Scenario, Turn
from parakh.transport.codec import BOT_STOPPED, AgentAudio, ProtocolError, RtviMessage
from parakh.transport.ws import AgentConnection

T0 = 1_000_000_000
MS = 1_000_000


def _scenario(limits: Limits | None = None) -> Scenario:
    return Scenario(
        schema_version=1,
        id="unit-call",
        title="Unit call",
        language="hi-en",
        domain="test",
        clock=datetime(2026, 11, 16, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        caller=CallerVoice(voice="hi-IN-SwaraNeural"),
        turns=[Turn(say="haan")],
        limits=limits or Limits(),
    )


@pytest.mark.parametrize(
    ("audio", "match"),
    [
        (AgentAudio(b"\x00\x00" * 4, 0, 1), "sample rate"),
        (AgentAudio(b"\x00\x00" * 4, 16000, 2), "channel"),
        (AgentAudio(b"\x00\x00\x00", 16000, 1), "odd"),
    ],
)
def test_malformed_agent_audio_is_protocol_error(audio: AgentAudio, match: str) -> None:
    with pytest.raises(ProtocolError, match=match):
        driver.agent_pcm(audio)


def test_unset_channel_count_is_mono() -> None:
    pcm = driver.agent_pcm(AgentAudio(b"\x01\x00\x02\x00", 16000, 0))
    assert pcm.tolist() == [1, 2]


async def test_non_ws_url_rejected_before_anything_is_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ws://"):
        await AgentConnection.connect("http://127.0.0.1:1")
    run_dir = tmp_path / "dir with space" / "run"
    with pytest.raises(ValueError, match="ws://"):
        await driver.run_call("http://127.0.0.1:1", _scenario(), [], run_dir)
    assert not run_dir.exists()


def test_bot_stopped_kept_until_the_agent_speaking_step(tmp_path: Path) -> None:
    # A burst reply can deliver all its audio and bot-stopped-speaking before the step
    # that first sees speech. That step moves WAIT_AGENT to AGENT_SPEAKING and would
    # drop the flag, so it is kept for the next step, and the reply then ends when
    # playback ends instead of after the 800 ms silence fallback.
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    rec = Recorder(tmp_path / "dir with space" / "run", T0)
    try:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        call._on_event(AgentAudio(b"\x00\x10" * 9600, 16000, 1), T0)  # 600 ms of audio
        call._on_event(RtviMessage(BOT_STOPPED, {}, {}), T0 + MS)
        assert call._step(T0 + 20 * MS).kind == "none"
        assert call.machine.state is TurnState.AGENT_SPEAKING
        assert call._step(T0 + 40 * MS).kind == "none"
        action = call._step(T0 + 600 * MS)
        assert (action.kind, action.turn_index) == ("start_turn", 0)
    finally:
        rec.close()


def test_pipecat_twin_messages_are_recorded_once(tmp_path: Path) -> None:
    # Pipecat 1.16 sends each transcription as user-input and user-transcription, and
    # each spoken bot segment as a "new" and a "completed" bot-output. Recording both
    # doubled every transcript and agent reply in the first live run (WER above 100 %).
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    run_dir = tmp_path / "run"
    rec = Recorder(run_dir, T0)
    segment = {"text": "Hello, Parakh Clinic.", "segment_id": 41, "will_be_spoken": True}
    heard = {"text": "हाँ", "final": True, "timestamp": "2026-11-17T06:10:00", "user_id": ""}
    messages = [
        RtviMessage("bot-output", {**segment, "spoken": False, "spoken_status": "new"}, {}),
        RtviMessage("bot-output", {**segment, "spoken": True, "spoken_status": "completed"}, {}),
        RtviMessage("user-input", {**heard, "input_type": "transcription"}, {}),
        RtviMessage("user-transcription", heard, {}),
    ]
    try:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        for k, message in enumerate(messages):
            call._on_event(message, T0 + k * MS)
    finally:
        rec.close()
    events = read_events(run_dir)
    assert [e["text"] for e in events if e["kind"] == "bot_output"] == ["Hello, Parakh Clinic."]
    assert [e["text"] for e in events if e["kind"] == "caller_transcript"] == ["हाँ"]
    assert [e["type"] for e in events if e["kind"] == "rtvi_repeat"] == [
        "bot-output",
        "user-transcription",
    ]


def test_silent_agent_frames_do_not_suppress_turn_timeout(tmp_path: Path) -> None:
    # EC-27: frames at or below -45 dBFS are not speech. An agent that streams
    # silence while it says nothing must still time out in WAIT_AGENT, not move
    # to AGENT_SPEAKING and wait there until call_timeout.
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    rec = Recorder(tmp_path / "run", T0)
    silent = AgentAudio(b"\x00\x00" * 320, 16000, 1)  # one 20 ms frame of zeros
    try:
        call = driver._Call(_scenario(Limits(response_timeout_s=1.0)), [clip], rec, T0, 16000, 800)
        kinds = []
        for k in range(60):  # 1.2 s, one silent frame per 20 ms step
            now = T0 + k * 20 * MS
            call._on_event(silent, now)
            kinds.append(call._step(now).kind)
            assert call.machine.state is not TurnState.AGENT_SPEAKING
    finally:
        rec.close()
    assert kinds.index("timeout") == 50  # 1000 ms after the wait began

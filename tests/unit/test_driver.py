"""Driver logic that needs no socket: agent audio checks, URL checks, bot-stopped handling."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from parakh.audio import read_wav
from parakh.caller import driver
from parakh.caller.recorder import Recorder, read_events
from parakh.caller.turns import Action, TurnState
from parakh.scenario import CallerVoice, Limits, Scenario, Turn
from parakh.transport.codec import (
    BOT_STOPPED,
    AgentAudio,
    AgentInterruption,
    AgentText,
    RtviMessage,
)
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


def test_rtvi_error_becomes_a_warning_in_the_report(tmp_path: Path) -> None:
    # Run 106c8e4e: edge-tts returned no audio for a reply and the agent sent two RTVI
    # "error" messages, which were logged only as rtvi_unknown; the report showed a
    # bare turn_timeout. They are now warnings, with any URL in the text redacted.
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    run_dir = tmp_path / "run"
    rec = Recorder(run_dir, T0)
    text = "No audio was received from wss://tts.example/v1?Token=SECRET#x, retry"
    try:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        call._on_event(RtviMessage("error", {"error": text, "fatal": False}, {}), T0 + MS)
        call._on_event(RtviMessage("error", {"error": "pipeline stopped", "fatal": True}, {}), T0)
        call._on_event(RtviMessage("error", {"fatal": False}, {}), T0 + 2 * MS)
    finally:
        rec.close()
    expected = [
        "agent error: No audio was received from wss://tts.example/v1, retry",
        "agent error (fatal): pipeline stopped",
        "agent error: (no message)",
    ]
    assert call.warnings == expected
    events = read_events(run_dir)
    assert [e["message"] for e in events if e["kind"] == "warning"] == expected
    assert not [e for e in events if e["kind"] == "rtvi_unknown"]
    assert "SECRET" not in (run_dir / "events.jsonl").read_text(encoding="utf-8")


class _FakeConn:
    """Duck-typed connection whose recv() never suspends."""

    def __init__(self, count: int) -> None:
        self._left = count

    async def recv(self) -> AgentText | None:
        if self._left == 0:
            return None
        self._left -= 1
        return AgentText("hi")


async def test_receive_yields_between_messages(tmp_path: Path) -> None:
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    rec = Recorder(tmp_path / "dir with space" / "run", T0)
    ticks = 0
    stop = False

    async def counter() -> None:
        nonlocal ticks
        while not stop:
            ticks += 1
            await asyncio.sleep(0)

    try:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        task = asyncio.create_task(counter())
        await call._receive(_FakeConn(200))  # type: ignore[arg-type]
        stop = True
        await task
    finally:
        rec.close()
    assert ticks >= 100


def test_bot_stopped_hold_discarded_at_caller_turn_end(tmp_path: Path) -> None:
    # A bot-stopped that arrives while the caller's clip plays belongs to the reply
    # before it. Once the clip's last frame is sent it is discarded, so a new burst
    # reply is not ended by it: the reply waits for end_of_turn_silence_ms of quiet.
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 2, 1)
    rec = Recorder(tmp_path / "dir with space" / "run", T0)

    class _Conn:
        async def send_audio(self, data: bytes, rate: int) -> None:
            return None

    async def run() -> None:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        call._turn, call._frames, call._next = 0, clip.frames, 0
        await call._send_frame(_Conn())  # type: ignore[arg-type]
        call._on_event(RtviMessage(BOT_STOPPED, {}, {}), T0 + MS)
        assert call._bot_stopped
        await call._send_frame(_Conn())  # type: ignore[arg-type]  # last frame
        assert not call._bot_stopped
        call.machine.state = TurnState.WAIT_AGENT
        call._on_event(AgentAudio(b"\x00\x10" * 3200, 16000, 1), T0 + 100 * MS)  # 200 ms
        assert call._step(T0 + 101 * MS).kind == "none"
        assert call.machine.state is TurnState.AGENT_SPEAKING
        # playback ends at 300 ms; with no bot-stopped the reply waits 800 ms of quiet
        assert call._step(T0 + 400 * MS).kind == "none"
        assert call._step(T0 + 1000 * MS).kind == "none"

    try:
        asyncio.run(run())
    finally:
        rec.close()


def test_bot_stopped_hold_not_passed_in_wait_agent_or_caller_speaking(tmp_path: Path) -> None:
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    rec = Recorder(tmp_path / "dir with space" / "run", T0)
    passed: list[bool] = []
    try:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        real = call.machine.step

        def spy(*args: Any, **kwargs: Any) -> Action:
            passed.append(bool(kwargs["bot_stopped"]))
            return real(*args, **kwargs)

        call.machine.step = spy  # type: ignore[method-assign]
        call._on_event(RtviMessage(BOT_STOPPED, {}, {}), T0)
        call.machine.state = TurnState.WAIT_AGENT
        call._step(T0 + 20 * MS)
        call.machine.state = TurnState.CALLER_SPEAKING
        call._step(T0 + 40 * MS)
        assert passed == [False, False]
        assert call._bot_stopped
        call.machine.state = TurnState.AGENT_SPEAKING
        call._step(T0 + 60 * MS)
        assert passed[-1] is True
        assert not call._bot_stopped
    finally:
        rec.close()


def test_interruption_flushes_clock_and_recorder(tmp_path: Path) -> None:
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    run_dir = tmp_path / "dir with space" / "run"
    rec = Recorder(run_dir, T0)
    try:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        call._on_event(AgentAudio(b"\x00\x10" * 16000, 16000, 1), T0)  # 1000 ms
        call._on_event(AgentInterruption(), T0 + 400 * MS)
        assert not call._clock.speaking(T0 + 401 * MS)
    finally:
        rec.close()
    events = read_events(run_dir)
    interruption = [e for e in events if e["kind"] == "agent_interruption"]
    assert [e["flushed_ms"] for e in interruption] == [600.0]
    pcm, _ = read_wav(run_dir / "agent.wav")
    assert not pcm[6400:].any()
    assert pcm[:6400].any()


def test_streamed_silence_behind_a_burst_does_not_delay_the_next_reply(tmp_path: Path) -> None:
    # M1 drift: an agent streams a silent frame every 20 ms while a burst reply is still
    # queued on the playback clock. The silence used to queue behind the burst and push
    # every later reply, and loud_end, later by the silence it had streamed.
    clip = driver._Clip([np.zeros(320, dtype=np.int16)] * 20, 19)
    rec = Recorder(tmp_path / "dir with space" / "run", T0)
    silent = AgentAudio(b"\x00\x00" * 320, 16000, 1)
    try:
        call = driver._Call(_scenario(), [clip], rec, T0, 16000, 800)
        call._on_event(AgentAudio(b"\x00\x10" * 9600, 16000, 1), T0)  # 600 ms burst
        for k in range(1, 30):
            call._on_event(silent, T0 + k * 20 * MS)  # all arrive before the burst ends
        assert call._clock.loud_end_ns == T0 + 600 * MS
        assert call._clock.playback_end_ns == T0 + 600 * MS
        call._on_event(AgentAudio(b"\x00\x10" * 9600, 16000, 1), T0 + 1000 * MS)
        assert call._clock.loud_end_ns == T0 + 1600 * MS  # not 1780 ms
    finally:
        rec.close()

"""Driver logic that needs no socket: agent audio checks, URL checks, bot-stopped handling."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from parakh.caller import driver
from parakh.caller.recorder import Recorder
from parakh.caller.turns import TurnState
from parakh.scenario import CallerVoice, Scenario, Turn
from parakh.transport.codec import BOT_STOPPED, AgentAudio, ProtocolError, RtviMessage
from parakh.transport.ws import AgentConnection

T0 = 1_000_000_000
MS = 1_000_000


def _scenario() -> Scenario:
    return Scenario(
        schema_version=1,
        id="unit-call",
        title="Unit call",
        language="hi-en",
        domain="test",
        clock=datetime(2026, 11, 16, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        caller=CallerVoice(voice="hi-IN-SwaraNeural"),
        turns=[Turn(say="haan")],
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

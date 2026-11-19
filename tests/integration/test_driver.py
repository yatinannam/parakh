"""Real-time calls between the driver and the fake Pipecat agent on 127.0.0.1."""

import hashlib
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from parakh.audio import SPEECH_DBFS, dbfs, read_wav, speech_end_ms, write_wav
from parakh.caller import driver
from parakh.caller.driver import CallResult, run_call
from parakh.caller.line import CallerLine, build_line
from parakh.caller.recorder import read_events
from parakh.scenario import BargeIn, CallerVoice, Limits, Scenario, Turn
from parakh.score.latency import response_latencies
from parakh.tts.cache import CallerClip, TTSCache
from tests.fakes import FakeEngine
from tests.integration.fake_agent import FakeBehaviour, fake_agent

pytestmark = pytest.mark.integration

TOL_MS = 60 if os.environ.get("CI") else 20
CLIP_MS = 400
IST = timezone(timedelta(hours=5, minutes=30))


def _write_clips(clip_dir: Path, n: int) -> list[CallerClip]:
    rate = 16000
    t = np.arange(rate * CLIP_MS // 1000) / rate
    pcm = np.round(3000 * np.sin(2 * np.pi * 300 * t)).astype(np.int16)
    clips = []
    for i in range(n):
        path = clip_dir / f"turn {i}.wav"
        write_wav(path, pcm, rate)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        clips.append(CallerClip(i, path, rate, speech_end_ms(pcm, rate), CLIP_MS, digest))
    return clips


async def _line(
    base: Path,
    clips: list[CallerClip],
    scenario: Scenario,
    preset: str = "clean",
    rate: int = 16000,
) -> CallerLine:
    """The caller line for clips, as run_scenario builds it."""
    cache = TTSCache(base / "cache")
    return await build_line(scenario, clips, preset, rate, cache=cache, engine=FakeEngine())


def _scenario(
    n_turns: int,
    agent_speaks_first: bool,
    call_timeout_s: float,
    max_turns: int = 12,
    barge_in: dict[int, int] | None = None,
) -> Scenario:
    barge_in = barge_in or {}
    return Scenario(
        schema_version=1,
        id="fake-call",
        title="Fake call",
        language="hi-en",
        domain="test",
        clock=datetime(2026, 11, 16, 10, 0, tzinfo=IST),
        agent_speaks_first=agent_speaks_first,
        caller=CallerVoice(voice="hi-IN-SwaraNeural"),
        turns=[
            Turn(
                say=f"turn {i}",
                barge_in=BargeIn(after_agent_ms=barge_in[i]) if i in barge_in else None,
            )
            for i in range(n_turns)
        ],
        limits=Limits(response_timeout_s=1.5, call_timeout_s=call_timeout_s, max_turns=max_turns),
    )


async def _call(
    tmp_path: Path,
    behaviour: FakeBehaviour,
    *,
    turns: int = 1,
    agent_speaks_first: bool = True,
    call_timeout_s: float = 20.0,
    max_turns: int = 12,
    agent_rate: int = 16000,
    preset: str = "clean",
    barge_in: dict[int, int] | None = None,
) -> tuple[CallResult, list[dict[str, Any]]]:
    base = tmp_path / "dir with space"
    clips = _write_clips(base / "clips", turns)
    scenario = _scenario(turns, agent_speaks_first, call_timeout_s, max_turns, barge_in)
    line = await _line(base, clips, scenario, preset, agent_rate)
    async with fake_agent(behaviour) as url:
        result = await run_call(url, scenario, line, base / "run")
    return result, read_events(result.run_dir)


def _kinds(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == kind]


def _assert_ends_with_call_end(events: list[dict[str, Any]], status: str) -> None:
    assert events[0]["kind"] == "call_start"
    assert events[-1]["kind"] == "call_end"
    assert events[-1]["status"] == status
    assert len(_kinds(events, "call_end")) == 1


async def test_latency_matches_reply_delay(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(reply_delay_ms=500), turns=2)
    assert result.status == "completed"
    assert result.turns_started == 2
    latencies = response_latencies(events)
    print("latencies_ms", [x.latency_ms for x in latencies])
    assert [x.turn for x in latencies] == [0, 1]
    for x in latencies:
        assert x.latency_ms is not None
        assert abs(x.latency_ms - 500) <= TOL_MS
    _assert_ends_with_call_end(events, "completed")


async def test_transcripts_and_agent_info_recorded(tmp_path: Path) -> None:
    info = {"llm_model": "fake-llm", "pipecat": "1.16.0"}
    texts = ["haan ji", "कल सुबह दस बजे"]
    behaviour = FakeBehaviour(transcripts=texts, agent_info=info)
    result, events = await _call(tmp_path, behaviour, turns=2)
    assert result.status == "completed"
    transcripts = _kinds(events, "caller_transcript")
    assert [e["text"] for e in transcripts] == texts
    assert all(e["final"] is True for e in transcripts)
    assert result.agent_info == info
    assert [e["info"] for e in _kinds(events, "agent_info")] == [info]
    assert len(_kinds(events, "bot_started")) == 3
    assert len(_kinds(events, "bot_stopped")) == 3


async def test_turn_timeout(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(silent_after_turn=0), turns=2)
    assert result.status == "turn_timeout"
    assert result.turns_started == 1
    assert (result.run_dir / "caller.wav").is_file()
    assert (result.run_dir / "events.jsonl").is_file()
    turn_end = _kinds(events, "caller_turn_end")[0]["t_ms"]
    assert events[-1]["t_ms"] - turn_end == pytest.approx(1500, abs=100)
    _assert_ends_with_call_end(events, "turn_timeout")


async def test_disconnect_mid_call_keeps_partial_results(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(close_after_replies=1), turns=2)
    assert result.status == "agent_disconnected"
    _assert_ends_with_call_end(events, "agent_disconnected")
    caller, _ = read_wav(result.run_dir / "caller.wav")
    agent, _ = read_wav(result.run_dir / "agent.wav")
    assert len(caller) > 0
    assert np.abs(agent).max() > 0


async def test_hangup_before_first_turn(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(close_before_greeting=True))
    assert result.status == "agent_hung_up_early"
    assert result.turns_started == 0
    _assert_ends_with_call_end(events, "agent_hung_up_early")


async def test_protocol_error_is_fast(tmp_path: Path) -> None:
    start = time.perf_counter()
    result, events = await _call(tmp_path, FakeBehaviour(send_garbage=True))
    assert time.perf_counter() - start < 2.0
    assert result.status == "protocol_error"
    assert events[-1]["t_ms"] < 2000
    assert any("not Pipecat protobuf" in w for w in result.warnings)
    assert any("not Pipecat protobuf" in e["message"] for e in _kinds(events, "warning"))
    _assert_ends_with_call_end(events, "protocol_error")


async def test_caller_first_line_silence(tmp_path: Path) -> None:
    behaviour = FakeBehaviour(greet_ms=None)
    result, events = await _call(tmp_path, behaviour, agent_speaks_first=False)
    assert result.status == "completed"
    assert _kinds(events, "caller_turn_start")[0]["t_ms"] >= 1000


async def test_agent_at_24k(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(out_rate=24000), turns=2)
    assert result.status == "completed"
    assert {e["sample_rate"] for e in _kinds(events, "agent_audio")} == {24000}
    latencies = response_latencies(events)
    print("latencies_ms", [x.latency_ms for x in latencies])
    for x in latencies:
        assert x.latency_ms is not None
        assert abs(x.latency_ms - 500) <= TOL_MS


async def test_unreachable(tmp_path: Path) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"ws://127.0.0.1:{port}"
    base = tmp_path / "dir with space"
    clips = _write_clips(base / "clips", 1)
    scenario = _scenario(1, True, 20.0)
    line = await _line(base, clips, scenario)
    result = await run_call(url, scenario, line, base / "run")
    assert result.status == "agent_unreachable"
    assert any(url in w for w in result.warnings)
    _assert_ends_with_call_end(read_events(result.run_dir), "agent_unreachable")


async def test_jitter_recorded(tmp_path: Path) -> None:
    result, _ = await _call(tmp_path, FakeBehaviour())
    print("jitter", result.jitter)
    assert result.jitter.n > 0
    assert result.jitter.max_ms >= result.jitter.p99_ms >= result.jitter.p50_ms >= 0


async def test_call_timeout(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(), turns=2, call_timeout_s=1.0)
    assert result.status == "call_timeout"
    assert events[-1]["t_ms"] == pytest.approx(1000, abs=50)
    _assert_ends_with_call_end(events, "call_timeout")


async def test_bot_stopped_ends_burst_reply_at_playback_end(tmp_path: Path) -> None:
    # The greeting arrives as a burst followed at once by bot-stopped-speaking. The
    # caller must start when playback ends, not after the 800 ms silence fallback.
    result, events = await _call(tmp_path, FakeBehaviour(reply_ms=600))
    assert result.status == "completed"
    greeting_start = _kinds(events, "agent_audio")[0]["t_ms"]
    first_turn = _kinds(events, "caller_turn_start")[0]["t_ms"]
    assert 600 <= first_turn - greeting_start < 600 + 200


async def test_paced_agent_audio(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(burst=False))
    assert result.status == "completed"
    latencies = response_latencies(events)
    assert latencies[0].latency_ms is not None
    assert abs(latencies[0].latency_ms - 500) <= TOL_MS


async def test_cpu_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver.psutil, "cpu_percent", lambda interval=None: 95.0)
    result, events = await _call(tmp_path, FakeBehaviour())
    assert result.cpu_max_percent == 95.0
    message = "cpu above 85 percent during the call (max 95.0)"
    assert message in result.warnings
    assert message in [e["message"] for e in _kinds(events, "warning")]
    _assert_ends_with_call_end(events, "completed")


def _first_loud_ms(path: Path) -> float:
    pcm, rate = read_wav(path)
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) > 32768 * 10 ** (SPEECH_DBFS / 20))
    assert loud.size > 0
    return float(loud[0]) * 1000 / rate


async def test_caller_and_agent_tracks_share_t0(tmp_path: Path) -> None:
    # A slow handshake makes the connect time visible: caller.wav must still start at
    # t0, like agent.wav and the event timestamps.
    result, events = await _call(tmp_path, FakeBehaviour(accept_delay_ms=150))
    assert result.status == "completed"
    turn_start = _kinds(events, "caller_turn_start")[0]["t_ms"]
    first_audio = _kinds(events, "agent_audio")[0]["t_ms"]
    assert first_audio > 150
    assert abs(_first_loud_ms(result.run_dir / "caller.wav") - turn_start) <= TOL_MS
    assert abs(_first_loud_ms(result.run_dir / "agent.wav") - first_audio) <= TOL_MS


async def test_close_after_final_reply_is_completed(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(close_after_replies=2), turns=2)
    assert result.status == "completed"
    assert result.turns_started == 2
    _assert_ends_with_call_end(events, "completed")


async def test_close_after_reply_to_max_turns_is_completed(tmp_path: Path) -> None:
    behaviour = FakeBehaviour(close_after_replies=1)
    result, events = await _call(tmp_path, behaviour, turns=2, max_turns=1)
    assert result.status == "completed"
    assert result.turns_started == 1
    _assert_ends_with_call_end(events, "completed")


@pytest.mark.parametrize("burst", [True, False])
async def test_agent_streaming_silence_between_replies_completes(
    tmp_path: Path, burst: bool
) -> None:
    # EC-27: silent frames are not speech. They used to extend the playback end,
    # so an agent that streams silence between replies never left AGENT_SPEAKING
    # and every call ended call_timeout.
    behaviour = FakeBehaviour(stream_silence=True, burst=burst)
    result, events = await _call(tmp_path, behaviour, turns=2, call_timeout_s=10.0)
    assert result.status == "completed"
    assert result.turns_started == 2
    assert any(e["dbfs"] <= SPEECH_DBFS for e in _kinds(events, "agent_audio"))
    latencies = response_latencies(events)
    print("latencies_ms", [x.latency_ms for x in latencies])
    assert [x.turn for x in latencies] == [0, 1]
    for x in latencies:
        assert x.latency_ms is not None
        assert abs(x.latency_ms - 500) <= TOL_MS
    # The first caller turn starts when the greeting's loud audio ends (bot-stopped
    # latch), not after the silence streamed behind it.
    loud = [e for e in _kinds(events, "agent_audio") if e["dbfs"] > SPEECH_DBFS]
    first_turn = _kinds(events, "caller_turn_start")[0]["t_ms"]
    assert 600 <= first_turn - loud[0]["t_ms"] < 600 + 200
    _assert_ends_with_call_end(events, "completed")


async def test_agent_streaming_silence_still_times_out(tmp_path: Path) -> None:
    # Silent frames in WAIT_AGENT must not count as the reply starting.
    behaviour = FakeBehaviour(stream_silence=True, silent_after_turn=0)
    result, events = await _call(tmp_path, behaviour, turns=2, call_timeout_s=8.0)
    assert result.status == "turn_timeout"
    assert result.turns_started == 1
    turn_end = _kinds(events, "caller_turn_end")[0]["t_ms"]
    assert events[-1]["t_ms"] - turn_end == pytest.approx(1500, abs=100)
    _assert_ends_with_call_end(events, "turn_timeout")


async def test_close_before_final_reply_is_disconnected(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(close_before_reply_to=1), turns=2)
    assert result.status == "agent_disconnected"
    assert result.turns_started == 2
    assert len(_kinds(events, "caller_turn_end")) == 2
    _assert_ends_with_call_end(events, "agent_disconnected")


async def test_speech_end_logged_on_its_frame(tmp_path: Path) -> None:
    rate = 16000
    t = np.arange(rate * 400 // 1000) / rate
    tone = np.round(3000 * np.sin(2 * np.pi * 300 * t)).astype(np.int16)
    pcm = np.concatenate([tone, np.zeros(rate * 200 // 1000, dtype=np.int16)])
    base = tmp_path / "dir with space"
    path = base / "clips" / "turn 0.wav"
    write_wav(path, pcm, rate)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    clip = CallerClip(0, path, rate, 400, 600, digest)
    scenario = _scenario(1, True, 20.0)
    line = await _line(base, [clip], scenario)
    async with fake_agent(FakeBehaviour()) as url:
        result = await run_call(url, scenario, line, base / "run")
    events = read_events(result.run_dir)
    speech_end = _kinds(events, "caller_speech_end")[0]
    frame20 = [e for e in _kinds(events, "caller_frame") if e["turn"] == 0 and e["frame"] == 20]
    assert len(frame20) == 1
    assert speech_end["t_ms"] == frame20[0]["t_ms"]


async def test_8khz_wire_call(tmp_path: Path) -> None:
    behaviour = FakeBehaviour(out_rate=8000)
    result, events = await _call(tmp_path, behaviour, turns=2, agent_rate=8000)
    assert result.status == "completed"
    assert behaviour.received
    assert all(entry == (8000, 160) for entry in behaviour.received)
    latencies = response_latencies(events)
    assert len(latencies) == 2
    for x in latencies:
        assert x.latency_ms is not None
        assert abs(x.latency_ms - 500) <= TOL_MS
    assert read_wav(result.run_dir / "caller.wav")[1] == 16000


async def test_phone_preset_latency(tmp_path: Path) -> None:
    result, events = await _call(
        tmp_path, FakeBehaviour(reply_delay_ms=500), turns=2, preset="phone"
    )
    assert result.status == "completed"
    latencies = response_latencies(events)
    assert len(latencies) == 2
    for x in latencies:
        assert x.latency_ms is not None
        assert abs(x.latency_ms - 500) <= TOL_MS


async def test_noise_preset_call_completes(tmp_path: Path) -> None:
    # The FakeEngine babble is a steady tone bed. The fake's own threshold sits between
    # the bed and the quietest speech frame, so it hears the speech and not the bed.
    base = tmp_path / "dir with space"
    clips = _write_clips(base / "clips", 2)
    scenario = _scenario(2, True, 20.0)
    line = await _line(base, clips, scenario, "phone_noisy")
    bed_level = dbfs(np.concatenate(line.bed))
    speech = [dbfs(f) for t in line.turns for f in t.frames[: max(1, t.speech_end_frame - 1)]]
    quietest = min(speech)
    assert quietest > bed_level
    behaviour = FakeBehaviour(vad_dbfs=(bed_level + quietest) / 2)
    async with fake_agent(behaviour) as url:
        result = await run_call(url, scenario, line, base / "run")
    assert result.status == "completed"
    assert result.turns_started == 2
    events = read_events(result.run_dir)
    assert any(e["turn"] is None for e in _kinds(events, "caller_frame"))


async def test_lossy_preset_logs_lost_frames(tmp_path: Path) -> None:
    base = tmp_path / "dir with space"
    clips = _write_clips(base / "clips", 2)
    scenario = _scenario(2, True, 20.0)
    line = await _line(base, clips, scenario, "phone_lossy")
    async with fake_agent(FakeBehaviour()) as url:
        result = await run_call(url, scenario, line, base / "run")
    assert result.status == "completed"
    frames = _kinds(read_events(result.run_dir), "caller_frame")
    assert frames
    for e in frames:
        flags = line.bed_lost if e["turn"] is None else line.turns[e["turn"]].lost
        assert e["lost"] is flags[e["frame"]]


async def _barge_call(tmp_path: Path, **behaviour: Any) -> tuple[CallResult, list[dict[str, Any]]]:
    return await _call(
        tmp_path, FakeBehaviour(reply_ms=3000, **behaviour), turns=2, barge_in={1: 1200}
    )


async def test_barge_in_agent_yields_with_interruption(tmp_path: Path) -> None:
    result, events = await _barge_call(
        tmp_path, burst=False, yield_after_ms=300, send_interruption=True
    )
    assert result.status == "completed"
    (barge,) = _kinds(events, "barge_in")
    assert barge["turn"] == 1
    assert barge["after_agent_ms"] == 1200
    # The machine fires on the first 20 ms tick at or after onset + 1200, so the
    # send can trail it by up to one tick on top of the timing tolerance.
    assert -TOL_MS <= barge["t_ms"] - barge["agent_onset_ms"] - 1200 <= TOL_MS + 20
    assert [e for e in _kinds(events, "agent_interruption") if e["t_ms"] > barge["t_ms"]]
    assert not _kinds(events, "barge_in_missed")
    _assert_ends_with_call_end(events, "completed")


def _loud_between(path: Path, start_ms: float, end_ms: float) -> bool:
    pcm, rate = read_wav(path)
    seg = pcm[round(start_ms * rate / 1000) : round(end_ms * rate / 1000)]
    return dbfs(seg) > SPEECH_DBFS


async def test_barge_in_burst_reply_is_flushed(tmp_path: Path) -> None:
    result, events = await _barge_call(
        tmp_path, burst=True, yield_after_ms=300, send_interruption=True
    )
    assert result.status == "completed"
    (barge,) = _kinds(events, "barge_in")
    cut = next(e for e in _kinds(events, "agent_interruption") if e["t_ms"] > barge["t_ms"])
    assert cut["flushed_ms"] > 500
    # The next reply is due about 600 ms after the cut.
    assert not _loud_between(result.run_dir / "agent.wav", cut["t_ms"] + 40, cut["t_ms"] + 450)


async def test_barge_in_agent_never_yields(tmp_path: Path) -> None:
    result, events = await _barge_call(tmp_path, burst=False)
    assert result.status == "completed"
    (barge,) = _kinds(events, "barge_in")
    assert not _kinds(events, "agent_interruption")
    assert _loud_between(result.run_dir / "agent.wav", barge["t_ms"], barge["t_ms"] + 2000)


async def test_barge_in_missed_short_reply(tmp_path: Path) -> None:
    result, events = await _call(tmp_path, FakeBehaviour(reply_ms=600), turns=2, barge_in={1: 1200})
    assert result.status == "completed"
    (missed,) = _kinds(events, "barge_in_missed")
    assert missed["turn"] == 1
    assert missed["after_agent_ms"] == 1200
    assert not _kinds(events, "barge_in")

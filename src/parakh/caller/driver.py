"""Real-time call driver over Pipecat's protobuf WebSocket protocol.

One task paces a 20 ms caller frame on every tick for the whole call (the frames of
the caller turn in progress, else the line's noise bed, looped) and steps the turn
machine. The frames come prepared and degraded from parakh.caller.line. A second
task receives agent events: audio feeds the virtual playback clock and the
recorder, RTVI messages become events. The recorder is always closed, so a failed
call still leaves events.jsonl and both WAV tracks, and call_end is the last event.

A call completes when the turn machine finishes, or when the agent closes the
socket after the last caller turn the script plays (the final turn, or the
max_turns-th) was fully sent and loud agent audio arrived after its speech end.
Any earlier close is agent_disconnected, or agent_hung_up_early before the first
caller turn.

Every timestamp is time.perf_counter_ns(); t0 is taken just before connecting.
Both WAV tracks start at t0: caller.wav is led by silence for the connect time.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from parakh.audio import FRAME_MS, PCM, SAMPLE_RATE, SPEECH_DBFS, dbfs
from parakh.caller.clock import PlaybackClock
from parakh.caller.events import CallStatus, agent_pcm, barge_event, map_event
from parakh.caller.line import CallerLine
from parakh.caller.pacer import JitterStats, Pacer
from parakh.caller.realdata import RealDataGate
from parakh.caller.recorder import Recorder
from parakh.caller.turns import Action, TurnMachine, TurnState
from parakh.scenario import Scenario
from parakh.transport.codec import (
    AgentAudio,
    AgentEvent,
    ProtocolError,
    RtviRepeats,
)
from parakh.transport.ws import AgentConnection, AgentUnreachable, check_agent_url

CPU_WARN_PERCENT = 85.0
_WAV_RATE = SAMPLE_RATE
_NS_PER_S = 1_000_000_000
_NS_PER_MS = 1_000_000


@dataclass
class CallResult:
    status: CallStatus
    run_dir: Path
    turns_started: int
    jitter: JitterStats
    timing_unreliable: bool
    cpu_max_percent: float
    agent_info: dict[str, Any]
    warnings: list[str]


class _Call:
    def __init__(
        self,
        scenario: Scenario,
        line: CallerLine,
        recorder: Recorder,
        t0_ns: int,
        end_of_turn_silence_ms: float,
        gate: RealDataGate | None = None,
    ) -> None:
        self._gate = gate  # set for a real run: recorded frames wait for it
        self._line = line
        self._rec = recorder
        self._t0 = t0_ns
        self._rate = line.rate
        self._bed_next = 0  # the bed loops across the gaps between turns
        self._deadline_ns = t0_ns + round(scenario.limits.call_timeout_s * _NS_PER_S)
        self._barge_offsets = [
            None if t.barge_in is None else t.barge_in.after_agent_ms for t in scenario.turns
        ]
        self.machine = TurnMachine(
            len(line.turns),
            agent_speaks_first=scenario.agent_speaks_first,
            response_timeout_ms=scenario.limits.response_timeout_s * 1000,
            max_turns=scenario.limits.max_turns,
            end_of_turn_silence_ms=end_of_turn_silence_ms,
            barge_in_ms=self._barge_offsets,
        )
        self._barge: bool | None = None  # how the turn in progress began, if it has a barge-in
        self._turns_to_play = min(len(line.turns), scenario.limits.max_turns)
        self._clock = PlaybackClock()
        self.pacer = Pacer(frame_ns=FRAME_MS * _NS_PER_MS)
        self.status: CallStatus | None = None
        self._end_ns = t0_ns
        self.warnings: list[str] = []
        self.agent_info: dict[str, Any] = {}
        self.cpu_max = 0.0
        self._bot_stopped = False
        self._turn = 0
        self._frames: list[PCM] | None = None  # clip frames of the caller turn in progress
        self._next = 0
        self._speech_end_ns: int | None = None  # of the caller turn in progress
        self._reply_heard = False  # loud agent audio after that speech end
        self._repeats = RtviRepeats()

    def _ms(self, t_ns: int) -> float:
        return (t_ns - self._t0) / _NS_PER_MS

    def _event(self, kind: str, t_ns: int, **fields: Any) -> None:
        """Record an event unless the call has already ended (call_end stays last)."""
        if self.status is None:
            self._rec.event(kind, t_ns, **fields)

    def _warn(self, message: str, t_ns: int) -> None:
        self.warnings.append(message)
        self._rec.event("warning", t_ns, message=message)

    def _end(self, status: CallStatus, warning: str | None = None) -> None:
        """Set the terminal status; the first one wins."""
        if self.status is not None:
            return
        now = time.perf_counter_ns()
        if warning is not None:
            self._warn(warning, now)
        self.status = status
        self._end_ns = now

    def _log_end(self) -> None:
        if self.cpu_max > CPU_WARN_PERCENT:
            message = f"cpu above 85 percent during the call (max {self.cpu_max:.1f})"
            self._warn(message, self._end_ns)
        self._rec.event("call_end", self._end_ns, status=self.status)

    async def run(self, url: str) -> None:
        self._rec.event("call_start", self._t0, agent_rate=self._rate)
        try:
            conn = await AgentConnection.connect(url)
        except AgentUnreachable as exc:
            self._end("agent_unreachable", str(exc))
            self._log_end()
            return
        try:
            await self._converse(conn)
            self._log_end()
        finally:
            await conn.close()

    async def _converse(self, conn: AgentConnection) -> None:
        pace = asyncio.create_task(self._pace(conn))
        receive = asyncio.create_task(self._receive(conn))
        try:
            timeout_s = max(0, self._deadline_ns - time.perf_counter_ns()) / _NS_PER_S
            done, _ = await asyncio.wait(
                (pace, receive), timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()  # re-raise a crash in either loop
            if self.status is None:
                self._end("call_timeout")
        finally:
            pace.cancel()
            receive.cancel()
            await asyncio.gather(pace, receive, return_exceptions=True)

    async def _pace(self, conn: AgentConnection) -> None:
        pacer_t0 = self.pacer.start()
        # caller.wav is the sent frames in order, with no time origin of its own. Lead
        # it with silence for the time spent connecting, so it starts at t0.
        self._rec.caller_lead(round((pacer_t0 - self._t0) * self._rate / _NS_PER_S))
        next_cpu_ns = time.perf_counter_ns() + _NS_PER_S
        while True:
            await self.pacer.tick()
            if self.status is not None:
                return
            now = time.perf_counter_ns()
            if now >= next_cpu_ns:
                self.cpu_max = max(self.cpu_max, psutil.cpu_percent(interval=None))
                next_cpu_ns = now + _NS_PER_S
            if self._gate is not None:
                state = self._gate.poll()
                if state == "refused":
                    self._end("real_data_refused", self._gate.warning)
                    return
                if state == "pending":  # hold the turn: bed frames only, the turn machine waits
                    await self._send_frame(conn)
                    continue
            action = self._step(now)
            if action.kind == "finish":
                self._end("completed")
                return
            if action.kind == "timeout":
                self._end("turn_timeout")
                return
            if action.kind == "start_turn" and action.turn_index is not None:
                self._bot_stopped = False  # it belonged to the reply before this turn
                self._turn = action.turn_index
                self._frames = self._line.turns[action.turn_index].frames
                self._next = 0
                self._speech_end_ns = None
                self._reply_heard = False
                self._barge = action.barge_in
            await self._send_frame(conn)

    def _step(self, now_ns: int) -> Action:
        # A bot-stopped-speaking is passed on exactly one step: the first one taken in
        # AGENT_SPEAKING, where the machine latches it. Other states ignore it, and a
        # burst reply can bring its audio and bot-stopped before any step sees speech.
        bot_stopped = self._bot_stopped and self.machine.state is TurnState.AGENT_SPEAKING
        if bot_stopped:
            self._bot_stopped = False
        # The machine sees the playback end of the last loud frame (EC-27), so the
        # 800 ms fallback and the bot-stopped latch ignore silence streamed after it.
        end_ns = self._clock.loud_end_ns
        onset_ns = self._clock.onset_ns
        return self.machine.step(
            self._ms(now_ns),
            agent_speaking=self._clock.speaking(now_ns),
            playback_end_ms=None if end_ns is None else self._ms(end_ns),
            bot_stopped=bot_stopped,
            caller_done=self._frames is None,
            agent_onset_ms=None if onset_ns is None else self._ms(onset_ns),
        )

    async def _send_frame(self, conn: AgentConnection) -> None:
        frames = self._frames
        t_send = time.perf_counter_ns()
        if frames is not None:
            if self._next == 0:
                self._event("caller_turn_start", t_send, turn=self._turn)
                self._log_barge(t_send)
            if self._next == self._line.turns[self._turn].speech_end_frame:
                self._event("caller_speech_end", t_send, turn=self._turn)
                self._speech_end_ns = t_send
        if frames is None:
            turn, index, frame = None, self._bed_next, self._line.bed[self._bed_next]
            lost = self._line.bed_lost[index]
            self._bed_next = (self._bed_next + 1) % len(self._line.bed)
        else:
            turn, index, frame = self._turn, self._next, frames[self._next]
            lost = self._line.turns[turn].lost[index]
            if self._gate is not None:
                frame = self._gate.guard(frame)  # silence unless the gate is open
        self._rec.caller_frame(t_send, frame, self._rate, turn=turn, frame=index, lost=lost)
        await conn.send_audio(frame.tobytes(), self._rate)
        if frames is not None:
            self._next += 1
            if self._next == len(frames):
                self._event("caller_turn_end", time.perf_counter_ns(), turn=self._turn)
                self._bot_stopped = False  # it belonged to the reply before this one
                self._frames = None

    def _log_barge(self, t_ns: int) -> None:
        after = self._barge_offsets[self._turn]
        event = barge_event(self._barge, self._turn, after, self.machine.reply_onset_ms)
        if event is not None:
            self._event(event[0], t_ns, **event[1])

    async def _receive(self, conn: AgentConnection) -> None:
        try:
            while (event := await conn.recv()) is not None:
                self._on_event(event, time.perf_counter_ns())
                await asyncio.sleep(0)  # let the pacer run even when events arrive in a burst
        except ProtocolError as exc:
            self._end("protocol_error", str(exc))
            return
        self._end(self._close_status())

    def _close_status(self) -> CallStatus:
        """Status for a socket the agent closed."""
        if self.machine.turns_started == 0:
            return "agent_hung_up_early"
        last_turn_sent = self.machine.turns_started == self._turns_to_play and self._frames is None
        return "completed" if last_turn_sent and self._reply_heard else "agent_disconnected"

    def _on_event(self, event: AgentEvent, now: int) -> None:
        if self.status is not None:
            return
        if isinstance(event, AgentAudio):
            self._on_audio(event, now)
            return
        mapped = map_event(event, self._repeats)
        if mapped.warning is not None:
            self._warn(mapped.warning, now)
        fields = mapped.fields
        if mapped.interruption:
            dropped_ns = self._clock.flush(now)
            self._rec.agent_flush(now)
            fields = {**fields, "flushed_ms": round(dropped_ns / _NS_PER_MS, 3)}
        if mapped.kind is not None:
            self._event(mapped.kind, now, **fields)
        if mapped.agent_info is not None:
            self.agent_info = mapped.agent_info
            if self._gate is not None:
                self._gate.on_agent_info(mapped.agent_info)
        if mapped.bot_stopped:
            self._bot_stopped = True

    def _on_audio(self, audio: AgentAudio, now: int) -> None:
        pcm = agent_pcm(audio)
        loud = dbfs(pcm) > SPEECH_DBFS
        if self._speech_end_ns is not None and now > self._speech_end_ns:
            self._reply_heard = self._reply_heard or loud
        start = self._clock.on_audio(now, len(pcm), audio.sample_rate, loud=loud)
        play_ms = None if start is None else self._ms(start)
        self._rec.agent_frame(now, pcm, audio.sample_rate, play_ms)

    def result(self, run_dir: Path) -> CallResult:
        assert self.status is not None, "result() before the call ended"
        return CallResult(
            status=self.status,
            run_dir=run_dir,
            turns_started=self.machine.turns_started,
            jitter=self.pacer.stats(),
            timing_unreliable=self.pacer.unreliable(),
            cpu_max_percent=self.cpu_max,
            agent_info=self.agent_info,
            warnings=self.warnings,
        )


async def run_call(
    url: str,
    scenario: Scenario,
    line: CallerLine,
    run_dir: Path,
    *,
    end_of_turn_silence_ms: float = 800,
    real: bool = False,
) -> CallResult:
    """Run one real-time call against the agent at url and record it under run_dir.

    Call outcomes are reported in CallResult.status, never raised. A URL that is
    not ws:// or wss:// raises ValueError before anything is written. real puts the
    recorded turns behind a RealDataGate: silence until the agent proves it is local.
    """
    check_agent_url(url)
    psutil.cpu_percent(interval=None)  # primes the counter; this first reading is meaningless
    t0 = time.perf_counter_ns()
    recorder = Recorder(run_dir, t0, _WAV_RATE)
    gate = RealDataGate(t0) if real else None
    call = _Call(scenario, line, recorder, t0, end_of_turn_silence_ms, gate)
    try:
        await call.run(url)
    finally:
        recorder.close()
    return call.result(run_dir)

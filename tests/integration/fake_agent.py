"""Fake agent speaking Pipecat's protobuf WebSocket protocol, for integration tests.

It listens on 127.0.0.1, serves one connection, and answers each caller utterance
with a 440 Hz tone after a fixed delay, so the driver's latency measurement can be
checked against a known value.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pipecat.frames.protobufs import frames_pb2
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request

from parakh.audio import PCM, SPEECH_DBFS, dbfs, split_frames

# Generated protobuf classes are created dynamically, so pyright cannot see them.
_Frame: Any = frames_pb2.Frame  # type: ignore[attr-defined]

GARBAGE = b"\xff\x00 not protobuf"
TONE_HZ = 440
TONE_DBFS = -10.0
_NS_PER_MS = 1_000_000
_FRAME_NS = 20 * _NS_PER_MS
_TIMER_TICK_NS = 16 * _NS_PER_MS


@dataclass
class FakeBehaviour:
    """Scripted agent behaviour.

    Caller utterances are counted from 0: an utterance is a run of caller frames
    above -45 dBFS, ended by reply_delay_ms without a loud frame. The greeting is
    not a reply. silent_after_turn N means no reply to utterance N or any later one.
    close_after_replies N closes the socket after the N-th reply; close_before_reply_to
    N closes it when the reply to utterance N would start. accept_delay_ms holds the
    opening handshake back, so connecting takes that long. stream_silence sends a
    silent 20 ms frame every 20 ms whenever the agent is not speaking, as some
    telephony agents do, from connect to close. received records (sample_rate, n_samples)
    of every caller audio frame. vad_dbfs is the level a caller frame must exceed to count
    as speech, so a test can make the fake ignore a noise bed.
    """

    greet_ms: int | None = 300
    reply_delay_ms: int = 500
    reply_ms: int = 600
    out_rate: int = 16000
    burst: bool = True
    transcripts: list[str] = field(default_factory=list)
    close_after_replies: int | None = None
    close_before_greeting: bool = False
    silent_after_turn: int | None = None
    send_garbage: bool = False
    agent_info: dict[str, Any] | None = None
    close_before_reply_to: int | None = None
    accept_delay_ms: int = 0
    stream_silence: bool = False
    vad_dbfs: float = SPEECH_DBFS
    received: list[tuple[int, int]] = field(default_factory=list)


def _tone(rate: int, ms: int) -> PCM:
    amp = 32768 * math.sqrt(2) * 10 ** (TONE_DBFS / 20)
    t = np.arange(rate * ms // 1000) / rate
    return np.round(amp * np.sin(2 * np.pi * TONE_HZ * t)).astype(np.int16)


async def _sleep_until(deadline_ns: int) -> None:
    """Sleep until time.perf_counter_ns() reaches deadline_ns.

    asyncio timers on Windows follow a 15.6 ms clock, so a plain sleep can end a
    whole tick early or late. Sleep coarsely, then yield to the loop until the
    deadline, so the fake replies on time and the tests measure the driver.
    """
    remaining = deadline_ns - time.perf_counter_ns()
    if remaining > _TIMER_TICK_NS:
        await asyncio.sleep((remaining - _TIMER_TICK_NS) / 1e9)
    while time.perf_counter_ns() < deadline_ns:
        await asyncio.sleep(0)


def _audio(pcm: PCM, rate: int) -> bytes:
    frame = _Frame()
    frame.audio.audio = pcm.astype("<i2").tobytes()
    frame.audio.sample_rate = rate
    frame.audio.num_channels = 1
    return frame.SerializeToString()


def _rtvi(msg_type: str, data: dict[str, Any] | None = None) -> bytes:
    payload: dict[str, Any] = {"label": "rtvi-ai", "type": msg_type}
    if data is not None:
        payload["data"] = data
    frame = _Frame()
    frame.message.data = json.dumps(payload, ensure_ascii=False)
    return frame.SerializeToString()


class _Session:
    def __init__(self, ws: ServerConnection, behaviour: FakeBehaviour) -> None:
        self._ws = ws
        self._b = behaviour
        self._tasks: set[asyncio.Task[None]] = set()
        self._transcripts = iter(behaviour.transcripts)
        tone = _tone(behaviour.out_rate, behaviour.reply_ms)
        self._reply = [
            _audio(pcm, behaviour.out_rate) for pcm in split_frames(tone, behaviour.out_rate)
        ]
        self._silence = _audio(
            np.zeros(behaviour.out_rate // 50, dtype=np.int16), behaviour.out_rate
        )
        self._start_ns = time.perf_counter_ns()
        self._last_loud_ns = 0
        self._waiting = False
        self._speaking = False
        self._utterances = 0
        self._replies = 0

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        self._tasks.add(asyncio.create_task(coro))

    async def run(self) -> None:
        b = self._b
        try:
            if b.close_before_greeting:
                await self._ws.close()
                return
            if b.send_garbage:
                await self._ws.send(GARBAGE)
            if b.agent_info is not None:
                await self._ws.send(_rtvi("server-message", {"agent_info": b.agent_info}))
            if b.greet_ms is not None:
                self._spawn(self._greet(b.greet_ms))
            if b.stream_silence:
                self._spawn(self._stream_silence())
            async for message in self._ws:
                self._on_message(message)
        except ConnectionClosed:
            pass
        finally:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _on_message(self, message: str | bytes) -> None:
        if isinstance(message, str):
            return
        frame = _Frame.FromString(message)
        if frame.WhichOneof("frame") != "audio":
            return
        self._b.received.append((frame.audio.sample_rate, len(frame.audio.audio) // 2))
        if dbfs(np.frombuffer(frame.audio.audio, dtype="<i2")) <= self._b.vad_dbfs:
            return
        self._last_loud_ns = time.perf_counter_ns()
        if self._waiting:
            return  # debounced: the waiting reply re-reads _last_loud_ns
        self._waiting = True
        self._spawn(self._reply_after_quiet(self._utterances))
        self._utterances += 1

    async def _greet(self, greet_ms: int) -> None:
        await _sleep_until(self._start_ns + greet_ms * _NS_PER_MS)
        await self._speak()

    async def _reply_after_quiet(self, utterance: int) -> None:
        b = self._b
        delay_ns = b.reply_delay_ms * _NS_PER_MS
        while (due := self._last_loud_ns + delay_ns) > time.perf_counter_ns():
            await _sleep_until(due)  # a newer loud frame moves the due time; check again
        self._waiting = False
        if utterance == b.close_before_reply_to:
            await self._ws.close()
            return
        if b.silent_after_turn is not None and utterance >= b.silent_after_turn:
            return
        text = next(self._transcripts, None)
        if text is not None:
            await self._ws.send(
                _rtvi("user-input", {"text": text, "input_type": "transcription", "final": True})
            )
        await self._speak()
        self._replies += 1
        if b.close_after_replies is not None and self._replies >= b.close_after_replies:
            await self._ws.close()

    async def _stream_silence(self) -> None:
        k = 0
        while True:
            k += 1
            await _sleep_until(self._start_ns + k * _FRAME_NS)
            if not self._speaking:
                await self._ws.send(self._silence)

    async def _speak(self) -> None:
        self._speaking = True
        await self._ws.send(_rtvi("bot-started-speaking"))
        start_ns = time.perf_counter_ns()
        for k, message in enumerate(self._reply):
            if not self._b.burst:
                await _sleep_until(start_ns + k * _FRAME_NS)
            await self._ws.send(message)
            # The fake shares the driver's event loop; yield after each frame so the
            # driver reads it on arrival, as it would from an agent in its own process.
            await asyncio.sleep(0)
        await self._ws.send(_rtvi("bot-stopped-speaking"))
        self._speaking = False


@asynccontextmanager
async def fake_agent(behaviour: FakeBehaviour) -> AsyncIterator[str]:
    """Serve one connection with the given behaviour; yield its ws:// URL."""
    served = False

    async def handler(ws: ServerConnection) -> None:
        nonlocal served
        if served:
            await ws.close()
            return
        served = True
        await _Session(ws, behaviour).run()

    async def delay_handshake(ws: ServerConnection, request: Request) -> None:
        await asyncio.sleep(behaviour.accept_delay_ms / 1000)

    async with serve(
        handler, "127.0.0.1", 0, max_size=None, process_request=delay_handshake
    ) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"

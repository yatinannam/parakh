"""Call recorder: events.jsonl plus the caller and agent audio tracks."""

import json
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from parakh.audio import PCM, SAMPLE_RATE, dbfs, resample, write_wav

EVENTS_FILE = "events.jsonl"


@dataclass
class _Placed:
    offset: int  # sample offset on the agent track, at the WAV rate
    pcm: PCM  # at its own rate
    rate: int


class Recorder:
    """Append call events to events.jsonl and keep both audio tracks in memory.

    Timestamps are monotonic nanoseconds; t_ms is relative to t0_ns. A writer thread
    appends and flushes each event line, so a stalled disk write (NTFS and filter
    drivers can block one for 30 ms or more) never blocks the caller's event loop.
    close() waits until every line is written.
    """

    def __init__(self, run_dir: Path, t0_ns: int, wav_rate: int = SAMPLE_RATE) -> None:
        self._run_dir = run_dir
        self._t0_ns = t0_ns
        self._wav_rate = wav_rate
        run_dir.mkdir(parents=True, exist_ok=True)
        self._events = (run_dir / EVENTS_FILE).open("a", encoding="utf-8", newline="\n")
        self._lead = 0  # caller samples before the first sent frame, at the caller rate
        self._caller: list[PCM] = []
        self._caller_rate: int | None = None
        self._agent: list[_Placed] = []
        self._closed = False
        self._lines: queue.SimpleQueue[str | None] = queue.SimpleQueue()
        self._write_error: Exception | None = None
        self._writer = threading.Thread(target=self._write_lines, name="recorder", daemon=True)
        self._writer.start()

    def _t_ms(self, t_ns: int) -> float:
        return round((t_ns - self._t0_ns) / 1e6, 3)

    def _write_lines(self) -> None:
        while (line := self._lines.get()) is not None:
            if self._write_error is not None:
                continue  # keep draining so close() can finish; close() raises the error
            try:
                self._events.write(line)
                self._events.flush()
            except Exception as exc:
                self._write_error = exc

    def event(self, kind: str, t_ns: int, **fields: Any) -> None:
        """Queue one event line; the writer thread appends and flushes it."""
        if self._closed:
            raise ValueError("event() on a closed Recorder")
        record: dict[str, Any] = {"kind": kind, "t_ms": self._t_ms(t_ns), **fields}
        self._lines.put(json.dumps(record, ensure_ascii=False) + "\n")

    def caller_lead(self, n_samples: int) -> None:
        """Silence before the first sent frame, in samples at the caller frame rate."""
        self._lead = n_samples

    def caller_frame(
        self,
        t_ns: int,
        pcm: PCM,
        sample_rate: int,
        *,
        turn: int | None,
        frame: int | None,
        lost: bool = False,
    ) -> None:
        """Log a caller_frame event and append the frame to the caller track.

        The track is resampled once, in close(), so every frame shares one rate."""
        if self._caller_rate not in (None, sample_rate):
            raise ValueError(
                f"caller frame rate {sample_rate} differs from the call rate {self._caller_rate}"
            )
        self._caller_rate = sample_rate
        self._caller.append(pcm)
        self.event("caller_frame", t_ns, turn=turn, frame=frame, lost=lost)

    def agent_frame(
        self, t_ns: int, pcm: PCM, sample_rate: int, playback_start_ms: float | None
    ) -> None:
        """Log an agent_audio event; a placed frame also goes on the agent timeline."""
        self.event(
            "agent_audio",
            t_ns,
            duration_ms=round(len(pcm) * 1000 / sample_rate, 3),
            dbfs=round(dbfs(pcm), 2),
            sample_rate=sample_rate,
            play_ms=None if playback_start_ms is None else round(playback_start_ms, 3),
        )
        if playback_start_ms is None:
            return
        offset = round(playback_start_ms * self._wav_rate / 1000)
        if offset < 0:
            pcm = pcm[round(-offset * sample_rate / self._wav_rate) :]
            offset = 0
        if len(pcm):
            self._agent.append(_Placed(offset, pcm, sample_rate))

    def agent_flush(self, t_ns: int) -> None:
        """Cut the agent track at t_ns: placed audio that plays after it is dropped."""
        cut = round(self._t_ms(t_ns) * self._wav_rate / 1000)
        kept: list[_Placed] = []
        for f in self._agent:
            if f.offset >= cut:
                continue
            keep = round((cut - f.offset) * f.rate / self._wav_rate)
            kept.append(_Placed(f.offset, f.pcm[:keep], f.rate) if keep < len(f.pcm) else f)
        self._agent = [f for f in kept if len(f.pcm)]

    def _agent_track(self) -> PCM:
        """Join frames that touch (same rate, within 1 sample); resample each run once."""
        runs: list[tuple[int, int, list[PCM], float]] = []  # offset, rate, frames, end sample
        for f in self._agent:
            end = f.offset + len(f.pcm) * self._wav_rate / f.rate
            if runs and runs[-1][1] == f.rate and abs(f.offset - runs[-1][3]) <= 1:
                off, rate, frames, _ = runs.pop()
                runs.append((off, rate, [*frames, f.pcm], end))
            else:
                runs.append((f.offset, f.rate, [f.pcm], end))
        placed = [
            (off, resample(np.concatenate(frames), rate, self._wav_rate))
            for off, rate, frames, _ in runs
        ]
        agent = np.zeros(max((off + len(p) for off, p in placed), default=0), dtype=np.int16)
        for off, p in placed:
            agent[off : off + len(p)] = p
        return agent

    def _caller_track(self) -> PCM:
        pcm = np.concatenate([np.zeros(self._lead, dtype=np.int16), *self._caller])
        return resample(pcm, self._caller_rate or self._wav_rate, self._wav_rate)

    def close(self) -> None:
        """Write caller.wav and agent.wav, padded to the same length, and finish
        events.jsonl. Idempotent. Raises a deferred event write error, if any."""
        if self._closed:
            return
        self._closed = True
        try:
            caller = self._caller_track()
            agent = self._agent_track()
            total = max(len(caller), len(agent))
            caller = np.pad(caller, (0, total - len(caller)))
            agent = np.pad(agent, (0, total - len(agent)))
            write_wav(self._run_dir / "caller.wav", caller, self._wav_rate)
            write_wav(self._run_dir / "agent.wav", agent, self._wav_rate)
        finally:
            self._lines.put(None)
            self._writer.join()
            self._events.close()
        if self._write_error is not None:
            raise self._write_error


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    """Parse events.jsonl; tolerate a partial final line, reject other bad lines."""
    lines = (run_dir / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for i, line in enumerate(lines, start=1):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if i == len(lines):
                break
            raise ValueError(f"invalid JSON on line {i} of events.jsonl") from exc
    return out

"""Call recorder: events.jsonl plus the caller and agent audio tracks."""

import json
import queue
import threading
from pathlib import Path
from typing import Any

import numpy as np

from parakh.audio import PCM, SAMPLE_RATE, dbfs, resample, write_wav

EVENTS_FILE = "events.jsonl"


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
        self._caller: list[PCM] = []
        self._agent: list[tuple[int, PCM]] = []
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

    def caller_frame(self, t_ns: int, pcm: PCM, sample_rate: int) -> None:
        """Append a caller frame to the caller track (no event is logged)."""
        self._caller.append(resample(pcm, sample_rate, self._wav_rate))

    def agent_frame(self, t_ns: int, pcm: PCM, sample_rate: int, playback_start_ms: float) -> None:
        """Log an agent_audio event and place the frame on the agent timeline."""
        self.event(
            "agent_audio",
            t_ns,
            duration_ms=round(len(pcm) * 1000 / sample_rate, 3),
            dbfs=round(dbfs(pcm), 2),
            sample_rate=sample_rate,
        )
        offset = round(playback_start_ms * self._wav_rate / 1000)
        placed = resample(pcm, sample_rate, self._wav_rate)
        if offset < 0:
            placed = placed[-offset:]
            offset = 0
        if len(placed):
            self._agent.append((offset, placed))

    def close(self) -> None:
        """Write caller.wav and agent.wav, padded to the same length, and finish
        events.jsonl. Idempotent. Raises a deferred event write error, if any."""
        if self._closed:
            return
        self._closed = True
        try:
            caller = np.concatenate(self._caller) if self._caller else np.zeros(0, dtype=np.int16)
            agent_len = max((off + len(p) for off, p in self._agent), default=0)
            agent = np.zeros(agent_len, dtype=np.int16)
            for off, p in self._agent:
                agent[off : off + len(p)] = p
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

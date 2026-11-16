"""Absolute-deadline pacer for 20 ms frame streaming.

Relative sleeps drift (asyncio timers are about 15.6 ms coarse on Windows), so the
k-th tick targets t0 + k * frame_ns. A late tick does not sleep and never shifts
the schedule.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

TIMING_UNRELIABLE_P99_MS = 30.0
_NS_PER_MS = 1_000_000


@dataclass(frozen=True)
class JitterStats:
    n: int
    p50_ms: float
    p99_ms: float
    max_ms: float


class Pacer:
    def __init__(
        self,
        frame_ns: int = 20_000_000,
        now: Callable[[], int] = time.perf_counter_ns,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._frame_ns = frame_ns
        self._now = now
        self._sleep = sleep
        self._t0: int | None = None
        self._k = 0
        self._lateness_ns: list[int] = []

    def start(self) -> int:
        self._t0 = self._now()
        return self._t0

    async def tick(self) -> int:
        if self._t0 is None:
            raise RuntimeError("Pacer.tick() called before start()")
        deadline = self._t0 + self._k * self._frame_ns
        self._k += 1
        current = self._now()
        if current < deadline:
            await self._sleep((deadline - current) / 1e9)
        self._lateness_ns.append(max(0, self._now() - deadline))
        return deadline

    def stats(self) -> JitterStats:
        if not self._lateness_ns:
            return JitterStats(0, 0.0, 0.0, 0.0)
        ms = np.asarray(self._lateness_ns, dtype=np.float64) / _NS_PER_MS
        return JitterStats(
            n=len(ms),
            p50_ms=float(np.percentile(ms, 50)),
            p99_ms=float(np.percentile(ms, 99)),
            max_ms=float(ms.max()),
        )

    def unreliable(self) -> bool:
        return self.stats().p99_ms > TIMING_UNRELIABLE_P99_MS

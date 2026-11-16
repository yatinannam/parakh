import pytest

from parakh.caller.pacer import TIMING_UNRELIABLE_P99_MS, JitterStats, Pacer

MS = 1_000_000


class FakeClock:
    def __init__(self, oversleep_ns: dict[int, int] | None = None) -> None:
        self.t_ns = 0
        self.oversleep_ns = oversleep_ns or {}
        self.sleeps: list[float] = []

    def now(self) -> int:
        return self.t_ns

    async def sleep(self, seconds: float) -> None:
        extra = self.oversleep_ns.get(len(self.sleeps), 0)
        self.sleeps.append(seconds)
        self.t_ns += round(seconds * 1e9) + extra


async def test_pacer_keeps_absolute_schedule() -> None:
    # Third sleep (the one for tick 3, as tick 0 is due immediately) oversleeps 50 ms.
    clock = FakeClock({2: 50 * MS})
    pacer = Pacer(now=clock.now, sleep=clock.sleep)
    t0 = pacer.start()
    assert t0 == 0
    deadlines = [await pacer.tick() for _ in range(8)]
    assert deadlines == [k * 20 * MS for k in range(8)]
    # tick 0 is due now; ticks 1-3 sleep (tick 3 oversleeps to 110 ms); ticks 4 and 5
    # are late and return without sleeping; ticks 6 and 7 sleep the remaining gap.
    assert clock.sleeps == [pytest.approx(s) for s in (0.02, 0.02, 0.02, 0.01, 0.02)]
    assert clock.t_ns == 140 * MS
    stats = pacer.stats()
    assert stats.n == 8
    assert stats.max_ms == pytest.approx(50.0)


async def test_pacer_late_tick_does_not_sleep() -> None:
    clock = FakeClock()
    pacer = Pacer(now=clock.now, sleep=clock.sleep)
    pacer.start()
    clock.t_ns = 100 * MS
    d = await pacer.tick()
    assert d == 0
    assert clock.sleeps == []
    assert pacer.stats().max_ms == pytest.approx(100.0)


async def test_tick_before_start_raises() -> None:
    pacer = Pacer(now=lambda: 0)
    with pytest.raises(RuntimeError):
        await pacer.tick()


async def test_pacer_stats_and_unreliable() -> None:
    pacer = Pacer(now=lambda: 0)
    assert pacer.stats() == JitterStats(0, 0.0, 0.0, 0.0)
    assert not pacer.unreliable()
    pacer._lateness_ns = [0] * 98 + [40 * MS, 40 * MS]  # pyright: ignore[reportPrivateUsage]
    stats = pacer.stats()
    assert stats.p99_ms > TIMING_UNRELIABLE_P99_MS
    assert pacer.unreliable()
    pacer._lateness_ns = [0] * 100  # pyright: ignore[reportPrivateUsage]
    assert not pacer.unreliable()

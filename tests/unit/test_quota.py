from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from parakh.budget.guard import RealDataRefused
from parakh.budget.quota import (
    DailyCounter,
    PaymentRequired,
    QuotaExhausted,
    RateLimited,
    TokenBucket,
    looks_rate_limited,
    retry_after_s,
    send_with_backoff,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_bucket_allows_burst_then_waits():
    clock = Clock()
    bucket = TokenBucket(2, clock=clock)
    await bucket.acquire(clock.sleep)
    await bucket.acquire(clock.sleep)
    assert clock.slept == []
    await bucket.acquire(clock.sleep)
    assert clock.slept == [pytest.approx(30.0)]


def test_counter_refuses_at_limit(tmp_path: Path):
    counter = DailyCounter(tmp_path / "q dir", "groq", "m", 2, today=lambda: date(2026, 11, 23))
    counter.take()
    counter.take()
    assert counter.count == 2
    with pytest.raises(QuotaExhausted) as info:
        counter.take()
    assert (info.value.provider, info.value.model) == ("groq", "m")
    assert counter.count == 2


def test_counter_resets_next_day(tmp_path: Path):
    day = [date(2026, 11, 23)]
    counter = DailyCounter(tmp_path, "groq", "openai/gpt-oss-120b", 1, today=lambda: day[0])
    counter.take()
    assert (tmp_path / "groq__openai_gpt-oss-120b__2026-11-23.json").is_file()
    day[0] = date(2026, 11, 24)
    assert counter.count == 0
    counter.take()


def test_counter_unreadable_file_counts_zero(tmp_path: Path):
    counter = DailyCounter(tmp_path, "g", "m", 3, today=lambda: date(2026, 11, 23))
    path = tmp_path / "g__m__2026-11-23.json"
    path.write_text("not json", encoding="utf-8")
    assert counter.count == 0
    path.write_text('{"requests": "x"}', encoding="utf-8")
    assert counter.count == 0
    counter.take()
    assert counter.count == 1


def test_retry_after_seconds_and_date():
    now = datetime(2026, 11, 23, 10, 0, 0, tzinfo=UTC)
    assert retry_after_s("3", now) == 3.0
    assert retry_after_s(" 2.5 ", now) == 2.5
    assert retry_after_s("-4", now) == 0.0
    assert retry_after_s("Mon, 23 Nov 2026 10:00:30 GMT", now) == 30.0
    assert retry_after_s("Mon, 23 Nov 2026 09:00:00 GMT", now) == 0.0
    assert retry_after_s(None, now) is None
    assert retry_after_s("soon", now) is None
    assert retry_after_s("nan", now) is None


def _sender(*responses: httpx.Response):
    queue = list(responses)
    calls: list[int] = []

    async def send() -> httpx.Response:
        calls.append(1)
        return queue.pop(0)

    return send, calls


def _kit(tmp_path: Path, clock: Clock, per_day: int = 100):
    bucket = TokenBucket(1000, clock=clock)
    counter = DailyCounter(tmp_path, "groq", "m", per_day, today=lambda: date(2026, 11, 23))
    return bucket, counter


async def _call(send, bucket, counter, clock: Clock, *, real: bool = False):
    return await send_with_backoff(
        send,
        provider="groq",
        model="m",
        real=real,
        bucket=bucket,
        counter=counter,
        sleep=clock.sleep,
    )


async def test_backoff_honours_retry_after(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock)
    send, _ = _sender(httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200))
    resp = await _call(send, bucket, counter, clock)
    assert resp.status_code == 200
    assert clock.slept == [3.0]


async def test_backoff_exponential_without_header(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock)
    send, _ = _sender(httpx.Response(429), httpx.Response(429), httpx.Response(200))
    await _call(send, bucket, counter, clock)
    assert clock.slept == [2.0, 4.0]


async def test_backoff_gives_up_after_retries(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock)
    send, calls = _sender(*[httpx.Response(429) for _ in range(5)])
    with pytest.raises(RateLimited):
        await _call(send, bucket, counter, clock)
    assert len(calls) == 5
    assert clock.slept == [2.0, 4.0, 8.0, 16.0]


async def test_long_retry_after_raises_at_once(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock)
    send, calls = _sender(httpx.Response(429, headers={"Retry-After": "3600"}))
    with pytest.raises(RateLimited) as info:
        await _call(send, bucket, counter, clock)
    assert clock.slept == []
    assert len(calls) == 1
    assert not isinstance(info.value, QuotaExhausted)
    assert (info.value.provider, info.value.model) == ("groq", "m")


async def test_402_raises_payment_required_no_retry(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock)
    send, calls = _sender(httpx.Response(402))
    with pytest.raises(PaymentRequired):
        await _call(send, bucket, counter, clock)
    assert len(calls) == 1


async def test_other_responses_returned_unchanged(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock)
    send, _ = _sender(httpx.Response(500))
    assert (await _call(send, bucket, counter, clock)).status_code == 500


async def test_daily_limit_stops_before_send(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock, per_day=0)
    send, calls = _sender(httpx.Response(200))
    with pytest.raises(QuotaExhausted):
        await _call(send, bucket, counter, clock)
    assert calls == []


async def test_real_payload_refused_before_send(tmp_path: Path):
    clock = Clock()
    bucket, counter = _kit(tmp_path, clock)
    send, calls = _sender(httpx.Response(200))
    with pytest.raises(RealDataRefused):
        await _call(send, bucket, counter, clock, real=True)
    assert calls == []
    assert counter.count == 0


def test_looks_rate_limited():
    assert looks_rate_limited("Error code: 429 - rate_limit_exceeded")
    assert looks_rate_limited("Rate limit reached")
    assert not looks_rate_limited("timeout")
    assert not looks_rate_limited("port 14290 closed")


async def test_bucket_caps_refill_at_capacity():
    clock = Clock()
    bucket = TokenBucket(2, clock=clock)
    clock.now += 120.0  # idle far longer than a full refill
    await bucket.acquire(clock.sleep)
    await bucket.acquire(clock.sleep)
    assert clock.slept == []
    await bucket.acquire(clock.sleep)
    assert clock.slept == [pytest.approx(30.0)]


async def test_bucket_refill_is_counted_once():
    clock = Clock()
    bucket = TokenBucket(2, clock=clock)
    for _ in range(4):
        await bucket.acquire(clock.sleep)
    assert clock.slept == [pytest.approx(30.0), pytest.approx(30.0)]


async def test_bucket_partial_refill_sleeps_the_remainder():
    clock = Clock()
    bucket = TokenBucket(2, clock=clock)
    await bucket.acquire(clock.sleep)
    await bucket.acquire(clock.sleep)
    clock.now += 10.0  # a third of a token
    await bucket.acquire(clock.sleep)
    assert clock.slept == [pytest.approx(20.0)]


async def test_bucket_cost_above_one():
    clock = Clock()
    bucket = TokenBucket(10, clock=clock)
    await bucket.acquire(clock.sleep, cost=6)
    assert clock.slept == []
    await bucket.acquire(clock.sleep, cost=6)
    assert clock.slept == [pytest.approx(12.0)]


async def test_bucket_cost_above_capacity_waits_for_full_then_empties():
    clock = Clock()
    bucket = TokenBucket(10, clock=clock)
    await bucket.acquire(clock.sleep, cost=4)
    await bucket.acquire(clock.sleep, cost=50)
    assert clock.slept == [pytest.approx(24.0)]
    await bucket.acquire(clock.sleep)
    assert clock.slept[-1] == pytest.approx(6.0)


def test_counter_take_amount(tmp_path: Path):
    counter = DailyCounter(tmp_path / "q dir", "groq", "m", 10, today=lambda: date(2026, 11, 24))
    counter.take(7)
    with pytest.raises(QuotaExhausted):
        counter.take(4)
    assert counter.count == 7


def test_token_counter_has_its_own_file(tmp_path: Path):
    def day() -> date:
        return date(2026, 11, 24)

    tokens = DailyCounter(tmp_path, "groq", "a/b", 100, today=day, unit="tokens")
    tokens.record(30)
    assert (tmp_path / "groq__a_b__tokens__2026-11-24.json").exists()
    assert DailyCounter(tmp_path, "groq", "a/b", 100, today=day).count == 0

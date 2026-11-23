"""Rate limiter, daily counter and 429 backoff for every remote LLM call Parakh makes."""

import asyncio
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from parakh.budget.guard import remote_call

_RATE_LIMITED = re.compile(r"\b429\b|rate.?limit", re.I)


class RateLimited(Exception):
    """A provider refused the call for now: a 429, or our own daily limit."""

    def __init__(self, provider: str, model: str, reason: str) -> None:
        super().__init__(f"{provider} {model} rate limited: {reason}")
        self.provider = provider
        self.model = model
        self.reason = reason


class QuotaExhausted(RateLimited):
    """The local daily counter is at its limit; nothing was sent."""


class PaymentRequired(Exception):
    """HTTP 402: the provider wants payment. Never retried."""

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(f"{provider} {model} answered 402 payment required")
        self.provider = provider
        self.model = model


class TokenBucket:
    """Holds per_minute tokens at most and refills continuously; starts full."""

    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = float(per_minute)
        self._rate = per_minute / 60.0
        self._clock = clock
        self._tokens = self._capacity
        self._stamp = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._stamp) * self._rate)
        self._stamp = now

    async def acquire(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        """Take one token, sleeping exactly until the next one when empty."""
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            await sleep((1.0 - self._tokens) / self._rate)


def _utc_today() -> date:
    return datetime.now(UTC).date()


class DailyCounter:
    """Requests sent today per provider and model, kept in a file under root.

    Days are UTC. Gemini resets at midnight Pacific, so its count is approximate.
    """

    def __init__(
        self,
        root: Path,
        provider: str,
        model: str,
        per_day: int,
        *,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._root = root
        self._provider = provider
        self._model = model
        self._per_day = per_day
        self._today = today

    def _path(self) -> Path:
        name = f"{self._provider}__{self._model.replace('/', '_')}__{self._today()}.json"
        return self._root / name

    @property
    def count(self) -> int:
        try:
            value = json.loads(self._path().read_text(encoding="utf-8"))["requests"]
        except (OSError, ValueError, KeyError, TypeError):
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    def take(self) -> None:
        used = self.count
        if used >= self._per_day:
            raise QuotaExhausted(
                self._provider, self._model, f"daily limit of {self._per_day} requests reached"
            )
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"requests": used + 1}), encoding="utf-8")


def retry_after_s(value: str | None, now: datetime) -> float | None:
    """Seconds from a Retry-After header (seconds or HTTP date); None when absent or invalid."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - now).total_seconds())
    return max(0.0, seconds) if math.isfinite(seconds) else None


async def send_with_backoff(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    provider: str,
    model: str,
    real: bool,
    bucket: TokenBucket,
    counter: DailyCounter,
    retries: int = 4,
    base_s: float = 2.0,
    max_s: float = 60.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.Response:
    """Send one request through the bucket and the daily counter; back off on 429.

    Raises RealDataRefused for real data (before anything else), PaymentRequired on 402
    (no retry), and RateLimited when a Retry-After is longer than max_s (no sleep) or
    the 429s outlast the retries.
    """
    remote_call(provider, real=real)
    for attempt in range(retries + 1):
        await bucket.acquire(sleep)
        counter.take()
        resp = await send()
        if resp.status_code == 402:
            raise PaymentRequired(provider, model)
        if resp.status_code != 429:
            return resp
        wait = retry_after_s(resp.headers.get("Retry-After"), datetime.now(UTC))
        if wait is not None and wait > max_s:
            raise RateLimited(provider, model, f"429 with Retry-After {wait:.0f} s")
        if attempt == retries:
            raise RateLimited(provider, model, f"429 after {retries} retries")
        await sleep(wait if wait is not None else min(max_s, base_s * 2**attempt))
    raise AssertionError("unreachable")  # pragma: no cover


def looks_rate_limited(text: str) -> bool:
    """True when an error text reads like a 429 or a rate limit."""
    return _RATE_LIMITED.search(text) is not None

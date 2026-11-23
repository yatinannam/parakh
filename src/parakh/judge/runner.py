"""Run the judge: cache, provider order, retries, fallback and honest failure reasons."""

import asyncio
import hashlib
import json
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import httpx

from parakh.budget.guard import RealDataRefused
from parakh.budget.quota import (
    DailyCounter,
    PaymentRequired,
    RateLimited,
    TokenBucket,
    send_with_backoff,
)
from parakh.judge.model import JudgeScores, parse_scores
from parakh.judge.prompt import SYSTEM_PROMPT, judge_payload, reached_turns
from parakh.judge.providers import (
    JudgeConfig,
    ProviderConfig,
    Reply,
    build_request,
    parse_reply,
)
from parakh.report.model import JudgeReport, Report

JUDGE_CACHE_ROOT = Path(".cache/judge")
QUOTA_ROOT = Path(".cache/quota")
ATTEMPTS = 4
REASON_MAX = 500
_TIMEOUT_S = 60.0
_BODY_CHARS = 200


class _Ended(Exception):
    """One provider is done for this report. kind is 'rate' or 'error'."""

    def __init__(self, kind: str, why: str) -> None:
        super().__init__(why)
        self.kind = kind
        self.why = why


def _first_line(exc: Exception) -> str:
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0]


class JudgeRunner:
    def __init__(
        self,
        config: JudgeConfig,
        keys: Mapping[str, str],
        *,
        cache_dir: Path = JUDGE_CACHE_ROOT,
        quota_dir: Path = QUOTA_ROOT,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        real: bool = False,
    ) -> None:
        self._config = config
        self._keys = dict(keys)
        self._cache_dir = cache_dir
        self._transport = transport
        self._sleep = sleep
        self._real = real
        self._buckets = {p.name: TokenBucket(p.rpm) for p in config.providers}
        self._counters = {
            p.name: DailyCounter(quota_dir, p.name, p.model, p.rpd) for p in config.providers
        }
        self._disabled: set[str] = set()

    def _cache_path(self, cfg: ProviderConfig, payload: str) -> Path:
        raw = json.dumps([cfg.name, cfg.model, self._config.prompt_version, payload])
        return self._cache_dir / f"{hashlib.sha256(raw.encode('utf-8')).hexdigest()}.json"

    def _read_cache(self, path: Path) -> tuple[JudgeScores, str | None, int | None] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scores = JudgeScores.model_validate(data["scores"])
            return scores, data.get("model_version"), data.get("tokens")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def _write_cache(self, path: Path, scores: JudgeScores, reply: Reply) -> None:
        body = {
            "scores": scores.model_dump(),
            "model_version": reply.model_version,
            "tokens": reply.tokens,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(body), encoding="utf-8")
        except OSError:
            pass  # a cache that cannot be written costs one request later, nothing else

    def _report(self, status: str, **fields: object) -> JudgeReport:
        return JudgeReport.model_validate(
            {"status": status, "prompt_version": self._config.prompt_version, **fields}
        )

    def _scrub(self, text: str) -> str:
        for key in sorted(self._keys.values(), key=len, reverse=True):
            if key:
                text = text.replace(key, "***")
        return text[:REASON_MAX]

    async def judge(self, report: Report, *, force: bool = False) -> JudgeReport:
        if not reached_turns(report) and not any(t.agent_text for t in report.turns):
            return self._report("skipped", reason="nothing to judge")
        payload = judge_payload(report)
        has_barge_in = any(t.barge_in is not None for t in reached_turns(report))
        reasons: list[str] = []
        kinds: list[str] = []
        attempts = 0
        for cfg in self._config.providers:
            path = self._cache_path(cfg, payload)
            if not force and (hit := self._read_cache(path)) is not None:
                scores, version, tokens = hit
                return self._report(
                    "ok",
                    provider=cfg.name,
                    model=cfg.model,
                    model_version=version,
                    scores=scores,
                    cached=True,
                    tokens=tokens,
                )
            key = self._keys.get(cfg.key_env)
            if not key:
                reasons.append(f"{cfg.name}: no key")
                continue
            if cfg.name in self._disabled:
                reasons.append(f"{cfg.name}: disabled after HTTP 402")
                kinds.append("error")
                continue
            sent = 0

            async def counted(client: httpx.AsyncClient, req: httpx.Request) -> httpx.Response:
                nonlocal sent
                sent += 1
                return await client.send(req)

            try:
                scores, reply = await self._ask(cfg, key, payload, has_barge_in, counted)
            except _Ended as ended:
                reasons.append(f"{cfg.name}: {ended.why}")
                kinds.append(ended.kind)
                attempts += sent
                continue
            attempts += sent
            self._write_cache(path, scores, reply)
            return self._report(
                "ok",
                provider=cfg.name,
                model=cfg.model,
                model_version=reply.model_version,
                scores=scores,
                attempts=attempts,
                tokens=reply.tokens,
            )
        reason = self._scrub("; ".join(reasons))
        if not kinds and all(r.endswith(": no key") for r in reasons):
            return self._report("skipped", reason=self._scrub("no judge API key; " + reason))
        status = "rate_limited" if kinds and all(k == "rate" for k in kinds) else "judge_error"
        return self._report(status, attempts=attempts, reason=reason)

    async def _ask(
        self,
        cfg: ProviderConfig,
        key: str,
        payload: str,
        has_barge_in: bool,
        counted: Callable[[httpx.AsyncClient, httpx.Request], Awaitable[httpx.Response]],
    ) -> tuple[JudgeScores, Reply]:
        last = "no reply"
        async with httpx.AsyncClient(transport=self._transport, timeout=_TIMEOUT_S) as client:
            request = build_request(cfg, key, SYSTEM_PROMPT, payload)
            for _ in range(ATTEMPTS):
                resp = await self._send(cfg, client, request, counted)
                try:
                    reply = parse_reply(cfg, resp)
                    if reply.truncated:
                        raise ValueError("reply was cut off at the token limit")
                    return parse_scores(reply.text, has_barge_in=has_barge_in), reply
                except ValueError as exc:
                    last = _first_line(exc)
        raise _Ended("error", f"invalid reply after {ATTEMPTS} attempts: {last}")

    async def _send(
        self,
        cfg: ProviderConfig,
        client: httpx.AsyncClient,
        request: httpx.Request,
        counted: Callable[[httpx.AsyncClient, httpx.Request], Awaitable[httpx.Response]],
    ) -> httpx.Response:
        try:
            resp = await send_with_backoff(
                lambda: counted(client, request),
                provider=cfg.name,
                model=cfg.model,
                real=self._real,
                bucket=self._buckets[cfg.name],
                counter=self._counters[cfg.name],
                sleep=self._sleep,
            )
        except RealDataRefused as exc:
            raise _Ended("error", "real data refused") from exc
        except PaymentRequired as exc:
            self._disabled.add(cfg.name)
            print(
                f"judge: {cfg.name} answered HTTP 402 (payment required); "
                "disabled for this process",
                file=sys.stderr,
            )
            raise _Ended("error", "HTTP 402 payment required, provider disabled") from exc
        except RateLimited as exc:
            raise _Ended("rate", f"rate limited ({exc.reason})") from exc
        except httpx.TimeoutException as exc:
            raise _Ended("error", "timeout") from exc
        except httpx.HTTPError as exc:
            raise _Ended("error", f"transport error: {type(exc).__name__}") from exc
        if not 200 <= resp.status_code < 300:
            body = resp.text.strip().replace("\n", " ")[:_BODY_CHARS]
            why = f"HTTP {resp.status_code}" + (f": {body}" if body else "")
            raise _Ended("error", why)
        return resp

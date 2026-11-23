import json
from collections.abc import Callable
from pathlib import Path

import httpx

from parakh.judge.providers import JudgeConfig, ProviderConfig, load_config
from parakh.judge.runner import JudgeRunner
from parakh.report.model import Report

from .helpers import not_reached, report, turn

GOOD = {
    "understanding": 4,
    "language_match": 5,
    "task_progress": 4,
    "politeness": 5,
    "interruption_handling": None,
    "rationale": "ok",
    "flags": [],
}
GROQ_KEY = "groq-test-key"
GEM_KEY = "gem-test-key"


def groq_body(finish: str = "stop", content: str | None = None) -> dict:
    return {
        "model": "gpt-oss-120b",
        "choices": [{"message": {"content": content or json.dumps(GOOD)}, "finish_reason": finish}],
        "usage": {"total_tokens": 50},
    }


def groq_ok(content: str | None = None) -> httpx.Response:
    return httpx.Response(200, json=groq_body(content=content))


def gem_ok() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(GOOD)}]}, "finishReason": "STOP"}
            ],
            "modelVersion": "gemini-v",
            "usageMetadata": {"totalTokenCount": 40},
        },
    )


class Fake:
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._run)

    def _run(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        return self._handler(req)

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]


async def _nosleep(_s: float) -> None:
    return None


def runner(
    tmp_path: Path,
    fake: Fake,
    keys: dict[str, str] | None = None,
    *,
    cfg: JudgeConfig | None = None,
    real: bool = False,
) -> JudgeRunner:
    return JudgeRunner(
        cfg or load_config(),
        {"GROQ_API_KEY": GROQ_KEY} if keys is None else keys,
        cache_dir=tmp_path / "judge cache",
        quota_dir=tmp_path / "quota dir",
        transport=fake.transport,
        sleep=_nosleep,
        real=real,
    )


def rep(text: str = "Hello") -> Report:
    return report(turn(1, reply=text))


def both(tmp_path: Path, h: Callable[[httpx.Request], httpx.Response]) -> tuple[JudgeRunner, Fake]:
    fake = Fake(h)
    return runner(tmp_path, fake, {"GROQ_API_KEY": GROQ_KEY, "GEMINI_API_KEY": GEM_KEY}), fake


async def test_groq_ok_and_cached(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    r = runner(tmp_path, fake)
    first = await r.judge(rep())
    assert first.status == "ok" and first.provider == "groq" and first.cached is False
    assert first.model == "openai/gpt-oss-120b" and first.model_version == "gpt-oss-120b"
    assert first.tokens == 50 and first.attempts == 1 and first.scores is not None
    second = await r.judge(rep())
    assert second.status == "ok" and second.cached is True and second.attempts == 0
    assert second.scores == first.scores
    assert len(fake.requests) == 1


async def test_force_bypasses_cache(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    r = runner(tmp_path, fake)
    await r.judge(rep())
    again = await r.judge(rep(), force=True)
    assert again.cached is False and len(fake.requests) == 2


async def test_corrupt_cache_is_a_miss(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    r = runner(tmp_path, fake)
    await r.judge(rep())
    for f in (tmp_path / "judge cache").glob("*.json"):
        f.write_text("{broken", encoding="utf-8")
    again = await r.judge(rep())
    assert again.status == "ok" and again.cached is False


async def test_invalid_json_retries_then_judge_error(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok("sure! here is prose"))
    out = await runner(tmp_path, fake).judge(rep())
    assert out.status == "judge_error" and out.attempts == 4 and len(fake.requests) == 4
    assert out.reason is not None and "invalid reply after 4 attempts" in out.reason


async def test_truncated_reply_retries_then_succeeds(tmp_path: Path) -> None:
    replies = [httpx.Response(200, json=groq_body(finish="length")), groq_ok()]
    out = await runner(tmp_path, Fake(lambda r: replies.pop(0))).judge(rep())
    assert out.status == "ok" and out.attempts == 2


async def test_groq_down_no_gemini_key(tmp_path: Path) -> None:
    fake = Fake(lambda r: httpx.Response(500, text="boom"))
    out = await runner(tmp_path, fake).judge(rep())
    assert out.status == "judge_error"
    assert out.reason is not None
    assert "groq: HTTP 500" in out.reason and "gemini: no key" in out.reason
    assert len(fake.requests) == 1


async def test_timeout_ends_provider(tmp_path: Path) -> None:
    def h(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=r)

    out = await runner(tmp_path, Fake(h)).judge(rep())
    assert out.status == "judge_error" and out.reason is not None
    assert "groq: timeout" in out.reason


async def test_groq_rate_limited_falls_back_to_gemini(tmp_path: Path) -> None:
    def h(r: httpx.Request) -> httpx.Response:
        if r.url.host == "api.groq.com":
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return gem_ok()

    r, fake = both(tmp_path, h)
    out = await r.judge(rep())
    assert out.status == "ok" and out.provider == "gemini" and out.model_version == "gemini-v"
    assert out.tokens == 40
    assert fake.hosts() == ["api.groq.com", "generativelanguage.googleapis.com"]


async def test_all_rate_limited(tmp_path: Path) -> None:
    r, _ = both(tmp_path, lambda q: httpx.Response(429, headers={"Retry-After": "3600"}))
    out = await r.judge(rep())
    assert out.status == "rate_limited" and out.reason is not None
    assert "groq: rate limited" in out.reason and "gemini: rate limited" in out.reason


async def test_no_keys_skipped(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    out = await runner(tmp_path, fake, {}).judge(rep())
    assert out.status == "skipped" and out.reason is not None
    assert "no judge API key" in out.reason and fake.requests == []


async def test_nothing_to_judge(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    out = await runner(tmp_path, fake).judge(report(not_reached(1)))
    assert out.status == "skipped" and out.reason == "nothing to judge"
    assert fake.requests == []


async def test_payment_required_disables_provider(tmp_path: Path) -> None:
    fake = Fake(lambda r: httpx.Response(402, text="pay"))
    r = runner(tmp_path, fake)
    first = await r.judge(rep("one"))
    assert first.status == "judge_error" and first.reason is not None
    assert "groq: " in first.reason and "402" in first.reason
    await r.judge(rep("two"))
    assert len(fake.requests) == 1


async def test_error_text_scrubs_keys(tmp_path: Path) -> None:
    r, _ = both(tmp_path, lambda q: httpx.Response(401, text=f"bad key {GROQ_KEY} {GEM_KEY}"))
    out = await r.judge(rep())
    assert out.reason is not None
    assert "***" in out.reason and GROQ_KEY not in out.reason and GEM_KEY not in out.reason
    assert len(out.reason) <= 500


async def test_real_runner_refuses(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    out = await runner(tmp_path, fake, real=True).judge(rep())
    assert out.status == "judge_error" and out.reason is not None
    assert "real data refused" in out.reason and fake.requests == []


async def test_daily_counter_shared_across_runs(tmp_path: Path) -> None:
    base = load_config()
    groq = base.providers[0]
    one = ProviderConfig(
        name=groq.name,
        model=groq.model,
        key_env=groq.key_env,
        url=groq.url,
        rpm=groq.rpm,
        rpd=1,
        params=groq.params,
    )
    cfg = JudgeConfig(prompt_version=base.prompt_version, providers=(one,))
    fake = Fake(lambda r: groq_ok())
    r = runner(tmp_path, fake, cfg=cfg)
    assert (await r.judge(rep("a"))).status == "ok"
    out = await r.judge(rep("b"))
    assert out.status == "rate_limited" and len(fake.requests) == 1

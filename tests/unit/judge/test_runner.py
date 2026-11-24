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


def _no_run_of(key: str, text: str, n: int = 8) -> bool:
    return not any(key[i : i + n] in text for i in range(len(key) - n + 1))


async def _reason_for_body(tmp_path: Path, key: str, body: str) -> str:
    fake = Fake(lambda r: httpx.Response(401, text=body))
    out = await runner(tmp_path, fake, {"GROQ_API_KEY": key}).judge(rep())
    assert out.reason is not None
    return out.reason


async def test_key_straddling_the_body_cut_is_scrubbed(tmp_path: Path) -> None:
    key = "groq-test-key-alpha-bravo-charlie"
    for pad in (170, 185, 190, 195, 199):
        reason = await _reason_for_body(tmp_path, key, "x" * pad + key + " tail")
        assert _no_run_of(key, reason), reason


async def test_key_split_by_newline_is_scrubbed(tmp_path: Path) -> None:
    key = "groq-test-key-alpha-bravo-charlie"
    reason = await _reason_for_body(tmp_path, key, "bad " + key[:12] + "\n" + key[12:])
    assert _no_run_of(key, reason), reason


async def test_url_encoded_key_is_scrubbed(tmp_path: Path) -> None:
    key = "groq test/key+alpha bravo"
    reason = await _reason_for_body(tmp_path, key, "bad key groq%20test%2Fkey%2Balpha%20bravo")
    assert "alpha" not in reason and "%2F" not in reason, reason


async def test_validation_failure_names_the_field(tmp_path: Path) -> None:
    bad = json.dumps({**GOOD, "understanding": 6})
    fake = Fake(lambda r: groq_ok(bad))
    out = await runner(tmp_path, fake).judge(rep())
    assert out.status == "judge_error" and out.attempts == 4 and out.reason is not None
    assert "invalid reply after 4 attempts: understanding: " in out.reason
    assert "less than or equal to 5" in out.reason


async def test_rate_limit_fallback_never_sleeps_long(tmp_path: Path) -> None:
    sleeps: list[float] = []

    async def rec(s: float) -> None:
        sleeps.append(s)

    def h(r: httpx.Request) -> httpx.Response:
        if r.url.host == "api.groq.com":
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return gem_ok()

    fake = Fake(h)
    r = JudgeRunner(
        load_config(),
        {"GROQ_API_KEY": GROQ_KEY, "GEMINI_API_KEY": GEM_KEY},
        cache_dir=tmp_path / "judge cache",
        quota_dir=tmp_path / "quota dir",
        transport=fake.transport,
        sleep=rec,
    )
    assert (await r.judge(rep())).provider == "gemini"
    assert all(s < 60 for s in sleeps), sleeps


def _barge(result: str) -> object:
    from parakh.report.model import BargeInReport

    return BargeInReport.model_validate(
        {
            "after_agent_ms": 1200.0,
            "onset_ms": 1300.0,
            "stop_latency_ms": None,
            "result": result,
            "via": None,
        }
    )


async def test_agent_finished_first_does_not_require_interruption_score(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())  # GOOD has interruption_handling null
    rpt = report(turn(1, barge_in=_barge("agent_finished_first")))  # type: ignore[arg-type]
    out = await runner(tmp_path, fake).judge(rpt)
    assert out.status == "ok" and out.scores is not None
    assert out.scores.interruption_handling is None


async def test_yielded_barge_in_still_requires_interruption_score(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    rpt = report(turn(1, barge_in=_barge("yielded")))  # type: ignore[arg-type]
    out = await runner(tmp_path, fake).judge(rpt)
    assert out.status == "judge_error" and len(fake.requests) == 4


async def test_json_validate_failed_400_is_retried(tmp_path: Path) -> None:
    bad = httpx.Response(400, json={"error": {"code": "json_validate_failed", "message": "x"}})
    replies = [bad, groq_ok()]
    out = await runner(tmp_path, Fake(lambda r: replies.pop(0))).judge(rep())
    assert out.status == "ok" and out.attempts == 2


async def test_json_validate_failed_400_gives_up_after_four(tmp_path: Path) -> None:
    bad = httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
    fake = Fake(lambda r: bad)
    out = await runner(tmp_path, fake).judge(rep())
    assert out.status == "judge_error" and len(fake.requests) == 4


async def test_other_400_still_ends_provider(tmp_path: Path) -> None:
    fake = Fake(lambda r: httpx.Response(400, json={"error": {"code": "invalid_request"}}))
    out = await runner(tmp_path, fake).judge(rep())
    assert out.status == "judge_error" and len(fake.requests) == 1
    assert out.reason is not None and "HTTP 400" in out.reason


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _with_limits(tpm: int | None, tpd: int | None, *, gemini: bool = False) -> JudgeConfig:
    base = load_config()
    groq = base.providers[0]
    one = ProviderConfig(
        name=groq.name,
        model=groq.model,
        key_env=groq.key_env,
        url=groq.url,
        rpm=groq.rpm,
        rpd=groq.rpd,
        params=groq.params,
        tpm=tpm,
        tpd=tpd,
    )
    rest = base.providers[1:] if gemini else ()
    return JudgeConfig(prompt_version=base.prompt_version, providers=(one, *rest))


async def test_tpm_paces_large_calls(tmp_path: Path) -> None:
    clock = _Clock()
    fake = Fake(lambda r: groq_ok())
    r = JudgeRunner(
        _with_limits(3000, None),
        {"GROQ_API_KEY": GROQ_KEY},
        cache_dir=tmp_path / "judge cache",
        quota_dir=tmp_path / "quota dir",
        transport=fake.transport,
        sleep=clock.sleep,
        clock=clock,
    )
    long_text = "word " * 600  # about 1000 tokens of prompt plus 600 overhead per call
    assert (await r.judge(rep(long_text))).status == "ok"
    assert clock.slept == []
    assert (await r.judge(rep(long_text + "x"))).status == "ok"
    assert len(clock.slept) == 1 and clock.slept[0] > 0


async def test_daily_token_limit_ends_provider(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.groq.com":
            body = groq_body()
            body["usage"] = {"total_tokens": 1200}
            return httpx.Response(200, json=body)
        return gem_ok()

    fake = Fake(handler)
    keys = {"GROQ_API_KEY": GROQ_KEY, "GEMINI_API_KEY": GEM_KEY}
    r = JudgeRunner(
        _with_limits(None, 1500, gemini=True),
        keys,
        cache_dir=tmp_path / "judge cache",
        quota_dir=tmp_path / "quota dir",
        transport=fake.transport,
        sleep=_nosleep,
    )
    assert (await r.judge(rep("a"))).provider == "groq"
    second = await r.judge(rep("b"))
    assert second.status == "ok" and second.provider == "gemini"
    assert fake.hosts().count("api.groq.com") == 1
    only = JudgeRunner(
        _with_limits(None, 1500),
        {"GROQ_API_KEY": GROQ_KEY},
        cache_dir=tmp_path / "judge cache 2",
        quota_dir=tmp_path / "quota dir",
        transport=fake.transport,
        sleep=_nosleep,
    )
    out = await only.judge(rep("c"))
    assert out.status == "rate_limited"
    assert out.reason is not None and "daily token limit reached" in out.reason


async def test_real_audio_report_is_skipped_before_cache_and_requests(tmp_path: Path) -> None:
    fake = Fake(lambda r: groq_ok())
    r = runner(tmp_path, fake)
    await r.judge(rep())  # warms the cache for the same payload
    assert len(fake.requests) == 1
    real = rep().model_copy(update={"real_audio": True})
    out = await r.judge(real)
    assert out.status == "skipped" and out.reason == "real recording (D20)"
    assert out.cached is False and out.attempts == 0
    forced = await r.judge(real, force=True)
    assert forced.status == "skipped"
    assert len(fake.requests) == 1

import json
from importlib.resources import files

import httpx
import pytest

from parakh.judge.providers import ProviderConfig, build_request, load_config, parse_reply


def _cfg(name: str) -> ProviderConfig:
    return next(p for p in load_config().providers if p.name == name)


def test_config_loads_and_ships_in_wheel() -> None:
    assert files("parakh.judge").joinpath("judge.yaml").is_file()
    cfg = load_config()
    assert cfg.prompt_version == "judge-v1"
    assert [p.name for p in cfg.providers] == ["groq", "gemini"]
    assert cfg.providers[0].rpd == 1000 and cfg.providers[1].rpd == 20


def test_groq_request_shape() -> None:
    req = build_request(_cfg("groq"), "groq-test-key", "SYS", "USER")
    body = json.loads(req.content)
    assert req.headers["Authorization"] == "Bearer groq-test-key"
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


def test_gemini_key_in_header_not_url() -> None:
    req = build_request(_cfg("gemini"), "gem-test-key", "SYS", "USER")
    body = json.loads(req.content)
    assert req.headers["x-goog-api-key"] == "gem-test-key"
    assert "gem-test-key" not in str(req.url)
    assert "gemini-flash-lite-latest:generateContent" in str(req.url)
    assert body["systemInstruction"] == {"parts": [{"text": "SYS"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "USER"}]}]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0


def test_parse_reply_groq_and_gemini() -> None:
    groq = httpx.Response(
        200,
        json={
            "model": "gpt-oss-120b-v2",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}],
            "usage": {"total_tokens": 321},
        },
    )
    r = parse_reply(_cfg("groq"), groq)
    assert (r.text, r.model_version, r.tokens, r.truncated) == ("{}", "gpt-oss-120b-v2", 321, True)
    gem = httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": "{"}, {"text": "}"}]}, "finishReason": "STOP"}
            ],
            "modelVersion": "gemini-x-001",
            "usageMetadata": {"totalTokenCount": 77},
        },
    )
    r = parse_reply(_cfg("gemini"), gem)
    assert (r.text, r.model_version, r.tokens, r.truncated) == ("{}", "gemini-x-001", 77, False)


def test_parse_reply_malformed_is_value_error() -> None:
    for cfg in (_cfg("groq"), _cfg("gemini")):
        with pytest.raises(ValueError):
            parse_reply(cfg, httpx.Response(200, json={"oops": 1}))
        with pytest.raises(ValueError):
            parse_reply(cfg, httpx.Response(200, content=b"not json"))

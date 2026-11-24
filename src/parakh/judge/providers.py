"""Provider config, request building and reply parsing for Groq and Gemini."""

from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any, Literal

import httpx
import yaml


@dataclass(frozen=True)
class ProviderConfig:
    name: Literal["groq", "gemini"]
    model: str
    key_env: str
    url: str
    rpm: int
    rpd: int
    params: dict[str, Any]
    tpm: int | None = None
    tpd: int | None = None


@dataclass(frozen=True)
class JudgeConfig:
    prompt_version: str
    providers: tuple[ProviderConfig, ...]


@dataclass(frozen=True)
class Reply:
    text: str
    model_version: str | None
    tokens: int | None
    truncated: bool


@cache
def load_config() -> JudgeConfig:
    text = files("parakh.judge").joinpath("judge.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    return JudgeConfig(
        prompt_version=raw["prompt_version"],
        providers=tuple(ProviderConfig(**p) for p in raw["providers"]),
    )


def build_request(cfg: ProviderConfig, key: str, system: str, user: str) -> httpx.Request:
    if cfg.name == "groq":
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **cfg.params,
        }
        headers = {"Authorization": f"Bearer {key}"}
    else:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": dict(cfg.params),
        }
        headers = {"x-goog-api-key": key}
    return httpx.Request("POST", cfg.url.format(model=cfg.model), headers=headers, json=body)


def _tokens(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_reply(cfg: ProviderConfig, resp: httpx.Response) -> Reply:
    """Pull text, model version, tokens and truncation out of a 2xx reply; ValueError if odd."""
    try:
        data = resp.json()
        if cfg.name == "groq":
            choice = data["choices"][0]
            return Reply(
                text=str(choice["message"]["content"]),
                model_version=data.get("model"),
                tokens=_tokens(data.get("usage", {}).get("total_tokens")),
                truncated=choice.get("finish_reason") == "length",
            )
        cand = data["candidates"][0]
        text = "".join(str(p.get("text", "")) for p in cand["content"]["parts"])
        return Reply(
            text=text,
            model_version=data.get("modelVersion"),
            tokens=_tokens(data.get("usageMetadata", {}).get("totalTokenCount")),
            truncated=cand.get("finishReason") == "MAX_TOKENS",
        )
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ValueError(f"unexpected {cfg.name} reply shape: {type(exc).__name__}") from exc

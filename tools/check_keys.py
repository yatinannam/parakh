"""Check that the API keys in .env work, without sending any data.

Usage: python -m tools.check_keys [--env PATH]
Only lists models; no prompts or audio are sent. Keys are never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import dotenv_values

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
WHISPER_MODEL = "whisper-large-v3-turbo"
TIMEOUT_S = 10.0


@dataclass
class KeyCheck:
    ok: bool
    detail: str
    models: list[str] = field(default_factory=list)


def check_groq(api_key: str, client: httpx.Client) -> KeyCheck:
    """List Groq models with the given key. Details never include the key."""
    if not api_key.isascii():
        return KeyCheck(ok=False, detail="key contains non-ASCII characters; re-copy it")
    try:
        resp = client.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        return KeyCheck(ok=False, detail=f"request failed: {type(exc).__name__}")
    if resp.status_code != 200:
        return KeyCheck(ok=False, detail=f"HTTP {resp.status_code}")
    try:
        models = sorted(m["id"] for m in resp.json()["data"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return KeyCheck(ok=False, detail="HTTP 200 but unexpected response body")
    return KeyCheck(ok=True, detail="HTTP 200", models=models)


class EnvFileError(Exception):
    """The .env file exists but cannot be read as UTF-8 text."""


def _read_key(env_path: Path, name: str) -> str:
    try:
        values = dotenv_values(env_path, encoding="utf-8") if env_path.is_file() else {}
    except UnicodeDecodeError as exc:
        raise EnvFileError(f"{env_path} is not UTF-8 text; save it as UTF-8") from exc
    return (values.get(name) or os.environ.get(name) or "").strip()


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.check_keys")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        key = _read_key(args.env, "GROQ_API_KEY")
        gemini = _read_key(args.env, "GEMINI_API_KEY")
    except EnvFileError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not key:
        print(f"GROQ_API_KEY not set (looked in {args.env} and the environment)", file=sys.stderr)
        return 2

    own_client = client is None
    http = client if client is not None else httpx.Client()
    try:
        result = check_groq(key, http)
    finally:
        if own_client:
            http.close()

    if not result.ok:
        print(f"groq: FAILED ({result.detail})", file=sys.stderr)
        return 1
    has_whisper = "yes" if WHISPER_MODEL in result.models else "no"
    print(f"groq: ok ({len(result.models)} models; {WHISPER_MODEL}: {has_whisper})")
    # Only whether it is set, never the value. The judge falls back to it, so it is optional.
    print(f"gemini: {'set' if gemini else 'not set (optional)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

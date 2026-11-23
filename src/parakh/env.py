"""Load .env and read the judge keys. Keys stay in the environment; nothing here prints them."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from parakh.judge.providers import JudgeConfig


def load_env() -> None:
    """Load .env from the working directory without overriding variables already set."""
    path = Path.cwd() / ".env"
    if not path.is_file():
        return
    try:
        load_dotenv(path, override=False, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # Name the file and the error type only: never its content or the exception text.
        reason = "not UTF-8" if isinstance(exc, UnicodeDecodeError) else type(exc).__name__
        print(
            f"warning: could not read .env ({path}): {reason}; judge keys not loaded",
            file=sys.stderr,
        )


def judge_keys(config: JudgeConfig) -> dict[str, str]:
    """{key_env: value} for each provider key that is set and not empty."""
    keys: dict[str, str] = {}
    for provider in config.providers:
        value = os.environ.get(provider.key_env, "").strip()
        if value:
            keys[provider.key_env] = value
    return keys

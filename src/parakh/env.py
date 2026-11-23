"""Load .env and read the judge keys. Keys stay in the environment; nothing here prints them."""

import os
from pathlib import Path

from dotenv import load_dotenv

from parakh.judge.providers import JudgeConfig


def load_env() -> None:
    """Load .env from the working directory without overriding variables already set."""
    path = Path.cwd() / ".env"
    if path.is_file():
        load_dotenv(path, override=False)


def judge_keys(config: JudgeConfig) -> dict[str, str]:
    """{key_env: value} for each provider key that is set and not empty."""
    keys: dict[str, str] = {}
    for provider in config.providers:
        value = os.environ.get(provider.key_env, "").strip()
        if value:
            keys[provider.key_env] = value
    return keys

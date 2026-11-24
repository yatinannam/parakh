"""Agent configuration. Model ids live only in config.yaml."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_PATH = Path(__file__).parent / "config.yaml"


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stt_language: str
    tts_voice: str


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stt_model: str
    local_stt_model: str
    stt_language: str
    llm_model: str
    tts_voice: str
    sample_rate: int
    clock: str
    profiles: dict[str, Profile]
    default_profile: str
    profile: str


def load_config(path: Path = DEFAULT_PATH, profile: str | None = None) -> AgentConfig:
    """Load the config; the chosen profile fills stt_language and tts_voice."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    profiles = data["profiles"]
    key = profile if profile is not None else data["default_profile"]
    if key not in profiles:
        raise ValueError(f"unknown profile {key!r}; valid profiles: {', '.join(profiles)}")
    data["profile"] = key
    data["stt_language"] = profiles[key]["stt_language"]
    data["tts_voice"] = profiles[key]["tts_voice"]
    return AgentConfig.model_validate(data)


def verify_models(available: set[str], config: AgentConfig, stt_mode: str = "groq") -> None:
    """Raise RuntimeError naming each configured model id the provider does not list.

    The local STT runs on this machine, so only the LLM is checked in that mode.
    """
    wanted = [config.llm_model] if stt_mode == "local" else [config.stt_model, config.llm_model]
    missing = [m for m in wanted if m not in available]
    if missing:
        raise RuntimeError(
            "Configured models not available on Groq: "
            + ", ".join(missing)
            + ". Edit agents/clinic_agent/config.yaml."
        )

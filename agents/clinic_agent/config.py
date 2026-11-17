"""Agent configuration. Model ids live only in config.yaml."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_PATH = Path(__file__).parent / "config.yaml"


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stt_model: str
    stt_language: str
    llm_model: str
    tts_voice: str
    sample_rate: int
    clock: str


def load_config(path: Path = DEFAULT_PATH) -> AgentConfig:
    return AgentConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def verify_models(available: set[str], config: AgentConfig) -> None:
    """Raise RuntimeError naming each configured model id the provider does not list."""
    missing = [m for m in (config.stt_model, config.llm_model) if m not in available]
    if missing:
        raise RuntimeError(
            "Configured models not available on Groq: "
            + ", ".join(missing)
            + ". Edit agents/clinic_agent/config.yaml."
        )

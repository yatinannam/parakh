"""Scenario model and YAML loader."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ScenarioError(ValueError):
    """Raised when a scenario file cannot be read or fails validation."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallerVoice(_Strict):
    voice: str
    rate: str = "+0%"
    pitch: str = "+0Hz"


class BargeIn(_Strict):
    after_agent_ms: int = Field(ge=0)


class Turn(_Strict):
    say: str
    ref: str | None = None
    barge_in: BargeIn | None = None

    @property
    def reference(self) -> str:
        """Reference text for WER: `ref` when given, else `say`."""
        return self.ref if self.ref is not None else self.say


class Limits(_Strict):
    # max_turns 0 would play no turn and still report completed (a false pass).
    max_turns: int = Field(default=12, ge=1)
    response_timeout_s: float = Field(default=8.0, gt=0, allow_inf_nan=False)
    call_timeout_s: float = Field(default=180.0, gt=0, allow_inf_nan=False)


class Scenario(_Strict):
    schema_version: Literal[1]
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str
    language: Literal["hi-en", "kn-en", "ta-en", "en", "hi"]
    domain: str
    clock: datetime
    agent_speaks_first: bool = True
    caller: CallerVoice
    hms_seed: str | None = None
    turns: list[Turn] = Field(min_length=1)
    expect: dict[str, Any] | None = None
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def _first_turn_barge_in_needs_agent_first(self) -> Scenario:
        if not self.agent_speaks_first and self.turns[0].barge_in is not None:
            raise ValueError("barge_in on the first turn needs agent_speaks_first: true")
        return self

    @field_validator("clock")
    @classmethod
    def _clock_has_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("clock must include a timezone offset, e.g. +05:30")
        return v


def load_scenario(path: Path) -> Scenario:
    """Load and validate a scenario YAML file."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ScenarioError(f"{path}: cannot read file: {e}") from e
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScenarioError(f"{path}: file is not valid UTF-8: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ScenarioError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ScenarioError(f"{path}: top level must be a mapping")
    try:
        return Scenario.model_validate(data)
    except ValidationError as e:
        lines = [f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise ScenarioError(f"{path}:\n" + "\n".join(lines)) from e

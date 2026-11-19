"""The packaged degradation presets and babble talkers."""

from functools import cache
from importlib.resources import files
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoiseSpec(_Model):
    kind: Literal["white", "pink", "brown", "babble"]
    snr_db: float


class LossSpec(_Model):
    rate: float = Field(gt=0, le=0.5)
    mean_burst_frames: float | None = Field(default=None, gt=1)
    conceal: Literal["zero", "repeat"] = "zero"


class Preset(_Model):
    name: str
    telephone: bool = False
    noise: NoiseSpec | None = None
    loss: LossSpec | None = None
    clip_dbfs: float | None = Field(default=None, lt=0)


class Talker(_Model):
    voice: str
    text: str
    rate: str = "+0%"


@cache
def _raw() -> dict[str, Any]:
    text = files("parakh.degrade").joinpath("presets.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def load_presets() -> dict[str, Preset]:
    """The five presets, keyed by name, in file order."""
    presets = [Preset.model_validate(p) for p in _raw()["presets"]]
    return {p.name: p for p in presets}


PRESET_ORDER: tuple[str, ...] = tuple(load_presets())


def get_preset(name: str) -> Preset:
    presets = load_presets()
    if name not in presets:
        raise ValueError(f"unknown preset '{name}'; available: {', '.join(PRESET_ORDER)}")
    return presets[name]


def load_talkers() -> list[Talker]:
    """The babble talkers."""
    return [Talker.model_validate(t) for t in _raw()["babble"]["talkers"]]

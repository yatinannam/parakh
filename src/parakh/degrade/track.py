"""The per-call noise track."""

from parakh.audio import SAMPLE_RATE
from parakh.degrade.babble import build_babble
from parakh.degrade.filters import F64
from parakh.degrade.noise import brown, pink, white
from parakh.degrade.presets import Preset
from parakh.degrade.seeds import part_rng
from parakh.tts.cache import TTSCache
from parakh.tts.engine import TTSEngine

NOISE_TRACK_S = 30.0


async def noise_track(preset: Preset, seed: int, cache: TTSCache, engine: TTSEngine) -> F64 | None:
    """Unit-RMS noise at 16 kHz for the preset, or None when it has no noise."""
    if preset.noise is None:
        return None
    rng = part_rng(seed, "noise")
    n = round(NOISE_TRACK_S * SAMPLE_RATE)
    match preset.noise.kind:
        case "white":
            return white(n, rng)
        case "pink":
            return pink(n, rng)
        case "brown":
            return brown(n, rng)
        case "babble":
            return await build_babble(cache, engine, NOISE_TRACK_S, rng)

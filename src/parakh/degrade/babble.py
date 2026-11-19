"""Babble noise built from Parakh's own TTS talkers."""

import numpy as np

from parakh.audio import SAMPLE_RATE, read_wav
from parakh.degrade.filters import F64
from parakh.degrade.noise import DegradeError, _unit_rms
from parakh.degrade.presets import load_talkers
from parakh.tts.cache import TTSCache
from parakh.tts.engine import TTSEngine

_PITCH = "+0Hz"


async def build_babble(
    cache: TTSCache, engine: TTSEngine, seconds: float, rng: np.random.Generator
) -> F64:
    """Sum the talkers, each looped from a random start, at unit RMS (16 kHz)."""
    n = round(seconds * SAMPLE_RATE)
    total = np.zeros(n)
    used = 0
    for index, talker in enumerate(load_talkers()):
        clip, _built = await cache.get(
            engine, talker.voice, talker.rate, _PITCH, talker.text, index
        )
        pcm, _rate = read_wav(clip.path)
        if len(pcm) == 0:
            continue
        start = int(rng.integers(len(pcm)))
        total += pcm.astype(np.float64)[(start + np.arange(n)) % len(pcm)]
        used += 1
    if used == 0:
        raise DegradeError("babble talkers produced no audio")
    out = _unit_rms(total)
    if not np.any(out):
        raise DegradeError("babble talkers produced no audio")
    return out

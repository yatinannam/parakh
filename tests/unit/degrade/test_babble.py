import math

import numpy as np

from parakh.degrade.babble import build_babble
from parakh.degrade.presets import get_preset
from parakh.degrade.track import NOISE_TRACK_S, noise_track
from parakh.tts.cache import TTSCache
from tests.fakes import FakeEngine

RATE = 16000


async def test_babble_is_deterministic_and_unit_rms(tmp_path):
    cache = TTSCache(tmp_path / "dir with space")
    engine = FakeEngine()
    first = await build_babble(cache, engine, 2.0, np.random.default_rng(5))
    assert engine.calls == 6
    second = await build_babble(cache, engine, 2.0, np.random.default_rng(5))
    assert engine.calls == 6
    assert len(first) == 2 * RATE
    np.testing.assert_array_equal(first, second)
    assert abs(math.sqrt(float(np.mean(first**2))) - 1.0) < 1e-6


async def test_noise_track_kinds(tmp_path):
    cache = TTSCache(tmp_path / "dir with space")
    engine = FakeEngine()
    assert await noise_track(get_preset("clean"), 1, cache, engine) is None
    pink = await noise_track(get_preset("bad_line"), 1, cache, engine)
    assert pink is not None
    assert len(pink) == round(NOISE_TRACK_S * RATE)
    assert engine.calls == 0
    babble = await noise_track(get_preset("phone_noisy"), 1, cache, engine)
    assert babble is not None
    assert len(babble) == round(NOISE_TRACK_S * RATE)
    assert engine.calls == 6

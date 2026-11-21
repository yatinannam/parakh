import math

import numpy as np
import pytest

from parakh.audio import PCM, resample, speech_end_ms
from parakh.degrade.chain import degrade
from parakh.degrade.filters import peak_normalise
from parakh.degrade.noise import noise_scale, pink
from parakh.degrade.presets import get_preset
from parakh.degrade.seeds import call_seed, part_rng

RATE = 16000


def _clip() -> PCM:
    t = np.arange(int(0.5 * RATE)) / RATE
    tone = 8000 * np.sin(2 * np.pi * 1000 * t)
    gap = np.zeros(int(0.3 * RATE))
    return np.concatenate([tone, gap, tone[: int(0.2 * RATE)]]).astype(np.int16)


def _noise(pcm: PCM, snr_db: float, seed: int = 0) -> np.ndarray:
    n = pink(len(pcm), np.random.default_rng(seed))
    return n * noise_scale([peak_normalise(pcm.astype(np.float64))], n, RATE, snr_db)


def test_clean_is_resample_only() -> None:
    pcm = _clip()
    out = degrade(pcm, RATE, get_preset("clean"), out_rate=16000, noise=None, rng=part_rng(1, "a"))
    assert np.array_equal(out.pcm, pcm)
    assert out.stats is None and not any(out.lost)
    out8 = degrade(pcm, RATE, get_preset("clean"), out_rate=8000, noise=None, rng=part_rng(1, "a"))
    assert np.array_equal(out8.pcm, resample(pcm, RATE, 8000))
    assert len(out8.lost) == math.ceil(len(out8.pcm) / 160)


def test_same_seed_same_bytes() -> None:
    pcm = _clip()
    preset = get_preset("bad_line")
    noise = _noise(pcm, 5.0)
    a = degrade(pcm, RATE, preset, out_rate=8000, noise=noise, rng=part_rng(7, "turn-0"))
    b = degrade(pcm, RATE, preset, out_rate=8000, noise=noise, rng=part_rng(7, "turn-0"))
    c = degrade(pcm, RATE, preset, out_rate=8000, noise=noise, rng=part_rng(7, "turn-1"))
    assert a.pcm.tobytes() == b.pcm.tobytes()
    assert a.lost == b.lost
    assert a.pcm.tobytes() != c.pcm.tobytes()


@pytest.mark.parametrize("out_rate", [8000, 16000, 24000])
def test_phone_keeps_length_and_timing(out_rate: int) -> None:
    pcm = _clip()
    out = degrade(
        pcm, RATE, get_preset("phone"), out_rate=out_rate, noise=None, rng=part_rng(1, "a")
    )
    assert len(out.pcm) == round(len(pcm) * out_rate / RATE)
    assert len(out.lost) == math.ceil(len(pcm) / RATE / 0.020)
    assert out.stats is not None and out.stats.frames == len(out.lost)
    assert abs(speech_end_ms(out.pcm, out_rate) - speech_end_ms(pcm, RATE)) <= 20


def test_lost_frames_are_zero_at_8khz() -> None:
    pcm = _clip()
    out = degrade(
        pcm, RATE, get_preset("phone_lossy"), out_rate=8000, noise=None, rng=part_rng(3, "a")
    )
    assert any(out.lost)
    assert out.stats is not None and out.stats.lost_frames == sum(out.lost)
    for i, lost in enumerate(out.lost):
        if lost:
            assert not out.pcm[i * 160 : (i + 1) * 160].any()


def test_bad_line_counts_clipping() -> None:
    pcm = _clip()
    out = degrade(
        pcm,
        RATE,
        get_preset("bad_line"),
        out_rate=8000,
        noise=_noise(pcm, 5.0),
        rng=part_rng(1, "a"),
    )
    assert out.stats is not None
    assert out.stats.clipped_samples > 0
    assert out.stats.snr_db == pytest.approx(5.0, abs=0.5)


def test_noise_preset_needs_noise() -> None:
    from parakh.degrade.noise import DegradeError

    with pytest.raises(DegradeError):
        degrade(
            _clip(), RATE, get_preset("bad_line"), out_rate=8000, noise=None, rng=part_rng(1, "a")
        )


def test_silent_clip_has_null_snr() -> None:
    pcm = np.zeros(RATE // 2, dtype=np.int16)
    noise = pink(len(pcm), np.random.default_rng(1)) * 100.0
    out = degrade(
        pcm, RATE, get_preset("phone_noisy"), out_rate=8000, noise=noise, rng=part_rng(1, "a")
    )
    assert out.stats is not None and out.stats.snr_db is None


@pytest.mark.parametrize("name", ["phone", "phone_noisy", "clean"])
def test_empty_clip_degrades_to_empty(name: str) -> None:
    pcm = np.zeros(0, dtype=np.int16)
    out = degrade(
        pcm, RATE, get_preset(name), out_rate=8000, noise=np.zeros(0), rng=part_rng(1, "a")
    )
    assert len(out.pcm) == 0 and out.pcm.dtype == np.int16
    assert out.lost == []
    if name == "clean":
        assert out.stats is None
    else:
        assert out.stats is not None and out.stats.frames == 0


def test_call_seed_is_stable() -> None:
    assert call_seed("clinic-book-hinglish-01", "phone") == 1493743292490877660
    assert call_seed("a", "phone") != call_seed("a", "bad_line")


def test_near_silent_clip_is_not_amplified() -> None:
    pcm = np.where(np.arange(RATE) % 2 == 0, 2, -2).astype(np.int16)
    out = degrade(pcm, RATE, get_preset("phone"), out_rate=16000, noise=None, rng=part_rng(1, "a"))
    assert int(np.max(np.abs(out.pcm))) < 100

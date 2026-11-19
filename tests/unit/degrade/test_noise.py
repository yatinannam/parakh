import numpy as np
import pytest
from scipy.signal import welch

from parakh.degrade.noise import (
    DegradeError,
    brown,
    measured_snr_db,
    noise_scale,
    noise_slice,
    pink,
    white,
)

RATE = 16000


def _tone(seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return amp * np.sin(2 * np.pi * 300 * t)


def _speech() -> np.ndarray:
    amp = 32768 * 10 ** (-3 / 20)
    return np.concatenate([_tone(0.5, amp), np.zeros(int(0.3 * RATE)), _tone(0.7, amp)])


@pytest.mark.parametrize(("kind", "slope_db"), [("pink", -3.0), ("brown", -6.0)])
def test_noise_slope_per_octave(kind: str, slope_db: float) -> None:
    gen = {"pink": pink, "brown": brown}[kind]
    x = gen(2**19, np.random.default_rng(1))
    f, p = welch(x, fs=RATE, nperseg=4096)
    sel = (f >= 250) & (f <= 4000)
    slope = np.polyfit(np.log2(f[sel]), 10 * np.log10(p[sel]), 1)[0]
    assert slope == pytest.approx(slope_db, abs=1.0)


def test_noise_unit_rms() -> None:
    for gen in (white, pink, brown):
        x = gen(50_000, np.random.default_rng(2))
        assert float(np.sqrt(np.mean(x**2))) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("snr_db", [5.0, 10.0, 20.0])
def test_snr_within_half_db(snr_db: float) -> None:
    speech = _speech()
    noise = pink(len(speech), np.random.default_rng(3))
    scaled = noise * noise_scale([speech], noise, RATE, snr_db)
    assert measured_snr_db(speech, scaled, RATE) == pytest.approx(snr_db, abs=0.5)


def test_snr_scale_rejects_silence() -> None:
    noise = white(1000, np.random.default_rng(4))
    with pytest.raises(DegradeError, match="no speech"):
        noise_scale([np.zeros(RATE)], noise, RATE, 10.0)


def test_snr_scale_rejects_silent_noise() -> None:
    with pytest.raises(DegradeError, match="zero RMS"):
        noise_scale([_speech()], np.zeros(1000), RATE, 10.0)


def test_measured_snr_none_without_speech() -> None:
    assert measured_snr_db(np.zeros(RATE), np.ones(RATE), RATE) is None


def test_noise_slice_wraps_and_is_seeded() -> None:
    track = np.arange(10, dtype=np.float64)
    a = noise_slice(track, 25, np.random.default_rng(5))
    b = noise_slice(track, 25, np.random.default_rng(5))
    assert len(a) == 25
    assert np.array_equal(a, b)
    assert np.all(np.diff(a) % 10 == 1)
    with pytest.raises(DegradeError):
        noise_slice(np.zeros(0), 5, np.random.default_rng(5))

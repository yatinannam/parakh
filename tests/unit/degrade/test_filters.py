import numpy as np

from parakh.audio import speech_end_ms
from parakh.degrade.filters import (
    F64,
    band_limit,
    hard_clip,
    peak_normalise,
    resample_f,
    telephone,
    to_int16,
)


def _sine(freq: float, rate: int, seconds: float = 1.0, amp: float = 10000.0) -> F64:
    t = np.arange(int(rate * seconds)) / rate
    return amp * np.sin(2 * np.pi * freq * t)


def _rms(x: F64) -> float:
    return float(np.sqrt(np.mean(x**2)))


def _sweep(
    f0: float, f1: float, rate: int, amp: float, seconds: float = 2.0, log: bool = False
) -> F64:
    t = np.arange(int(rate * seconds)) / rate
    if log:
        k = (f1 / f0) ** (1 / seconds)
        phase = 2 * np.pi * f0 * (k**t - 1) / np.log(k)
    else:
        phase = 2 * np.pi * (f0 * t + (f1 - f0) * t**2 / (2 * seconds))
    return amp * np.sin(phase)


def _db(ratio: float) -> float:
    return float(20 * np.log10(ratio))


def test_band_limit_passes_voice_band() -> None:
    mid = (slice(2000, -2000),)
    x = _sine(1000, 16000)
    assert _db(_rms(band_limit(x, 16000)[mid]) / _rms(x[mid])) > -1.0
    x = _sine(100, 16000)
    assert _db(_rms(x[mid]) / _rms(band_limit(x, 16000)[mid])) >= 20.0
    x = _sine(6000, 16000)
    assert _db(_rms(x[mid]) / _rms(band_limit(x, 16000)[mid])) >= 40.0


def test_band_limit_keeps_timing() -> None:
    # Silence on both sides, so the speech end is not the array end.
    tone = _sine(1000, 16000, 0.4, 8000.0)
    x = np.concatenate([np.zeros(3200), tone, np.zeros(3200)])
    y = np.round(band_limit(x, 16000)).astype(np.int16)
    ref = np.round(x).astype(np.int16)
    assert abs(speech_end_ms(y, 16000) - speech_end_ms(ref, 16000)) <= 10
    # Speech start: the end of the reversed signal is len - start.
    assert abs(speech_end_ms(y[::-1].copy(), 16000) - speech_end_ms(ref[::-1].copy(), 16000)) <= 10


def test_band_limit_has_zero_lag() -> None:
    # A causal filter delays a burst near the 300 Hz edge by ~19 samples (1.2 ms),
    # too small for the 10 ms speech-end check, so assert the lag directly.
    burst = _sine(400, 16000, 0.2, 8000.0) * np.hanning(3200)
    x = np.concatenate([np.zeros(3200), burst, np.zeros(3200)])
    y = band_limit(x, 16000)
    lag = int(np.argmax(np.correlate(y, x, "full"))) - (len(x) - 1)
    assert lag == 0


def test_telephone_suppresses_aliasing() -> None:
    x = _sweep(5000, 7500, 16000, 10000.0)
    y, _ = telephone(x, 16000)
    assert _db(_rms(x) / max(_rms(y), 1e-9)) >= 50.0


def test_telephone_output_has_no_energy_above_4khz() -> None:
    x = _sweep(100, 7900, 16000, 32768 * 10 ** (-6 / 20), seconds=3.0, log=True)
    y, _ = telephone(x, 16000)
    z = resample_f(y, 8000, 16000)
    power = np.abs(np.fft.rfft(z)) ** 2
    freqs = np.fft.rfftfreq(len(z), 1 / 16000)
    high = power[freqs >= 4000].sum()
    assert 10 * np.log10(high / power.sum()) <= -40.0


def test_resample_f_length() -> None:
    x = np.random.default_rng(0).standard_normal(16001)
    down = resample_f(x, 16000, 8000)
    assert len(down) == round(16001 * 8000 / 16000)
    up = resample_f(down, 8000, 24000)
    assert len(up) == round(len(down) * 24000 / 8000)
    assert resample_f(x, 16000, 16000).shape == x.shape


def test_peak_normalise() -> None:
    x = _sine(500, 16000, amp=1234.0)
    y = peak_normalise(x)
    assert abs(np.max(np.abs(y)) - 32768 * 10 ** (-3 / 20)) < 1.0
    z = np.zeros(100)
    assert np.array_equal(peak_normalise(z), z)


def test_hard_clip_counts() -> None:
    x = np.array([0.0, 100.0, -100.0, 20000.0, -20000.0])
    level = 20 * np.log10(10000.0 / 32768)
    y, n = hard_clip(x, level)
    assert n == 2
    assert np.max(np.abs(y)) <= 10000.0 + 1e-6
    _, none = hard_clip(x[:3], level)
    assert none == 0


def test_to_int16_counts() -> None:
    pcm, n = to_int16(np.array([0.4, 0.6, 40000.0, -40000.0]))
    assert pcm.dtype == np.int16
    assert pcm.tolist() == [0, 1, 32767, -32768]
    assert n == 2


def test_telephone_counts_clipping() -> None:
    _, n = telephone(_sine(1000, 16000, amp=60000.0), 16000)
    assert n > 0

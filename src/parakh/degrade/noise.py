"""Synthetic noise sources and SNR arithmetic.

SNR is `20 * log10(speech_active_rms / noise_rms)`: speech RMS over the 10 ms
windows above -45 dBFS, noise RMS over the whole noise array (the noise is
stationary and plays during speech and gaps alike).
"""

import math
from collections.abc import Sequence

import numpy as np

from parakh.audio import SPEECH_DBFS
from parakh.degrade.filters import F64

_WINDOW_MS = 10
_FULL_SCALE = 32768.0


class DegradeError(ValueError):
    """Degradation cannot proceed (undefined SNR, silent noise)."""


def _rms(x: F64) -> float:
    return math.sqrt(float(np.mean(np.square(x)))) if x.size else 0.0


def _unit_rms(x: F64) -> F64:
    r = _rms(x)
    return x / r if r > 0.0 else x


def white(n: int, rng: np.random.Generator) -> F64:
    """White Gaussian noise at unit RMS."""
    return _unit_rms(rng.standard_normal(n))


def _shaped(n: int, rng: np.random.Generator, exponent: float) -> F64:
    """White noise filtered to power ~ 1/f**exponent, DC removed, unit RMS."""
    if n == 0:
        return np.zeros(0)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spec), dtype=np.float64)
    f[0] = 1.0
    spec = spec / f ** (exponent / 2)
    spec[0] = 0.0
    return _unit_rms(np.fft.irfft(spec, n=n))


def pink(n: int, rng: np.random.Generator) -> F64:
    """Pink noise (1/f power) at unit RMS."""
    return _shaped(n, rng, 1.0)


def brown(n: int, rng: np.random.Generator) -> F64:
    """Brown noise (1/f^2 power) at unit RMS."""
    return _shaped(n, rng, 2.0)


def speech_active_rms(clips: Sequence[F64], rate: int) -> float:
    """RMS over the 10 ms windows above -45 dBFS of all clips together."""
    size = rate * _WINDOW_MS // 1000
    threshold = _FULL_SCALE * 10 ** (SPEECH_DBFS / 20)
    energy = 0.0
    count = 0
    for clip in clips:
        for start in range(0, len(clip), size):
            window = clip[start : start + size]
            if _rms(window) > threshold:
                energy += float(np.sum(np.square(window)))
                count += len(window)
    if count == 0:
        raise DegradeError("no speech above -45 dBFS; SNR is undefined")
    return math.sqrt(energy / count)


def noise_scale(clips: Sequence[F64], noise: F64, rate: int, snr_db: float) -> float:
    """Gain to apply to `noise` so the clips hear it at `snr_db`."""
    noise_rms = _rms(noise)
    if noise_rms == 0.0:
        raise DegradeError("noise has zero RMS; cannot set an SNR")
    return speech_active_rms(clips, rate) / (noise_rms * 10 ** (snr_db / 20))


def measured_snr_db(speech: F64, added_noise: F64, rate: int) -> float | None:
    """SNR of `speech` against `added_noise`; None without speech or noise."""
    noise_rms = _rms(added_noise)
    if noise_rms == 0.0:
        return None
    try:
        speech_rms = speech_active_rms([speech], rate)
    except DegradeError:
        return None
    return 20.0 * math.log10(speech_rms / noise_rms)


def noise_slice(track: F64, n: int, rng: np.random.Generator) -> F64:
    """n samples of `track` from a random start, wrapping around."""
    if track.size == 0:
        raise DegradeError("noise track is empty")
    start = int(rng.integers(len(track)))
    return track[(start + np.arange(n)) % len(track)]

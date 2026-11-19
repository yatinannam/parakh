"""Telephone band filters: band-pass, resampling, normalising, clipping."""

import math

import numpy as np
import numpy.typing as npt
from scipy.signal import butter, resample_poly, sosfiltfilt

from parakh.audio import PCM
from parakh.degrade.mulaw import mulaw_decode, mulaw_encode, mulaw_saturated

F64 = npt.NDArray[np.float64]

TELEPHONE_RATE = 8000
BAND_HZ = (300.0, 3400.0)
PEAK_DBFS = -3.0
_FULL_SCALE = 32768.0
_ORDER = 6


def band_limit(x: F64, rate: int) -> F64:
    """Zero-phase Butterworth band-pass over BAND_HZ.

    No edge padding: odd extension of a loud out-of-band edge leaks a
    transient into the pass band, and speech clips start and end quiet.
    """
    sos = butter(_ORDER, BAND_HZ, btype="bandpass", fs=rate, output="sos")
    return np.asarray(sosfiltfilt(sos, x, padlen=0), dtype=np.float64)


def resample_f(x: F64, src: int, dst: int) -> F64:
    """Polyphase resample in float; output length is round(len * dst / src)."""
    if src == dst:
        return x.copy()
    g = math.gcd(src, dst)
    out = np.asarray(resample_poly(x, dst // g, src // g), dtype=np.float64)
    n = round(len(x) * dst / src)
    if len(out) >= n:
        return out[:n]
    return np.concatenate([out, np.zeros(n - len(out))])


def peak_normalise(x: F64, target_dbfs: float = PEAK_DBFS) -> F64:
    """Scale so the peak sits at target_dbfs; all-zero input is returned unchanged."""
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak == 0.0:
        return x
    return x * (_FULL_SCALE * 10 ** (target_dbfs / 20) / peak)


def hard_clip(x: F64, level_dbfs: float) -> tuple[F64, int]:
    """Clip to +-level_dbfs; return the clipped signal and the clipped count."""
    limit = _FULL_SCALE * 10 ** (level_dbfs / 20)
    return np.clip(x, -limit, limit), int(np.count_nonzero(np.abs(x) > limit))


def to_int16(x: F64) -> tuple[PCM, int]:
    """Round and clip to int16; return the samples and the clipped count."""
    r = np.round(x)
    clipped = int(np.count_nonzero((r > 32767) | (r < -32768)))
    return np.clip(r, -32768, 32767).astype(np.int16), clipped


def telephone(x: F64, rate: int) -> tuple[F64, int]:
    """Band-limit, go to 8 kHz, then mu-law encode and decode.

    Returns the 8 kHz signal and the clipped plus saturated sample count.
    """
    narrow = resample_f(band_limit(x, rate), rate, TELEPHONE_RATE)
    pcm, clipped = to_int16(narrow)
    saturated = mulaw_saturated(pcm)
    return mulaw_decode(mulaw_encode(pcm)).astype(np.float64), clipped + saturated

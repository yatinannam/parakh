"""The degrade chain: normalise, noise, clip, telephone, loss, resample."""

from dataclasses import dataclass

import numpy as np

from parakh.audio import PCM, resample
from parakh.degrade.filters import (
    F64,
    TELEPHONE_RATE,
    hard_clip,
    peak_normalise,
    resample_f,
    telephone,
    to_int16,
)
from parakh.degrade.loss import apply_loss, loss_mask
from parakh.degrade.noise import DegradeError, measured_snr_db
from parakh.degrade.presets import Preset

FRAME_MS = 20


@dataclass(frozen=True)
class DegradeStats:
    snr_db: float | None
    frames: int
    lost_frames: int
    clipped_samples: int


@dataclass(frozen=True)
class Degraded:
    pcm: PCM
    lost: list[bool]
    stats: DegradeStats | None


def _frame_len(rate: int) -> int:
    return max(1, round(rate * FRAME_MS / 1000))


def _n_frames(n: int, rate: int) -> int:
    return -(-n // _frame_len(rate))


def _fit(x: F64, n: int) -> F64:
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros(n - len(x))])


def degrade(
    pcm: PCM,
    rate: int,
    preset: Preset,
    *,
    out_rate: int,
    noise: F64 | None,
    rng: np.random.Generator,
) -> Degraded:
    """Degrade one clip. `noise` is already scaled and as long as `pcm`."""
    if preset.name == "clean":
        out = resample(pcm, rate, out_rate)
        return Degraded(out, [False] * _n_frames(len(out), out_rate), None)
    if len(pcm) == 0:
        return Degraded(np.zeros(0, dtype=np.int16), [], DegradeStats(None, 0, 0, 0))

    speech = peak_normalise(pcm.astype(np.float64))
    x = speech
    snr = None
    if preset.noise is not None:
        if noise is None or len(noise) != len(pcm):
            raise DegradeError("noise preset needs a noise array as long as the clip")
        x = x + noise
        snr = measured_snr_db(speech, noise, rate)
    clipped = 0
    if preset.clip_dbfs is not None:
        x, n = hard_clip(x, preset.clip_dbfs)
        clipped += n
    cur = rate
    if preset.telephone:
        x, n = telephone(x, rate)
        clipped += n
        cur = TELEPHONE_RATE
    mask = np.zeros(_n_frames(len(x), cur), dtype=np.bool_)
    if preset.loss is not None:
        mask = loss_mask(len(mask), preset.loss.rate, preset.loss.mean_burst_frames, rng)
        x = apply_loss(x, _frame_len(cur), mask, preset.loss.conceal)
    x = _fit(resample_f(x, cur, out_rate), round(len(pcm) * out_rate / rate))
    out, n = to_int16(x)
    clipped += n
    lost = [bool(b) for b in mask]
    return Degraded(out, lost, DegradeStats(snr, len(lost), sum(lost), clipped))

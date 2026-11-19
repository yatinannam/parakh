"""Packet-loss masks and concealment."""

from typing import Literal

import numpy as np
import numpy.typing as npt

from parakh.degrade.filters import F64


def loss_mask(
    n_frames: int, rate: float, mean_burst_frames: float | None, rng: np.random.Generator
) -> npt.NDArray[np.bool_]:
    """True marks a lost frame.

    Independent losses when `mean_burst_frames` is None; otherwise a two-state
    Gilbert model: bad->good with r = 1 / mean_burst_frames, good->bad with
    p = rate * r / (1 - rate), which gives a stationary loss rate of `rate`.
    """
    u = rng.random(n_frames)
    if mean_burst_frames is None:
        return u < rate
    r = 1.0 / mean_burst_frames
    p = rate * r / (1.0 - rate)
    mask = np.zeros(n_frames, dtype=np.bool_)
    bad = bool(rng.random() < rate)
    for i in range(n_frames):
        bad = bool(u[i] >= r) if bad else bool(u[i] < p)
        mask[i] = bad
    return mask


def apply_loss(
    x: F64, frame_len: int, mask: npt.NDArray[np.bool_], conceal: Literal["zero", "repeat"]
) -> F64:
    """Conceal lost frames: silence, or repeat the previous frame as played."""
    out = x.copy()
    for i, lost in enumerate(mask):
        if not lost:
            continue
        a, b = i * frame_len, min((i + 1) * frame_len, len(out))
        if a >= len(out):
            break
        if conceal == "zero" or i == 0:
            out[a:b] = 0.0
        else:
            prev = out[a - frame_len : a]
            out[a:b] = prev[: b - a]
    return out

"""G.711 mu-law codec, written from the algorithm description (numpy only).

Encoding works on the 14-bit sample (16-bit input shifted right by 2). The
magnitude is clipped at 8159, biased by 33, placed in one of eight segments
(a value goes to the nearer of the two reconstruction levels at a segment
edge, which is what ffmpeg does), and the sign, segment and four mantissa bits are
inverted to form the code byte.
"""

import numpy as np
import numpy.typing as npt

from parakh.audio import PCM

_BIAS = 33
_CLIP = 8159
_MAX_BIASED = 8191
# A segment starts where the biased magnitude is nearer its first level than
# the previous segment's last level: ceil(129 * 2**k / 4) for k = 1..7.
_SEGMENT_STARTS = np.array([((129 << k) + 3) >> 2 for k in range(1, 8)], dtype=np.int32)


def _magnitude_14bit(pcm: PCM) -> npt.NDArray[np.int32]:
    """Absolute value of the 14-bit sample, before clipping."""
    s = pcm.astype(np.int32) >> 2
    return np.abs(s)


def mulaw_saturated(pcm: PCM) -> int:
    """Count samples whose 14-bit magnitude exceeds the clip value."""
    return int(np.count_nonzero(_magnitude_14bit(pcm) > _CLIP))


def mulaw_encode(pcm: PCM) -> npt.NDArray[np.uint8]:
    """Encode int16 PCM as G.711 mu-law bytes."""
    negative = (pcm.astype(np.int32) >> 2) < 0
    mag = np.minimum(_magnitude_14bit(pcm), _CLIP) + _BIAS
    mag = np.minimum(mag, _MAX_BIASED)
    segment = np.searchsorted(_SEGMENT_STARTS, mag, side="right").astype(np.int32)
    mantissa = np.clip((mag >> (segment + 1)) - 16, 0, 15)
    code = (negative.astype(np.int32) << 7) | (segment << 4) | mantissa
    return (~code & 0xFF).astype(np.uint8)


def mulaw_decode(codes: npt.NDArray[np.uint8]) -> PCM:
    """Decode G.711 mu-law bytes to int16 PCM."""
    c = ~codes.astype(np.int32) & 0xFF
    segment = (c >> 4) & 0x07
    mantissa = c & 0x0F
    mag = (((mantissa << 3) + (_BIAS << 2)) << segment) - (_BIAS << 2)
    return np.where(c & 0x80, -mag, mag).astype(np.int16)

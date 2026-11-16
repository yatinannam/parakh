"""Audio helpers: WAV I/O, dBFS, resampling, framing and silence trimming.

All PCM is mono int16 held in a numpy array.
"""

import math
import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy.signal import resample_poly

SAMPLE_RATE = 16000
FRAME_MS = 20
SILENCE_DBFS = -120.0
SPEECH_DBFS = -45.0
_WINDOW_MS = 10
_FULL_SCALE = 32768.0

PCM = npt.NDArray[np.int16]


def read_wav(path: Path) -> tuple[PCM, int]:
    """Read a 16-bit mono WAV file and return its samples and sample rate."""
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16-bit mono PCM")
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.int16), rate


def write_wav(path: Path, pcm: PCM, rate: int) -> None:
    """Write 16-bit mono PCM to a WAV file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.astype("<i2").tobytes())


def dbfs(pcm: PCM) -> float:
    """RMS level relative to full scale (32768), floored at SILENCE_DBFS."""
    if pcm.size == 0:
        return SILENCE_DBFS
    rms = math.sqrt(float(np.mean(np.square(pcm.astype(np.float64)))))
    if rms <= 0.0:
        return SILENCE_DBFS
    return max(SILENCE_DBFS, 20.0 * math.log10(rms / _FULL_SCALE))


def resample(pcm: PCM, src_rate: int, dst_rate: int) -> PCM:
    """Resample with a polyphase filter, clipped back to int16."""
    if src_rate == dst_rate:
        return pcm.copy()
    g = math.gcd(src_rate, dst_rate)
    out = resample_poly(pcm.astype(np.float64), dst_rate // g, src_rate // g)
    return np.clip(np.round(out), -32768, 32767).astype(np.int16)


def split_frames(pcm: PCM, rate: int, frame_ms: int = FRAME_MS) -> list[PCM]:
    """Split into fixed-size frames; the last frame is zero-padded."""
    size = rate * frame_ms // 1000
    frames: list[PCM] = []
    for start in range(0, len(pcm), size):
        frame = pcm[start : start + size]
        if len(frame) < size:
            frame = np.concatenate([frame, np.zeros(size - len(frame), dtype=np.int16)])
        frames.append(frame)
    return frames


def _speech_window_bounds(pcm: PCM, rate: int, threshold_dbfs: float) -> tuple[int, int] | None:
    """Return (start, end) sample indexes of the first and last loud 10 ms window."""
    size = rate * _WINDOW_MS // 1000
    loud = [i for i in range(0, len(pcm), size) if dbfs(pcm[i : i + size]) > threshold_dbfs]
    if not loud:
        return None
    return loud[0], min(loud[-1] + size, len(pcm))


def trim_silence(pcm: PCM, rate: int, threshold_dbfs: float = SPEECH_DBFS) -> PCM:
    """Drop leading and trailing windows at or below the threshold."""
    bounds = _speech_window_bounds(pcm, rate, threshold_dbfs)
    if bounds is None:
        return pcm[:0].copy()
    return pcm[bounds[0] : bounds[1]].copy()


def speech_end_ms(pcm: PCM, rate: int, threshold_dbfs: float = SPEECH_DBFS) -> int:
    """End time in ms of the last 10 ms window above the threshold (0 if none)."""
    bounds = _speech_window_bounds(pcm, rate, threshold_dbfs)
    if bounds is None:
        return 0
    return round(bounds[1] * 1000 / rate)

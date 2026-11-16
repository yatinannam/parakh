"""ffmpeg helpers: locate the binary and decode encoded audio to PCM."""

import shutil
import subprocess

import numpy as np

from parakh.audio import PCM, SAMPLE_RATE


class FfmpegMissing(RuntimeError):
    """Raised when ffmpeg is not on PATH."""


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise FfmpegMissing(
            "ffmpeg not found on PATH. Install it: "
            'Windows "winget install Gyan.FFmpeg", Ubuntu "sudo apt install ffmpeg".'
        )
    return path


def decode_to_pcm16(data: bytes, rate: int = SAMPLE_RATE) -> PCM:
    """Decode encoded audio bytes to mono int16 PCM at `rate`."""
    ffmpeg = require_ffmpeg()
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "pipe:1",
        ],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return np.frombuffer(result.stdout, dtype="<i2").astype(np.int16)

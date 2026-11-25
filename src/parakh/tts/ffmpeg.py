"""ffmpeg helpers: locate the binary and decode encoded audio to PCM."""

import shutil
import subprocess
from pathlib import Path

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
    return _decode("pipe:0", data, rate)


def decode_file_to_pcm16(path: Path, rate: int = SAMPLE_RATE) -> PCM:
    """Decode an audio file to mono int16 PCM at `rate`.

    ffmpeg reads the file itself: an .m4a with its index at the end cannot be piped.
    """
    return _decode(str(path.resolve()), None, rate)


def _decode(source: str, data: bytes | None, rate: int) -> PCM:
    ffmpeg = require_ffmpeg()
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            # A playlist or concat file among the recordings must not reach the network.
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            source,
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

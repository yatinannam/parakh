import subprocess

import numpy as np

from parakh.degrade.mulaw import mulaw_decode, mulaw_encode, mulaw_saturated

_FFMPEG = ["ffmpeg", "-hide_banner", "-loglevel", "error"]


def _run(args: list[str], data: bytes) -> bytes:
    return subprocess.run(_FFMPEG + args, input=data, capture_output=True, check=True).stdout


def test_encode_matches_ffmpeg_for_every_value() -> None:
    pcm = np.arange(-32768, 32768, dtype=np.int16)
    expected = _run(
        ["-f", "s16le", "-ar", "8000", "-ac", "1", "-i", "pipe:0", "-f", "mulaw", "pipe:1"],
        pcm.astype("<i2").tobytes(),
    )
    ours = mulaw_encode(pcm)
    assert ours.dtype == np.uint8
    assert ours.tobytes() == expected


def test_decode_matches_ffmpeg_for_every_code() -> None:
    codes = np.arange(256, dtype=np.uint8)
    expected = _run(
        ["-f", "mulaw", "-ar", "8000", "-ac", "1", "-i", "pipe:0", "-f", "s16le", "pipe:1"],
        codes.tobytes(),
    )
    ours = mulaw_decode(codes)
    assert ours.dtype == np.int16
    assert ours.astype("<i2").tobytes() == expected


def _sqnr_db(level_dbfs: float) -> float:
    # 1 kHz at 8 kHz repeats only 8 phases, so a zero-phase sine lands on
    # unlucky grid points (34.9 dB); a fixed 0.3 rad offset is representative.
    t = np.arange(8000) / 8000.0
    amp = 32768 * 10 ** (level_dbfs / 20)
    x = np.round(amp * np.sin(2 * np.pi * 1000 * t + 0.3)).astype(np.int16)
    y = mulaw_decode(mulaw_encode(x))
    sig = np.mean(x.astype(np.float64) ** 2)
    err = np.mean((x.astype(np.float64) - y.astype(np.float64)) ** 2)
    return float(10 * np.log10(sig / err))


def test_round_trip_sqnr() -> None:
    assert _sqnr_db(-3.0) >= 35.0
    assert _sqnr_db(-30.0) >= 33.0


def test_saturation_counted() -> None:
    square = np.where(np.arange(800) % 2 == 0, 32767, -32768).astype(np.int16)
    assert mulaw_saturated(square) == 800
    t = np.arange(8000) / 8000.0
    sine = np.round(32768 * 10 ** (-3 / 20) * np.sin(2 * np.pi * 1000 * t)).astype(np.int16)
    assert mulaw_saturated(sine) == 0

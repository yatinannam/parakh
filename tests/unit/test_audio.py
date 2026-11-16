from pathlib import Path

import numpy as np
import numpy.typing as npt

from parakh.audio import (
    SILENCE_DBFS,
    dbfs,
    read_wav,
    resample,
    speech_end_ms,
    split_frames,
    trim_silence,
    write_wav,
)


def tone(
    ms: int, rate: int = 16000, dbfs_peak: float = -3.0, hz: int = 440
) -> npt.NDArray[np.int16]:
    n = rate * ms // 1000
    t = np.arange(n) / rate
    amp = 32768 * 10 ** (dbfs_peak / 20)
    wave = amp * np.sin(2 * np.pi * hz * t)
    return np.clip(np.round(wave), -32768, 32767).astype(np.int16)


def zeros(ms: int, rate: int = 16000) -> npt.NDArray[np.int16]:
    return np.zeros(rate * ms // 1000, dtype=np.int16)


def test_dbfs_of_full_scale_sine() -> None:
    pcm = tone(1000, dbfs_peak=0.0)
    pcm = np.clip(pcm.astype(np.int32), -32767, 32767).astype(np.int16)
    assert abs(dbfs(pcm) - (-3.01)) < 0.05


def test_dbfs_of_silence() -> None:
    assert dbfs(zeros(100)) == SILENCE_DBFS


def test_split_frames_pads_last() -> None:
    frames = split_frames(tone(50), 16000)
    assert len(frames) == 3
    assert all(len(f) == 320 for f in frames)
    assert not frames[2][160:].any()


def test_resample_lengths() -> None:
    up = resample(tone(1000, rate=16000), 16000, 24000)
    assert len(up) == 24000
    assert up.dtype == np.int16
    down = resample(tone(1000, rate=24000), 24000, 16000)
    assert len(down) == 16000


def test_trim_and_speech_end() -> None:
    pcm = np.concatenate([zeros(200), tone(500), zeros(300)])
    assert abs(speech_end_ms(pcm, 16000) - 700) <= 10
    assert abs(len(trim_silence(pcm, 16000)) - 8000) <= 160


def test_wav_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "dir with space" / "sub" / "a.wav"
    pcm = tone(100)
    write_wav(path, pcm, 16000)
    out, rate = read_wav(path)
    assert rate == 16000
    assert np.array_equal(out, pcm)

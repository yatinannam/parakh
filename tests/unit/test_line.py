"""build_line: the caller line a call streams, per preset."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from parakh.audio import dbfs, resample, speech_end_ms, split_frames, write_wav
from parakh.caller.line import CallerLine, build_line
from parakh.degrade import DegradeError
from parakh.scenario import CallerVoice, Limits, Scenario, Turn
from parakh.tts.cache import CallerClip, TTSCache
from tests.fakes import FakeEngine

RATE = 16000


def _scenario(n: int) -> Scenario:
    return Scenario(
        schema_version=1,
        id="line-test",
        title="Line test",
        language="hi-en",
        domain="test",
        clock=datetime(2026, 11, 16, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        caller=CallerVoice(voice="hi-IN-SwaraNeural"),
        turns=[Turn(say=f"turn {i}") for i in range(n)],
        limits=Limits(),
    )


def _tone() -> np.ndarray:
    t = np.arange(RATE * 400 // 1000) / RATE
    return np.round(3000 * np.sin(2 * np.pi * 300 * t)).astype(np.int16)


def _clips(base: Path, pcms: list[np.ndarray]) -> list[CallerClip]:
    clips = []
    for i, pcm in enumerate(pcms):
        path = base / "dir with space" / f"turn {i}.wav"
        write_wav(path, pcm, RATE)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        clips.append(
            CallerClip(i, path, RATE, speech_end_ms(pcm, RATE), len(pcm) * 1000 // RATE, digest)
        )
    return clips


async def _line(base: Path, pcms: list[np.ndarray], preset: str, rate: int = RATE) -> CallerLine:
    cache = TTSCache(base / "dir with space" / "cache")
    return await build_line(
        _scenario(len(pcms)), _clips(base, pcms), preset, rate, cache=cache, engine=FakeEngine()
    )


async def test_clean_line_matches_m1_frames(tmp_path: Path) -> None:
    pcm = _tone()
    line = await _line(tmp_path, [pcm], "clean")
    expected = split_frames(resample(pcm, RATE, RATE), RATE)
    assert len(line.turns[0].frames) == len(expected)
    assert all(np.array_equal(a, b) for a, b in zip(line.turns[0].frames, expected, strict=True))
    assert len(line.bed) == 1 and not line.bed[0].any()
    assert line.bed_lost == [False]
    assert line.seed is None and line.turns[0].stats is None
    assert line.turns[0].lost == [False] * len(expected)
    assert line.rate == RATE and line.preset == "clean"


@pytest.mark.parametrize("rate", [8000, 16000, 24000])
async def test_line_frames_at_agent_rate(tmp_path: Path, rate: int) -> None:
    pcm = _tone()
    phone = await _line(tmp_path, [pcm, pcm], "phone", rate)
    clean = await _line(tmp_path, [pcm, pcm], "clean", rate)
    for p, c in zip(phone.turns, clean.turns, strict=True):
        assert all(len(f) == rate // 50 for f in p.frames)
        assert len(p.frames) == len(c.frames)
        assert p.speech_end_frame == c.speech_end_frame
        assert len(p.lost) == len(p.frames)


async def test_line_is_deterministic(tmp_path: Path) -> None:
    a = await _line(tmp_path / "a", [_tone(), _tone()], "bad_line")
    b = await _line(tmp_path / "b", [_tone(), _tone()], "bad_line")
    assert a.seed == b.seed and a.seed is not None
    for x, y in zip(a.turns, b.turns, strict=True):
        assert np.array_equal(np.concatenate(x.frames), np.concatenate(y.frames))
        assert x.lost == y.lost
    assert np.array_equal(np.concatenate(a.bed), np.concatenate(b.bed))


async def test_noisy_bed_is_not_silent(tmp_path: Path) -> None:
    line = await _line(tmp_path, [_tone()], "phone_noisy")
    assert dbfs(np.concatenate(line.bed)) > -60
    assert len(line.bed_lost) == len(line.bed)


async def test_silent_turn_gets_null_snr(tmp_path: Path) -> None:
    zeros = np.zeros(RATE * 400 // 1000, dtype=np.int16)
    line = await _line(tmp_path, [_tone(), zeros, _tone()], "bad_line")
    stats = [t.stats for t in line.turns]
    assert stats[1] is not None and stats[1].snr_db is None
    assert stats[0] is not None and stats[0].snr_db is not None
    assert stats[2] is not None and stats[2].snr_db is not None


async def test_all_silent_noise_preset_raises(tmp_path: Path) -> None:
    zeros = np.zeros(RATE * 400 // 1000, dtype=np.int16)
    with pytest.raises(DegradeError):
        await _line(tmp_path, [zeros, zeros], "bad_line")

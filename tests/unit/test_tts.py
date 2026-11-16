import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from parakh.cli import app
from parakh.scenario import load_scenario
from parakh.tts.cache import TTSCache, build_scenario_audio, cache_key
from parakh.tts.ffmpeg import FfmpegMissing, decode_to_pcm16, require_ffmpeg
from tests.fakes import FakeEngine

EXAMPLE = Path("scenarios/hinglish/clinic-book-hinglish-01.yaml")


def test_require_ffmpeg_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(FfmpegMissing, match=r"winget install Gyan\.FFmpeg"):
        require_ffmpeg()


async def test_decode_mp3_to_16k() -> None:
    data = await FakeEngine().synthesize("x", "v", "+0%", "+0Hz")
    pcm = decode_to_pcm16(data)
    assert pcm.dtype.name == "int16"
    assert abs(len(pcm) - 9600) <= 800


def test_cache_key_is_stable_and_sensitive() -> None:
    base = ["e", "1", "voice", "+0%", "+0Hz", "text"]
    key = cache_key(base[0], base[1], base[2], base[3], base[4], base[5])
    assert key == cache_key(base[0], base[1], base[2], base[3], base[4], base[5])
    for i in range(6):
        c = list(base)
        c[i] += "x"
        assert cache_key(c[0], c[1], c[2], c[3], c[4], c[5]) != key


async def test_cache_hit_skips_engine(tmp_path: Path) -> None:
    cache = TTSCache(tmp_path / "dir with space")
    engine = FakeEngine()
    clip1, built1 = await cache.get(engine, "v", "+0%", "+0Hz", "namaste", 0)
    clip2, built2 = await cache.get(engine, "v", "+0%", "+0Hz", "namaste", 0)
    assert engine.calls == 1
    assert built1 is True
    assert built2 is False
    assert clip2.path == clip1.path
    manifest = json.loads((cache.root / "manifest.json").read_text(encoding="utf-8"))
    key = cache_key("fake", "1", "v", "+0%", "+0Hz", "namaste")
    assert manifest[key]["sha256"] == hashlib.sha256(clip1.path.read_bytes()).hexdigest()
    assert abs(clip1.speech_end_ms - 600) <= 30


async def test_corrupt_entry_is_rebuilt(tmp_path: Path) -> None:
    cache = TTSCache(tmp_path / "dir with space")
    engine = FakeEngine()
    clip, _ = await cache.get(engine, "v", "+0%", "+0Hz", "namaste", 0)
    clip.path.write_bytes(clip.path.read_bytes()[:50])
    _, built = await cache.get(engine, "v", "+0%", "+0Hz", "namaste", 0)
    assert built is True
    assert engine.calls == 2


async def test_build_scenario_audio(tmp_path: Path) -> None:
    scenario = load_scenario(EXAMPLE)
    cache = TTSCache(tmp_path / "dir with space")
    engine = FakeEngine()
    clips, built = await build_scenario_audio(scenario, cache, engine)
    assert [c.turn_index for c in clips] == [0, 1, 2, 3]
    assert built == 4
    _, built2 = await build_scenario_audio(scenario, cache, engine)
    assert built2 == 0


def test_tts_build_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parakh.cli.make_engine", lambda: FakeEngine())
    cache_dir = tmp_path / "dir with space"
    result = CliRunner().invoke(app, ["tts", "build", str(EXAMPLE), "--cache-dir", str(cache_dir)])
    assert result.exit_code == 0, result.output
    assert "4 clips (4 built, 0 cached)" in result.output

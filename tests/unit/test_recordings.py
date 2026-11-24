"""Real recordings: found by name, decoded to 16 kHz mono, checked before any call."""

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from parakh.audio import SAMPLE_RATE, read_wav
from parakh.cli import app
from parakh.scenario import Scenario, load_scenario
from parakh.tts.recordings import (
    RecordingError,
    load_recorded_clips,
    recording_paths,
    recording_status,
)

if shutil.which("ffmpeg") is None:  # pragma: no cover
    pytest.skip("ffmpeg not installed", allow_module_level=True)

YAML = """\
schema_version: 1
id: rec-real-01
title: Recordings test
language: hi-en
domain: clinic
clock: "2026-11-19T10:00:00+05:30"
caller:
  voice: hi-IN-SwaraNeural
turns:
  - say: "one"
  - say: "two"
  - say: "three"
  - say: "four"
"""

SINE = "sine=frequency=440:duration=1"


def make_audio(path: Path, source: str = SINE, codec: list[str] | None = None) -> Path:
    """Write a 48 kHz stereo file with ffmpeg; the format follows the file extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source]
    cmd += ["-ar", "48000", "-ac", "2", *(codec or []), str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def setup(tmp_path: Path) -> tuple[Scenario, Path, Path]:
    base = tmp_path / "dir with space"
    base.mkdir()
    file = base / "s.yaml"
    file.write_text(YAML, encoding="utf-8")
    return load_scenario(file), base / "real", file


def fill(root: Path, numbers: list[int], ext: str = "wav") -> None:
    for n in numbers:
        make_audio(root / "rec-real-01" / f"turn-{n:02d}.{ext}")


def test_recordings_decode_any_format(tmp_path: Path) -> None:
    scenario, root, _ = setup(tmp_path)
    ext = "m4a"
    try:
        make_audio(root / "rec-real-01" / "turn-01.m4a", codec=["-c:a", "aac"])
    except subprocess.CalledProcessError:  # pragma: no cover - no aac encoder
        ext = "wav"
        make_audio(root / "rec-real-01" / "turn-01.wav")
    fill(root, [2, 3], "flac")
    make_audio(root / "rec-real-01" / "Turn-04.WAV")
    clips = load_recorded_clips(scenario, root)
    assert [c.turn_index for c in clips] == [0, 1, 2, 3]
    first = clips[0]
    pcm, rate = read_wav(first.path)
    assert rate == SAMPLE_RATE == first.sample_rate
    assert 900 <= first.duration_ms <= 1200
    assert first.speech_end_ms <= first.duration_ms
    assert first.path.name == ".turn-01.16k.wav"
    assert (root / "rec-real-01" / f"turn-01.{ext}").is_file()  # the original is untouched
    assert len(pcm) == round(first.duration_ms * rate / 1000)


def test_decoded_cache_is_reused_and_refreshed(tmp_path: Path) -> None:
    scenario, root, _ = setup(tmp_path)
    fill(root, [1, 2, 3, 4])
    first = load_recorded_clips(scenario, root)
    stamp = first[0].path.stat().st_mtime_ns
    assert load_recorded_clips(scenario, root)[0].path.stat().st_mtime_ns == stamp
    make_audio(root / "rec-real-01" / "turn-01.wav", source="sine=frequency=300:duration=2")
    refreshed = load_recorded_clips(scenario, root)[0]
    assert refreshed.duration_ms > first[0].duration_ms + 500


def test_missing_or_silent_recording_fails_before_call(tmp_path: Path) -> None:
    scenario, root, _ = setup(tmp_path)
    fill(root, [1, 2, 4])
    with pytest.raises(RecordingError, match=r"turn 3.*turn-03\.\*"):
        load_recorded_clips(scenario, root)
    make_audio(root / "rec-real-01" / "turn-03.wav", source="anullsrc=r=48000:cl=stereo:d=1")
    with pytest.raises(RecordingError, match=r"turn-03\.wav is silent"):
        load_recorded_clips(scenario, root)
    (root / "rec-real-01" / "turn-03.wav").write_bytes(b"not audio")
    with pytest.raises(RecordingError, match=r"cannot decode .*turn-03\.wav"):
        load_recorded_clips(scenario, root)


def test_two_files_for_one_turn_name_both(tmp_path: Path) -> None:
    scenario, root, _ = setup(tmp_path)
    fill(root, [1, 2, 3, 4])
    make_audio(root / "rec-real-01" / "turn-02.m4a", codec=["-c:a", "aac"])
    with pytest.raises(RecordingError) as info:
        recording_paths(scenario, root)
    assert "turn-02.m4a" in str(info.value) and "turn-02.wav" in str(info.value)


def test_status_lists_unused_files(tmp_path: Path) -> None:
    scenario, root, _ = setup(tmp_path)
    fill(root, [1, 2, 3, 4, 9])
    folder = root / "rec-real-01"
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    (folder / ".hidden.wav").write_bytes(b"")
    load_recorded_clips(scenario, root)  # leaves .turn-NN.16k.wav caches behind
    status = recording_status(scenario, root)
    assert status.complete
    assert sorted(p.name for p in status.unused) == ["notes.txt", "turn-09.wav"]
    assert [t.path is not None for t in status.turns] == [True] * 4
    assert status.turns[0].expected.endswith("rec-real-01/turn-01.*")


def test_status_command_exit_codes(tmp_path: Path) -> None:
    _, root, file = setup(tmp_path)
    fill(root, [1, 2, 3])
    make_audio(root / "rec-real-01" / "turn-09.wav")
    args = ["recordings", "status", str(file), "--real-dir", str(root)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("turn 01: found  ") and lines[0].endswith('turn-01.*  "one"')
    assert lines[3].startswith("turn 04: MISSING  ") and lines[3].endswith('turn-04.*  "four"')
    assert any(line.startswith("unused:") and "turn-09.wav" in line for line in lines)
    fill(root, [4])
    ok = CliRunner().invoke(app, args)
    assert ok.exit_code == 0, ok.output

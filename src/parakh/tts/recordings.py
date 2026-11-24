"""Real recordings of the caller turns (D10): the files, their status and their clips.

A recording lives at data/real/<scenario_id>/turn-<NN>.<ext>, NN being the 1-based turn
number. Any format ffmpeg reads is accepted. Each is decoded once to 16 kHz mono, trimmed
like a synthesised clip, and cached next to the original as .turn-<NN>.16k.wav. This audio
is personal data: nothing here touches the network.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from parakh.audio import SAMPLE_RATE, read_wav, speech_end_ms, trim_silence, write_wav
from parakh.scenario import Scenario
from parakh.tts.cache import CallerClip
from parakh.tts.ffmpeg import decode_file_to_pcm16

REAL_ROOT = Path("data/real")
_TURN_FILE = re.compile(r"^turn-(\d+)\.[A-Za-z0-9]+$")


class RecordingError(ValueError):
    """A recording is missing, ambiguous, undecodable or silent."""


@dataclass(frozen=True)
class TurnRecording:
    index: int  # 0-based
    say: str
    expected: str  # the file name pattern, such as data/real/<id>/turn-01.*
    path: Path | None


@dataclass(frozen=True)
class RecordingStatus:
    turns: list[TurnRecording]
    unused: list[Path]

    @property
    def complete(self) -> bool:
        return all(t.path is not None for t in self.turns)


def _scan(scenario: Scenario, root: Path) -> tuple[dict[int, list[Path]], list[Path]]:
    """Files by 0-based turn index, and the files that belong to no turn."""
    found: dict[int, list[Path]] = {}
    unused: list[Path] = []
    folder = root / scenario.id
    files = sorted(folder.iterdir()) if folder.is_dir() else []
    for path in files:
        if path.name.startswith(".") or not path.is_file():
            continue
        match = _TURN_FILE.match(path.name.lower())
        index = int(match.group(1)) - 1 if match else -1
        if 0 <= index < len(scenario.turns):
            found.setdefault(index, []).append(path)
        else:
            unused.append(path)
    return found, unused


def recording_paths(scenario: Scenario, root: Path = REAL_ROOT) -> list[Path | None]:
    """One recording path per turn, None where there is none. Two files for a turn raise."""
    found, _ = _scan(scenario, root)
    paths: list[Path | None] = []
    for index in range(len(scenario.turns)):
        files = found.get(index, [])
        if len(files) > 1:
            raise RecordingError(
                f"turn {index + 1} of {scenario.id} has two recordings: "
                f"{files[0]} and {files[1]}; keep one"
            )
        paths.append(files[0] if files else None)
    return paths


def recording_status(scenario: Scenario, root: Path = REAL_ROOT) -> RecordingStatus:
    """Each turn's say text, expected file name and file, plus the files nothing uses."""
    paths = recording_paths(scenario, root)
    _, unused = _scan(scenario, root)
    turns = [
        TurnRecording(
            index=i,
            say=turn.say,
            expected=(root / scenario.id / f"turn-{i + 1:02d}.*").as_posix(),
            path=path,
        )
        for i, (turn, path) in enumerate(zip(scenario.turns, paths, strict=True))
    ]
    return RecordingStatus(turns, unused)


def _cache_path(path: Path, number: int) -> Path:
    return path.with_name(f".turn-{number:02d}.16k.wav")


def _clip(path: Path, number: int) -> CallerClip:
    cache = _cache_path(path, number)
    if not (cache.is_file() and cache.stat().st_mtime_ns >= path.stat().st_mtime_ns):
        try:
            decoded = decode_file_to_pcm16(path, SAMPLE_RATE)
        except RuntimeError as exc:
            lines = str(exc).strip().splitlines()
            detail = lines[-1] if lines else "no output"
            raise RecordingError(f"cannot decode {path}: {detail}") from exc
        pcm = trim_silence(decoded, SAMPLE_RATE)
        if len(pcm) == 0:
            raise RecordingError(f"{path} is silent (nothing above -45 dBFS); record it again")
        write_wav(cache, pcm, SAMPLE_RATE)
    pcm, rate = read_wav(cache)
    return CallerClip(
        turn_index=number - 1,
        path=cache,
        sample_rate=rate,
        speech_end_ms=speech_end_ms(pcm, rate),
        duration_ms=round(len(pcm) * 1000 / rate),
        sha256=hashlib.sha256(cache.read_bytes()).hexdigest(),
    )


def load_recorded_clips(scenario: Scenario, root: Path = REAL_ROOT) -> list[CallerClip]:
    """Every turn's recording as a clip; RecordingError names the file or turn that fails."""
    clips: list[CallerClip] = []
    for index, path in enumerate(recording_paths(scenario, root)):
        if path is None:
            expected = root / scenario.id / f"turn-{index + 1:02d}.*"
            raise RecordingError(f"no recording for turn {index + 1} of {scenario.id}: {expected}")
        clips.append(_clip(path, index + 1))
    return clips

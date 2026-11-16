"""Content-addressed cache of caller clips (16 kHz WAV)."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from parakh.audio import SAMPLE_RATE, speech_end_ms, trim_silence, write_wav
from parakh.scenario import Scenario
from parakh.tts.engine import TTSEngine
from parakh.tts.ffmpeg import decode_to_pcm16

DEFAULT_CACHE_ROOT = Path(".cache/tts")


def cache_key(
    engine: str, engine_version: str, voice: str, rate: str, pitch: str, text: str
) -> str:
    canonical = json.dumps([engine, engine_version, voice, rate, pitch, text], ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CallerClip:
    turn_index: int
    path: Path
    sample_rate: int
    speech_end_ms: int
    duration_ms: int
    sha256: str


class TTSCache:
    def __init__(self, root: Path = DEFAULT_CACHE_ROOT) -> None:
        self.root = root

    @property
    def _manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def _load_manifest(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_manifest(self, manifest: dict[str, dict[str, object]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._manifest_path)

    def _from_entry(self, entry: object, turn_index: int) -> CallerClip | None:
        try:
            return self._read_entry(entry, turn_index)
        except (AttributeError, KeyError, TypeError, ValueError, OSError):
            return None

    def _read_entry(self, entry: object, turn_index: int) -> CallerClip | None:
        if not isinstance(entry, dict):
            return None
        path = self.root / str(entry.get("file", ""))
        if not path.is_file():
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.get("sha256"):
            return None
        return CallerClip(
            turn_index=turn_index,
            path=path,
            sample_rate=SAMPLE_RATE,
            speech_end_ms=int(str(entry["speech_end_ms"])),
            duration_ms=int(str(entry["duration_ms"])),
            sha256=digest,
        )

    async def get(
        self, engine: TTSEngine, voice: str, rate: str, pitch: str, text: str, turn_index: int
    ) -> tuple[CallerClip, bool]:
        key = cache_key(engine.name, engine.version, voice, rate, pitch, text)
        manifest = self._load_manifest()
        entry = manifest.get(key)
        if entry is not None:
            clip = self._from_entry(entry, turn_index)
            if clip is not None:
                return clip, False
        data = await engine.synthesize(text, voice, rate, pitch)
        pcm = trim_silence(decode_to_pcm16(data, SAMPLE_RATE), SAMPLE_RATE)
        path = self.root / f"{key}.wav"
        write_wav(path, pcm, SAMPLE_RATE)
        end_ms = speech_end_ms(pcm, SAMPLE_RATE)
        dur_ms = round(len(pcm) * 1000 / SAMPLE_RATE)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[key] = {
            "file": path.name,
            "sha256": digest,
            "speech_end_ms": end_ms,
            "duration_ms": dur_ms,
            "engine": engine.name,
            "engine_version": engine.version,
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
            "text": text,
        }
        self._save_manifest(manifest)
        return CallerClip(turn_index, path, SAMPLE_RATE, end_ms, dur_ms, digest), True


async def build_scenario_audio(
    scenario: Scenario, cache: TTSCache, engine: TTSEngine
) -> tuple[list[CallerClip], int]:
    clips: list[CallerClip] = []
    built = 0
    caller = scenario.caller
    for index, turn in enumerate(scenario.turns):
        clip, was_built = await cache.get(
            engine, caller.voice, caller.rate, caller.pitch, turn.say, index
        )
        clips.append(clip)
        built += int(was_built)
    return clips, built

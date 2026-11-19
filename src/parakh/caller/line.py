"""The caller line: every caller turn and the noise bed, rendered before the call.

The driver only streams these frames. Degradation is applied once here, with seeds
from call_seed, so the same scenario under the same preset sends the same audio.
"""

from dataclasses import dataclass

import numpy as np

from parakh.audio import FRAME_MS, PCM, SAMPLE_RATE, read_wav, resample, split_frames
from parakh.degrade import (
    DegradeStats,
    call_seed,
    degrade,
    get_preset,
    noise_scale,
    noise_slice,
    part_rng,
)
from parakh.degrade.filters import F64, peak_normalise
from parakh.degrade.track import noise_track
from parakh.scenario import Scenario
from parakh.tts.cache import CallerClip, TTSCache
from parakh.tts.engine import TTSEngine

BED_S = 10.0


@dataclass(frozen=True)
class LineTurn:
    frames: list[PCM]
    lost: list[bool]
    speech_end_frame: int
    stats: DegradeStats | None


@dataclass(frozen=True)
class CallerLine:
    preset: str
    seed: int | None
    rate: int
    turns: list[LineTurn]
    bed: list[PCM]
    bed_lost: list[bool]


def _frames(pcm: PCM, lost: list[bool], rate: int) -> tuple[list[PCM], list[bool]]:
    """20 ms frames (one silent frame for an empty clip) and one lost flag per frame."""
    frames = split_frames(pcm, rate)
    if not frames:
        return [np.zeros(rate * FRAME_MS // 1000, dtype=np.int16)], [False]
    return frames, (lost + [False] * len(frames))[: len(frames)]


def _turn(
    clip: CallerClip, frames: list[PCM], lost: list[bool], stats: DegradeStats | None
) -> LineTurn:
    end = min(len(frames) - 1, clip.speech_end_ms // FRAME_MS)
    return LineTurn(frames, lost, end, stats)


async def build_line(
    scenario: Scenario,
    clips: list[CallerClip],
    preset: str,
    agent_rate: int,
    *,
    cache: TTSCache,
    engine: TTSEngine,
) -> CallerLine:
    """Render the caller turns and the bed for one call under a preset."""
    spec = get_preset(preset)
    raw = [read_wav(clip.path) for clip in clips]
    silent_frame = np.zeros(agent_rate * FRAME_MS // 1000, dtype=np.int16)
    if spec.name == "clean":
        turns = []
        for clip, (pcm, src_rate) in zip(clips, raw, strict=True):
            frames, lost = _frames(resample(pcm, src_rate, agent_rate), [], agent_rate)
            turns.append(_turn(clip, frames, lost, None))
        return CallerLine(preset, None, agent_rate, turns, [silent_frame], [False])

    pcms = [resample(pcm, src_rate, SAMPLE_RATE) for pcm, src_rate in raw]
    seed = call_seed(scenario.id, preset)
    track = await noise_track(spec, seed, cache, engine)
    scale = 0.0
    if spec.noise is not None and track is not None:
        normalised: list[F64] = [peak_normalise(p.astype(np.float64)) for p in pcms]
        scale = noise_scale(normalised, track, SAMPLE_RATE, spec.noise.snr_db)

    turns = []
    for i, (clip, pcm) in enumerate(zip(clips, pcms, strict=True)):
        rng = part_rng(seed, f"turn-{i}")
        noise = None
        if track is not None:
            noise = scale * noise_slice(track, len(pcm), rng)
        out = degrade(pcm, SAMPLE_RATE, spec, out_rate=agent_rate, noise=noise, rng=rng)
        frames, lost = _frames(out.pcm, out.lost, agent_rate)
        turns.append(_turn(clip, frames, lost, out.stats))

    rng = part_rng(seed, "bed")
    n = round(BED_S * SAMPLE_RATE)
    noise = None if track is None else scale * noise_slice(track, n, rng)
    bed = degrade(
        np.zeros(n, dtype=np.int16), SAMPLE_RATE, spec, out_rate=agent_rate, noise=noise, rng=rng
    )
    bed_frames, bed_lost = _frames(bed.pcm, bed.lost, agent_rate)
    if not any(f.any() for f in bed_frames):
        bed_frames, bed_lost = [silent_frame], [False]
    return CallerLine(preset, seed, agent_rate, turns, bed_frames, bed_lost)

"""Test doubles shared across test modules."""

import subprocess

from parakh.report.model import JitterModel, LatencyStatsModel, Metrics, Report


class FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel: records how it was built and called."""

    def __init__(self, model_size_or_path: str, **kwargs: object) -> None:
        self.name = model_size_or_path
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []

    def transcribe(self, audio: object, **kwargs: object) -> tuple[list[object], None]:
        self.calls.append(kwargs)
        return [], None


class FakeEngine:
    """TTS engine that returns a short sine-wave MP3 and counts calls."""

    name = "fake"
    version = "1"

    def __init__(self) -> None:
        self.calls = 0
        self._mp3: bytes | None = None

    def _make_mp3(self) -> bytes:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.6",
                "-ar",
                "24000",
                "-f",
                "mp3",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", "replace"))
        return result.stdout

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        self.calls += 1
        if self._mp3 is None:
            self._mp3 = self._make_mp3()
        return self._mp3


def make_report(
    *,
    scenario_id: str = "s1",
    title: str = "Scenario one",
    preset: str = "clean",
    status: str = "completed",
    run_id: str = "a1b2c3d4",
    loose_wer: float | None = 0.1,
    p50: float | None = 800.0,
) -> Report:
    """A minimal Report for comparison and batch tests."""
    return Report(
        parakh_version="0",
        git_sha=None,
        run_id=run_id,
        created_at="t",
        scenario_id=scenario_id,
        scenario_title=title,
        language="en",
        preset=preset,
        seed=None,
        agent_url="ws://h",
        agent_info={},
        status=status,
        timing_unreliable=False,
        jitter=JitterModel(n=0, p50_ms=0, p99_ms=0, max_ms=0),
        cpu_max_percent=0,
        turns=[],
        metrics=Metrics(
            latency=LatencyStatsModel(n=0, p50_ms=p50, p90_ms=p50, p95_ms=p50, max_ms=p50),
            strict_wer=loose_wer,
            loose_wer=loose_wer,
            loose_cer=None,
            wer_reason=None,
        ),
        warnings=[],
    )

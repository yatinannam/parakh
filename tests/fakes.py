"""Test doubles shared across test modules."""

import subprocess


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

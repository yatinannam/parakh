"""TTS engines. edge-tts is an unmodified LGPL dependency."""

from typing import Protocol

import edge_tts

from parakh.budget.guard import remote_call


class TTSEngine(Protocol):
    name: str
    version: str

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        """Return encoded audio bytes for `text`."""
        ...


class EdgeTTSEngine:
    name = "edge-tts"
    version = edge_tts.__version__

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        remote_call("edge-tts", real=False)
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk.get("data", b""))
        return b"".join(chunks)

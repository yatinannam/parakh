"""Pipecat TTS service that speaks with a Parakh TTSEngine (edge-tts by default)."""

import asyncio
from collections.abc import AsyncGenerator, Callable

import numpy as np
from pipecat.frames.frames import Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService

from parakh.tts.engine import TTSEngine
from parakh.tts.ffmpeg import decode_to_pcm16

CHUNK_MS = 20


class EdgeTTSService(TTSService):
    def __init__(
        self,
        *,
        engine: TTSEngine,
        voice: str,
        sample_rate: int = 16000,
        decode: Callable[[bytes, int], np.ndarray] = decode_to_pcm16,
        **kwargs,
    ) -> None:
        # With these flags the base class emits the started and stopped frames itself.
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )
        self._engine = engine
        self._voice = voice
        self._rate = sample_rate
        self._decode = decode

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        encoded = await self._engine.synthesize(text, self._voice, "+0%", "+0Hz")
        pcm = (await asyncio.to_thread(self._decode, encoded, self._rate)).astype(np.int16)
        step = self._rate * CHUNK_MS // 1000
        for start in range(0, len(pcm), step):
            chunk = pcm[start : start + step]
            yield TTSAudioRawFrame(chunk.tobytes(), self._rate, 1, context_id=context_id)

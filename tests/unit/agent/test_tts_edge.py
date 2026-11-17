import numpy as np
from pipecat.frames.frames import TTSAudioRawFrame

from agents.clinic_agent.tts_edge import EdgeTTSService


class _Engine:
    name = "fake"
    version = "0"

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        return b"encoded"


def _decode(data: bytes, rate: int) -> np.ndarray:
    return np.ones(16000, dtype=np.int16)


async def test_tts_service_yields_audio() -> None:
    service = EdgeTTSService(engine=_Engine(), voice="en-IN-NeerjaNeural", decode=_decode)
    frames = [f async for f in service.run_tts("hello", "ctx")]
    audio = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
    assert audio
    assert all(len(f.audio) == 640 for f in audio)
    assert sum(len(f.audio) for f in audio) == 32000
    assert all(f.sample_rate == 16000 and f.num_channels == 1 for f in audio)

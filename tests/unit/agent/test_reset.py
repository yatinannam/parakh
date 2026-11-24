import array
import warnings
from typing import Any

import pytest
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADState
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.whisper.stt import WhisperSTTService

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from agents.clinic_agent.reset import ClinicLocalSTT, ClinicSTT, ClinicVAD, ResettableSTTMixin

RATE = 16000
WINDOW = 512


class _LoudAnalyzer(VADAnalyzer):
    """Scores every window as speech, so no Silero model is loaded."""

    def num_frames_required(self) -> int:
        return WINDOW

    def voice_confidence(self, buffer: bytes) -> float:
        return 1.0


def _loud(samples: int) -> bytes:
    return array.array("h", [20000, -20000] * (samples // 2)).tobytes()


async def test_vad_reset_returns_to_quiet_without_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyzer = _LoudAnalyzer()
    analyzer.set_sample_rate(RATE)
    vad = ClinicVAD(vad_analyzer=analyzer)
    events: list[str] = []

    async def broadcast_frame(frame_cls: type[Frame], **_kwargs: Any) -> None:
        events.append(frame_cls.__name__)

    monkeypatch.setattr(vad, "broadcast_frame", broadcast_frame)
    controller = vad._vad_controller
    for _ in range(40):
        audio = _loud(WINDOW)
        await controller._handle_audio(InputAudioRawFrame(audio, RATE, 1))
    assert controller._vad_state == VADState.SPEAKING
    # A partial window is left over, as when a caller hangs up mid-chunk.
    await controller._handle_audio(InputAudioRawFrame(_loud(100), RATE, 1))
    assert analyzer._vad_buffer != b""
    events.clear()

    vad.reset_call()

    assert controller._vad_state == VADState.QUIET
    assert analyzer._vad_state == VADState.QUIET
    assert analyzer._vad_buffer == b""
    assert "VADUserStoppedSpeakingFrame" not in events
    assert events == []


@pytest.fixture(params=[ClinicSTT, ClinicLocalSTT], ids=["groq", "local"])
def stt(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> ResettableSTTMixin:
    # WhisperSTTService.__init__ calls _load(), which loads (and may download) the model.
    monkeypatch.setattr(WhisperSTTService, "_load", lambda self: None)
    if request.param is ClinicSTT:
        service: Any = ClinicSTT(api_key="test-key", sample_rate=RATE)
    else:
        service = ClinicLocalSTT(sample_rate=RATE)
    service._sample_rate = RATE  # set by StartFrame in a running pipeline
    service._speech_buffer.set_sample_rate(RATE)
    return service


def test_reset_mixin_on_both_services() -> None:
    assert issubclass(ClinicSTT, ResettableSTTMixin)
    assert issubclass(ClinicLocalSTT, ResettableSTTMixin)
    assert issubclass(ClinicLocalSTT, WhisperSTTService)


async def test_stt_reset_drops_open_segment(stt: Any) -> None:
    await stt._handle_user_started_speaking(VADUserStartedSpeakingFrame(start_secs=0.2))
    stt._speech_buffer.append(_loud(RATE))
    stt.reset_call()
    await stt._handle_user_stopped_speaking(VADUserStoppedSpeakingFrame(stop_secs=0.8))
    assert stt._segment_queue.empty()


async def test_stt_reset_removes_queued_segments(stt: Any) -> None:
    stt._segment_queue.put_nowait((b"old", 1))
    stt._segment_queue.put_nowait((b"older", 2))
    stt._segment_count = 2
    stt.reset_call()
    assert stt._segment_queue.empty()


async def test_stt_keeps_segments_of_the_next_call(stt: Any) -> None:
    stt.reset_call()
    await stt._handle_user_started_speaking(VADUserStartedSpeakingFrame(start_secs=0.2))
    stt._speech_buffer.append(_loud(RATE))
    await stt._handle_user_stopped_speaking(VADUserStoppedSpeakingFrame(stop_secs=0.8))
    assert stt._segment_queue.qsize() == 1


async def test_stt_reset_drops_transcripts_of_old_segments(
    stt: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pushed: list[Frame] = []

    async def push_frame(_self: FrameProcessor, frame: Frame, *_args: Any) -> None:
        pushed.append(frame)

    monkeypatch.setattr(FrameProcessor, "push_frame", push_frame)
    stt._segment_count = 3
    stt._transcribing_segment = 3
    stt.reset_call()

    await stt.push_frame(TranscriptionFrame("old call", "u", "now"))
    await stt.push_frame(InterimTranscriptionFrame("old call", "u", "now"))
    assert pushed == []

    stt._transcribing_segment = 4
    await stt.push_frame(TranscriptionFrame("new call", "u", "now"))
    assert [f.text for f in pushed if isinstance(f, TranscriptionFrame)] == ["new call"]

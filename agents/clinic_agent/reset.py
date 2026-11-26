"""VAD and STT services that drop their state between calls.

One pipeline serves call after call, so a speech segment still open when a caller hangs
up would otherwise surface in the next call. Both services lean on private Pipecat 1.16
attributes; the version is pinned exactly and the tests break if they move.
"""

import os
from typing import TYPE_CHECKING, Any, cast

from faster_whisper import WhisperModel
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.utils.types import require_given

# Local STT speed on the M3b laptop (Core Ultra 5 225U, Chrome open; run-m3b.md): faster-whisper
# small at its defaults ran 2.8 times slower than real time, because a clip that hallucinates
# is decoded again at every fallback temperature. One temperature, no timestamps and 8 threads
# ran at 1.09 and scored better (loose WER 60.0 % against 67.5 % on the real clips).
LOCAL_CPU_THREADS = min(8, os.cpu_count() or 4)
LOCAL_DECODE: dict[str, Any] = {"temperature": 0.0, "without_timestamps": True}


class ClinicVAD(VADProcessor):
    """VADProcessor that can return to quiet without announcing a speech stop."""

    def reset_call(self) -> None:
        controller = self._vad_controller
        # Set the state directly: going through the controller would emit
        # on_speech_stopped and push a stop frame into the next call.
        controller._vad_state = VADState.QUIET
        analyzer = controller._vad_analyzer
        # set_params returns the analyzer to QUIET and clears its start/stop counters. It
        # divides by the sample rate, which is unset until the pipeline starts; before
        # that the analyzer has scored nothing, so there is nothing to clear.
        if analyzer.sample_rate:
            analyzer.set_params(analyzer.params)
        analyzer._vad_buffer = b""
        if isinstance(analyzer, SileroVADAnalyzer):
            analyzer._model.reset_states()
            # Silero counts windows since its last model reset; the model was just reset.
            analyzer._windows_since_reset = 0
            analyzer._low_confidence_windows = 0


# For type checking the mixin is a SegmentedSTTService; at run time it is a plain mixin, so
# the real service class that follows it in the bases supplies the behaviour.
_MixinBase = SegmentedSTTService if TYPE_CHECKING else object


class ResettableSTTMixin(_MixinBase):
    """Lets a SegmentedSTTService discard everything a finished call left behind.

    Both STT services share Pipecat's SegmentedSTTService, which holds the segment state
    this touches; put the mixin first in the bases.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._reset_segment = 0
        self._segment_open = False

    def reset_call(self) -> None:
        self._speech_buffer.stop()
        self._segment_open = False
        while not self._segment_queue.empty():
            self._segment_queue.get_nowait()
        # A segment being transcribed right now belongs to the old call.
        self._reset_segment = self._segment_count

    async def _handle_user_started_speaking(self, frame: VADUserStartedSpeakingFrame) -> None:
        self._segment_open = True
        await super()._handle_user_started_speaking(frame)

    async def _handle_user_stopped_speaking(self, frame: VADUserStoppedSpeakingFrame) -> None:
        # The segment was discarded by reset_call: queueing its trailing silence would
        # send an empty segment for transcription.
        if not self._segment_open:
            return
        self._segment_open = False
        await super()._handle_user_stopped_speaking(frame)

    async def push_frame(
        self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        stale = self._transcribing_segment <= self._reset_segment
        if stale and isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
            return
        await super().push_frame(frame, direction)


class ClinicSTT(ResettableSTTMixin, GroqSTTService):
    """Groq-hosted STT with the per-call reset."""


class _TunedWhisper:
    """Adds Parakh's decode options to every transcribe call that Pipecat makes."""

    def __init__(self, model: Any) -> None:
        self._model = model

    def transcribe(self, audio: Any, **kwargs: Any) -> Any:
        return self._model.transcribe(audio, **LOCAL_DECODE, **kwargs)


class ClinicLocalSTT(ResettableSTTMixin, WhisperSTTService):
    """Local faster-whisper STT with the per-call reset. Audio never leaves the laptop."""

    def _load(self) -> None:
        # Pipecat 1.16's _load builds the model without cpu_threads; the rest is the same.
        name = require_given(self._settings.model, "Whisper model")
        model = WhisperModel(
            name,
            device=self._device,
            compute_type=self._compute_type,
            cpu_threads=LOCAL_CPU_THREADS,
        )
        # run_stt calls only transcribe(), which _TunedWhisper provides.
        self._model = cast("WhisperModel", _TunedWhisper(model))
        unsupported = self._unsupported_language()
        if unsupported:
            raise ValueError(unsupported)

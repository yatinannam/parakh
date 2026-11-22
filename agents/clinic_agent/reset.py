"""VAD and STT services that drop their state between calls.

One pipeline serves call after call, so a speech segment still open when a caller hangs
up would otherwise surface in the next call. Both services lean on private Pipecat 1.16
attributes; the version is pinned exactly and the tests break if they move.
"""

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


class ClinicSTT(GroqSTTService):
    """GroqSTTService that can discard everything a finished call left behind."""

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

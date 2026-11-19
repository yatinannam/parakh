"""Virtual playback clock: models agent audio as played at real-time speed."""

_NS_PER_S = 1_000_000_000


class PlaybackClock:
    """Tracks when a phone speaker would finish playing the audio received so far.

    Agents may send audio faster than real time; playback is serialised, so each
    frame starts at max(previous playback end, its arrival time). Every frame takes
    its place on that timeline, except a silent frame that arrives while earlier
    audio is still queued: it is not placed, so streamed silence never pushes later
    speech back. Only a loud frame (above -45 dBFS,
    EC-27) moves loud_end_ns, and "agent speaking" means now < loud_end_ns, so an
    agent that streams silence between replies is not speaking.
    """

    def __init__(self) -> None:
        self.playback_end_ns: int | None = None
        self.loud_end_ns: int | None = None  # playback end of the last loud frame

    def on_audio(
        self, arrival_ns: int, n_samples: int, sample_rate: int, *, loud: bool
    ) -> int | None:
        """Place one frame and return its playback start, or None if it is not placed."""
        if not loud and self.playback_end_ns is not None and self.playback_end_ns > arrival_ns:
            return None
        duration_ns = n_samples * _NS_PER_S // sample_rate
        start = arrival_ns
        if self.playback_end_ns is not None:
            start = max(self.playback_end_ns, arrival_ns)
        self.playback_end_ns = start + duration_ns
        if loud:
            self.loud_end_ns = self.playback_end_ns
        return start

    def flush(self, now_ns: int) -> int:
        """Drop queued audio (an interruption); return the nanoseconds dropped."""
        dropped = 0
        if self.playback_end_ns is not None and self.playback_end_ns > now_ns:
            dropped = self.playback_end_ns - now_ns
            self.playback_end_ns = now_ns
        if self.loud_end_ns is not None:
            self.loud_end_ns = min(self.loud_end_ns, now_ns)
        return dropped

    def speaking(self, now_ns: int) -> bool:
        return self.loud_end_ns is not None and now_ns < self.loud_end_ns

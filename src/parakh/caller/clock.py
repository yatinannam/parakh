"""Virtual playback clock: models agent audio as played at real-time speed."""

_NS_PER_S = 1_000_000_000


class PlaybackClock:
    """Tracks when a phone speaker would finish playing the audio received so far.

    Agents may send audio faster than real time; playback is serialised, so each
    frame starts at max(previous playback end, its arrival time).
    """

    def __init__(self) -> None:
        self.playback_end_ns: int | None = None

    def on_audio(self, arrival_ns: int, n_samples: int, sample_rate: int) -> None:
        duration_ns = n_samples * _NS_PER_S // sample_rate
        start = arrival_ns
        if self.playback_end_ns is not None:
            start = max(self.playback_end_ns, arrival_ns)
        self.playback_end_ns = start + duration_ns

    def speaking(self, now_ns: int) -> bool:
        return self.playback_end_ns is not None and now_ns < self.playback_end_ns

from parakh.caller.clock import PlaybackClock

MS = 1_000_000


def test_burst_arrivals_play_in_real_time() -> None:
    clock = PlaybackClock()
    assert clock.playback_end_ns is None
    assert not clock.speaking(0)
    for _ in range(10):
        clock.on_audio(0, 320, 16_000)
    assert clock.playback_end_ns == 200 * MS
    assert clock.speaking(150 * MS)
    assert not clock.speaking(201 * MS)
    clock.on_audio(500 * MS, 320, 16_000)
    assert clock.playback_end_ns == 520 * MS


def test_playback_clock_uses_frame_rate() -> None:
    clock = PlaybackClock()
    clock.on_audio(0, 480, 24_000)
    assert clock.playback_end_ns == 20 * MS

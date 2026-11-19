from parakh.caller.clock import PlaybackClock

MS = 1_000_000


def test_burst_arrivals_play_in_real_time() -> None:
    clock = PlaybackClock()
    assert clock.playback_end_ns is None
    assert not clock.speaking(0)
    for _ in range(10):
        clock.on_audio(0, 320, 16_000, loud=True)
    assert clock.playback_end_ns == 200 * MS
    assert clock.speaking(150 * MS)
    assert not clock.speaking(201 * MS)
    clock.on_audio(500 * MS, 320, 16_000, loud=True)
    assert clock.playback_end_ns == 520 * MS


def test_playback_clock_uses_frame_rate() -> None:
    clock = PlaybackClock()
    clock.on_audio(0, 480, 24_000, loud=True)
    assert clock.playback_end_ns == 20 * MS


def test_silent_frames_keep_their_place_but_do_not_count_as_speaking() -> None:
    # EC-27: "agent speaking" needs a frame above -45 dBFS. A silent frame still
    # takes its place on the timeline (the recorder places it there), but it
    # does not extend loud_end, so an agent streaming silence is not speaking.
    clock = PlaybackClock()
    assert clock.loud_end_ns is None
    assert clock.on_audio(0, 320, 16_000, loud=False) == 0
    assert clock.playback_end_ns == 20 * MS
    assert clock.loud_end_ns is None
    assert not clock.speaking(10 * MS)
    assert clock.on_audio(0, 3200, 16_000, loud=True) == 20 * MS
    assert clock.loud_end_ns == 220 * MS
    for k in range(50):
        clock.on_audio(k * 20 * MS, 320, 16_000, loud=False)
    assert clock.playback_end_ns == 1000 * MS  # silence behind a backlog is not placed
    assert clock.loud_end_ns == 220 * MS
    assert clock.speaking(219 * MS)
    assert not clock.speaking(220 * MS)


def test_silence_does_not_queue_behind_backlog() -> None:
    clock = PlaybackClock()
    clock.on_audio(0, 1600, 16_000, loud=True)  # 100 ms
    assert clock.playback_end_ns == 100 * MS
    assert clock.on_audio(10 * MS, 320, 16_000, loud=False) is None
    assert clock.playback_end_ns == 100 * MS
    assert clock.loud_end_ns == 100 * MS
    assert clock.on_audio(10 * MS, 320, 16_000, loud=True) == 100 * MS  # loud still queues
    assert clock.on_audio(500 * MS, 320, 16_000, loud=False) == 500 * MS  # idle: placed


def test_flush_drops_queued_audio() -> None:
    clock = PlaybackClock()
    assert clock.flush(0) == 0
    clock.on_audio(0, 8000, 16_000, loud=True)  # 500 ms burst
    assert clock.flush(200 * MS) == 300 * MS
    assert clock.playback_end_ns == 200 * MS
    assert clock.loud_end_ns == 200 * MS
    assert clock.speaking(199 * MS)
    assert not clock.speaking(201 * MS)
    assert clock.flush(300 * MS) == 0
    assert clock.loud_end_ns == 200 * MS


def test_onset_kept_across_short_gap() -> None:
    clock = PlaybackClock()
    assert clock.onset_ns is None
    clock.on_audio(0, 8000, 16_000, loud=True)  # loud 0-500 ms
    assert clock.onset_ns == 0
    clock.on_audio(600 * MS, 320, 16_000, loud=True)
    assert clock.onset_ns == 0


def test_onset_resets_after_200ms_gap() -> None:
    clock = PlaybackClock()
    clock.on_audio(0, 8000, 16_000, loud=True)
    clock.on_audio(800 * MS, 320, 16_000, loud=True)
    assert clock.onset_ns == 800 * MS
    clock.flush(810 * MS)
    assert clock.onset_ns == 800 * MS  # a flush does not change it


def test_silent_frame_does_not_set_onset() -> None:
    clock = PlaybackClock()
    clock.on_audio(0, 320, 16_000, loud=False)
    assert clock.onset_ns is None

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from parakh.audio import read_wav, resample
from parakh.caller.recorder import Recorder, read_events

T0 = 1_000_000_000


def _tone(n: int, amp: int = 8000) -> np.ndarray:
    return np.full(n, amp, dtype=np.int16)


def test_events_jsonl_is_valid_utf8(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.event("caller_transcript", T0 + 1_500_000, text="हाँ", final=True)
    rec.close()
    raw = (run / "events.jsonl").read_bytes()
    assert "हाँ".encode() in raw
    line = json.loads(raw.decode("utf-8").splitlines()[0])
    assert line == {"kind": "caller_transcript", "t_ms": 1.5, "text": "हाँ", "final": True}
    assert read_events(run) == [line]


def test_caller_wav_has_every_frame(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    for i in range(50):
        rec.caller_frame(T0 + i * 20_000_000, _tone(320), 16000, turn=None, frame=None)
    rec.close()
    pcm, rate = read_wav(run / "caller.wav")
    assert rate == 16000
    assert len(pcm) == 16000
    assert len(read_wav(run / "agent.wav")[0]) == 16000


def test_agent_audio_resampled_into_wav(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    for i in range(50):
        rec.agent_frame(T0 + i * 20_000_000, _tone(480), 24000, i * 20.0)
    rec.close()
    pcm, rate = read_wav(run / "agent.wav")
    assert rate == 16000
    assert abs(len(pcm) - 16000) <= 320
    events = read_events(run)
    assert len(events) == 50
    assert all(e["kind"] == "agent_audio" and e["duration_ms"] == 20.0 for e in events)
    assert events[0]["sample_rate"] == 24000
    assert events[0]["dbfs"] == pytest.approx(-12.25, abs=0.01)
    assert events[1]["t_ms"] == 20.0


def test_agent_frame_placed_at_playback_start(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(160), 16000, 100.0)
    rec.close()
    pcm, _ = read_wav(run / "agent.wav")
    assert len(pcm) == 1600 + 160
    assert not pcm[:1600].any()
    assert (pcm[1600:] == 8000).all()
    assert len(read_wav(run / "caller.wav")[0]) == len(pcm)


def test_paths_with_spaces(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "ab12cd34"
    rec = Recorder(run, T0)
    rec.close()
    assert run.is_dir()
    assert (run / "caller.wav").exists()
    assert len(read_wav(run / "caller.wav")[0]) == 0


def test_close_idempotent_and_negative_t_ms(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.event("warning", T0 - 2_000_000, message="early")
    rec.close()
    rec.close()
    assert read_events(run)[0]["t_ms"] == -2.0


def test_read_events_partial_and_invalid(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    run.mkdir(parents=True)
    path = run / "events.jsonl"
    path.write_text('{"kind": "a"}\n{"kind": "b"', encoding="utf-8")
    assert read_events(run) == [{"kind": "a"}]
    path.write_text('{"kind": "a"}\nnot json\n{"kind": "b"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        read_events(run)


def test_negative_playback_start_is_trimmed(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(320, 1000), 16000, -10.0)
    rec.close()
    pcm, _ = read_wav(run / "agent.wav")
    assert len(pcm) == 160
    assert (pcm == 1000).all()


def test_frame_entirely_before_zero_is_dropped(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(160, 1000), 16000, -50.0)
    rec.agent_frame(T0, _tone(160, 2000), 16000, 20.0)
    rec.close()
    pcm, _ = read_wav(run / "agent.wav")
    assert len(pcm) == 480
    assert not pcm[:320].any()
    assert (pcm[320:] == 2000).all()
    assert [e["kind"] for e in read_events(run)] == ["agent_audio", "agent_audio"]


def test_overlapping_frames_overwrite(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(320, 1000), 16000, 0.0)
    rec.agent_frame(T0, _tone(320, 2000), 16000, 10.0)
    rec.close()
    pcm, _ = read_wav(run / "agent.wav")
    assert len(pcm) == 480
    assert (pcm[:160] == 1000).all()
    assert (pcm[160:] == 2000).all()


def test_odd_length_resampled_frame(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(441), 22050, 0.0)
    rec.close()
    assert read_events(run)[0]["duration_ms"] == 20.0
    assert abs(len(read_wav(run / "agent.wav")[0]) - 320) <= 1


class _SlowFile:
    """Stands in for events.jsonl: each flush blocks like a stalled disk write."""

    def __init__(self, real: Any, fail: bool = False) -> None:
        self.real = real
        self.fail = fail

    def write(self, line: str) -> int:
        if self.fail:
            raise OSError("disk full")
        return self.real.write(line)

    def flush(self) -> None:
        time.sleep(0.05)
        self.real.flush()

    def close(self) -> None:
        self.real.close()


def test_event_does_not_wait_for_the_disk(tmp_path: Path) -> None:
    # The driver calls event() on its event loop; a stalled write (NTFS and filter
    # drivers can block one for 30 ms or more) must not stall the call.
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec._events = _SlowFile(rec._events)  # type: ignore[assignment]
    start = time.perf_counter()
    for i in range(5):
        rec.event("tick", T0 + i * 1_000_000, i=i)
    assert time.perf_counter() - start < 0.05
    rec.close()
    assert [e["i"] for e in read_events(run)] == [0, 1, 2, 3, 4]


def test_event_write_error_raised_at_close(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec._events = _SlowFile(rec._events, fail=True)  # type: ignore[assignment]
    rec.event("tick", T0)
    with pytest.raises(OSError, match="disk full"):
        rec.close()
    assert (run / "caller.wav").is_file()


def _sine(n: int, rate: int) -> np.ndarray:
    t = np.arange(n) / rate
    return np.round(8000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)


def test_agent_runs_resampled_once(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    whole = _sine(24000, 24000)
    frames = [whole[i * 480 : (i + 1) * 480] for i in range(50)]
    rec = Recorder(run, T0)
    for i, frame in enumerate(frames):
        rec.agent_frame(T0 + i * 20_000_000, frame, 24000, i * 20.0)
    rec.close()
    pcm, _ = read_wav(run / "agent.wav")
    expected = resample(whole, 24000, 16000)
    assert len(pcm) == len(expected)
    assert np.abs(pcm.astype(np.int32) - expected.astype(np.int32)).max() <= 1
    per_frame = np.concatenate([resample(f, 24000, 16000) for f in frames])
    assert np.abs(per_frame.astype(np.int32) - expected.astype(np.int32)).max() > 1


def test_agent_flush_cuts_track(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(16000, 5000), 16000, 0.0)
    rec.agent_flush(T0 + 400_000_000)
    rec.agent_frame(T0 + 500_000_000, _tone(160, 7000), 16000, 500.0)  # after the flush: kept
    rec.close()
    pcm, _ = read_wav(run / "agent.wav")
    assert (pcm[:6400] == 5000).all()
    assert not pcm[6400:8000].any()
    assert (pcm[8000:8160] == 7000).all()


def test_agent_flush_drops_frames_starting_after_the_cut(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(320, 1000), 16000, 0.0)
    rec.agent_frame(T0, _tone(320, 2000), 16000, 20.0)
    rec.agent_flush(T0 + 10_000_000)
    rec.close()
    pcm, _ = read_wav(run / "agent.wav")
    assert len(pcm) == 160
    assert (pcm == 1000).all()


def test_caller_frames_logged_and_resampled_once(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    whole = _sine(1600, 8000)
    rec = Recorder(run, T0)
    for i in range(10):
        frame = whole[i * 160 : (i + 1) * 160]
        rec.caller_frame(T0 + i * 20_000_000, frame, 8000, turn=0, frame=i, lost=i == 3)
    rec.close()
    events = read_events(run)
    assert [(e["kind"], e["turn"], e["frame"], e["lost"]) for e in events] == [
        ("caller_frame", 0, i, i == 3) for i in range(10)
    ]
    pcm, rate = read_wav(run / "caller.wav")
    assert rate == 16000
    assert np.array_equal(pcm, resample(whole, 8000, 16000))


def test_caller_lead_precedes_frames_and_rates_must_match(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.caller_lead(80)  # 10 ms at 8 kHz
    rec.caller_frame(T0, _tone(160, 3000), 8000, turn=None, frame=None)
    with pytest.raises(ValueError, match="rate"):
        rec.caller_frame(T0, _tone(160, 3000), 16000, turn=None, frame=None)
    rec.close()
    pcm, _ = read_wav(run / "caller.wav")
    assert len(pcm) == 480
    assert not pcm[:100].any()  # the lead is 160 samples at 16 kHz
    assert (np.abs(pcm[240:420].astype(int) - 3000) < 100).all()
    assert [e["kind"] for e in read_events(run)] == ["caller_frame"]


def test_agent_audio_event_has_play_ms(tmp_path: Path) -> None:
    run = tmp_path / "dir with space" / "run"
    rec = Recorder(run, T0)
    rec.agent_frame(T0, _tone(160), 16000, 123.456)
    rec.agent_frame(T0, _tone(160), 16000, None)
    rec.close()
    events = read_events(run)
    assert events[0]["play_ms"] == 123.456
    assert events[1]["play_ms"] is None
    assert len(read_wav(run / "agent.wav")[0]) == round(123.456 * 16) + 160

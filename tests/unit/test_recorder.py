import json
from pathlib import Path

import numpy as np
import pytest

from parakh.audio import read_wav
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
        rec.caller_frame(T0 + i * 20_000_000, _tone(320), 16000)
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

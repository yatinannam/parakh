from datetime import datetime, timedelta, timezone
from pathlib import Path

from parakh.caller.driver import CallResult
from parakh.caller.pacer import JitterStats
from parakh.report.build import build_report
from parakh.report.html import render_html, write_report_html
from parakh.report.model import (
    BargeInReport,
    JitterModel,
    LatencyStatsModel,
    Metrics,
    Report,
    TurnDegradation,
    TurnReport,
    load_report,
    write_report_json,
)
from parakh.scenario import BargeIn, CallerVoice, Limits, Scenario, Turn

IST = timezone(timedelta(hours=5, minutes=30))


def make_report(
    transcript: str = "kal shaam",
    reference: str = "kal subah",
    *,
    status: str = "completed",
    latency_ms: float | None = 850.0,
    agent_info: dict | None = None,
    ttfb: list[float] | None = None,
    nulls: bool = False,
) -> Report:
    turn = TurnReport(
        index=0,
        say=reference,
        reference=reference,
        transcript=transcript,
        latency_ms=None if nulls else latency_ms,
        latency_reason="no agent audio" if nulls else None,
        strict_wer=None if nulls else 0.5,
        loose_wer=None if nulls else 0.5,
        agent_text="ji boliye",
        agent_ttfb_ms=ttfb or [],
    )
    latency = (
        LatencyStatsModel(n=0, p50_ms=None, p90_ms=None, p95_ms=None, max_ms=None)
        if nulls
        else LatencyStatsModel(n=1, p50_ms=850.0, p90_ms=850.0, p95_ms=850.0, max_ms=850.0)
    )
    return Report(
        parakh_version="0.0.1",
        git_sha=None,
        run_id="run1",
        created_at="2026-11-16T10:00:00+05:30",
        scenario_id="s1",
        scenario_title="Booking",
        language="hinglish",
        preset="clean",
        seed=None,
        agent_url="ws://localhost:8765",
        agent_info=agent_info or {},
        status=status,
        timing_unreliable=False,
        jitter=JitterModel(n=3, p50_ms=1.0, p99_ms=2.0, max_ms=3.0),
        cpu_max_percent=40.0,
        turns=[turn],
        metrics=Metrics(
            latency=latency,
            strict_wer=None if nulls else 0.125,
            loose_wer=None if nulls else 0.125,
            loose_cer=None,
            wer_reason="agent exposed no caller transcript" if nulls else None,
        ),
        warnings=[],
    )


def test_json_round_trip(tmp_path: Path):
    report = make_report()
    path = tmp_path / "report.json"
    write_report_json(report, path)
    assert load_report(path) == report
    text = path.read_text(encoding="utf-8")
    assert '"schema_version": 1' in text
    assert text.endswith("\n")


def test_html_is_self_contained():
    html = render_html(make_report())
    for banned in ("<script", "<link", "http://", "https://"):
        assert banned not in html
    assert "<svg" in html
    assert 'src="caller.wav"' in html
    assert 'src="agent.wav"' in html
    assert '<meta charset="utf-8">' in html


def test_agent_text_is_escaped():
    html = render_html(make_report(transcript="<script>alert(1)</script>"))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html


def test_agent_info_is_escaped():
    html = render_html(make_report(agent_info={"llm_model": "<b>x</b>"}))
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_devanagari_preserved(tmp_path: Path):
    word = "हाँ"
    report = make_report(transcript=word, reference=word)
    write_report_json(report, tmp_path / "report.json")
    path = write_report_html(report, tmp_path)
    assert path == tmp_path / "report.html"
    assert word in path.read_text(encoding="utf-8")
    assert word in (tmp_path / "report.json").read_text(encoding="utf-8")


def test_mismatches_marked():
    html = render_html(make_report())
    assert '<mark class="miss">shaam</mark>' in html
    assert '<mark class="miss">kal</mark>' not in html


def test_null_metrics_render():
    html = render_html(make_report(nulls=True, status="agent_disconnected"))
    assert "n/a" in html
    assert "agent_disconnected" in html


def test_agent_model_and_ttfb_shown():
    html = render_html(make_report(agent_info={"llm_model": "openai/gpt-oss-20b"}, ttfb=[812.0]))
    assert "openai/gpt-oss-20b" in html
    assert "812" in html


def test_number_formats():
    html = render_html(make_report())
    assert "12.5%" in html
    assert "850 ms" in html


def test_degradation_and_seed_shown():
    report = make_report().model_copy(update={"seed": 1234, "preset": "bad_line"})
    deg = TurnDegradation(snr_db=5.04, frames=30, lost_frames=2, clipped_samples=17)
    report.turns[0] = report.turns[0].model_copy(update={"degradation": deg})
    html = render_html(report)
    assert "seed 1234" in html
    assert "line: SNR 5.0 dB (at mixing), lost 2/30 frames, clipped 17 samples" in html


def test_m1_turn_without_degradation_loads():
    data = make_report().model_dump(mode="json")
    del data["turns"][0]["degradation"]
    assert Report.model_validate(data).turns[0].degradation is None
    assert "line: SNR" not in render_html(make_report())


def test_report_includes_barge_in(tmp_path: Path):
    scenario = Scenario(
        schema_version=1,
        id="s1",
        title="Booking",
        language="hi-en",
        domain="test",
        clock=datetime(2026, 11, 16, 10, 0, tzinfo=IST),
        agent_speaks_first=True,
        caller=CallerVoice(voice="hi-IN-SwaraNeural"),
        turns=[Turn(say="one"), Turn(say="two", barge_in=BargeIn(after_agent_ms=1200))],
        limits=Limits(response_timeout_s=1.5, call_timeout_s=20, max_turns=12),
    )
    events: list[dict] = [
        {"kind": "caller_turn_start", "t_ms": 1000.0, "turn": 0},
        {"kind": "caller_speech_end", "t_ms": 2000.0, "turn": 0},
        {"kind": "caller_turn_end", "t_ms": 2100.0, "turn": 0},
        {"kind": "caller_turn_start", "t_ms": 5000.0, "turn": 1},
        {"kind": "barge_in", "t_ms": 5000.0, "turn": 1, "after_agent_ms": 1200.0},
        {"kind": "caller_speech_end", "t_ms": 5600.0, "turn": 1},
        {"kind": "caller_turn_end", "t_ms": 5700.0, "turn": 1},
        {"kind": "user_started", "t_ms": 9000.0},
    ]
    for t in range(2400, 7400, 20):
        events.append(
            {
                "kind": "agent_audio",
                "t_ms": float(t),
                "duration_ms": 20.0,
                "dbfs": -20.0,
                "sample_rate": 8000,
                "play_ms": float(t),
            }
        )
    result = CallResult(
        status="completed",
        run_dir=tmp_path,
        turns_started=2,
        jitter=JitterStats(n=0, p50_ms=0.0, p99_ms=0.0, max_ms=0.0),
        timing_unreliable=False,
        cpu_max_percent=0.0,
        agent_info={},
        warnings=[],
    )
    report = build_report(scenario, result, events, run_id="r", agent_url="ws://x", preset="clean")
    assert report.turns[0].barge_in is None
    barge = report.turns[1].barge_in
    assert barge is not None
    assert barge.result == "did_not_yield"
    assert report.metrics.did_not_yield == 1
    assert report.metrics.stop_latency is not None
    assert report.metrics.stop_latency.n == 0
    assert report.metrics.false_barge_in_ms == [9000.0]
    html = render_html(report)
    assert "Barge-in stop latency p50 / p95 / max" in html
    assert "Did not yield" in html
    assert "False barge-ins" in html
    assert "did not yield within 2 s" in html


def test_report_shows_stopped_barge_in(tmp_path: Path):
    report = make_report()
    barge = BargeInReport(
        after_agent_ms=1200.0, onset_ms=5000.0, stop_latency_ms=340.0, result="yielded", via="audio"
    )
    report.turns[0] = report.turns[0].model_copy(update={"barge_in": barge})
    stats = LatencyStatsModel(n=1, p50_ms=340.0, p90_ms=340.0, p95_ms=340.0, max_ms=340.0)
    report = report.model_copy(
        update={"metrics": report.metrics.model_copy(update={"stop_latency": stats})}
    )
    html = render_html(report)
    assert "barge-in after 1200 ms: stopped in 340 ms (audio)" in html
    assert "340 ms / 340 ms / 340 ms" in html


def test_m1_report_without_barge_in_loads():
    data = make_report().model_dump(mode="json")
    del data["turns"][0]["barge_in"]
    for key in ("stop_latency", "did_not_yield", "false_barge_in_ms"):
        del data["metrics"][key]
    loaded = Report.model_validate(data)
    assert loaded.metrics.stop_latency is None
    assert "Barge-in stop" not in render_html(loaded)


def test_turn_without_noise_prints_snr_na_without_unit():
    report = make_report().model_copy(update={"preset": "phone"})
    deg = TurnDegradation(snr_db=None, frames=30, lost_frames=0, clipped_samples=0)
    report.turns[0] = report.turns[0].model_copy(update={"degradation": deg})
    html = render_html(report)
    assert "line: SNR n/a, lost 0/30 frames" in html
    assert "n/a dB" not in html

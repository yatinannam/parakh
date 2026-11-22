import os
from pathlib import Path

import pytest

from parakh.report.compare import Comparison, _report_href, build_comparison, write_comparison
from parakh.report.model import Report, TurnReport
from tests.fakes import make_report


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "dir with space" / "batch"
    out.mkdir(parents=True)
    return out


def test_rows_ordered_by_scenario_then_preset(tmp_path: Path):
    out = _out(tmp_path)
    runs = [
        (make_report(scenario_id="b", preset="phone"), out / "r1"),
        (make_report(scenario_id="a", preset="bad_line"), out / "r2"),
        (make_report(scenario_id="a", preset="mystery"), out / "r3"),
        (make_report(scenario_id="a", preset="clean"), out / "r4"),
        (make_report(scenario_id="b", preset="clean"), out / "r5"),
    ]
    rows = build_comparison(runs, out).rows
    assert [(r.scenario_id, r.preset) for r in rows] == [
        ("a", "clean"),
        ("a", "bad_line"),
        ("a", "mystery"),
        ("b", "clean"),
        ("b", "phone"),
    ]


def test_report_links_are_relative(tmp_path: Path):
    out = _out(tmp_path)
    comparison = build_comparison([(make_report(), out / "a1b2c3d4")], out)
    assert comparison.rows[0].report_href == "a1b2c3d4/report.html"


def test_compare_html_escapes_titles(tmp_path: Path):
    out = _out(tmp_path)
    comparison = build_comparison([(make_report(title="<script>x</script>"), out / "r")], out)
    html = write_comparison(comparison, out).read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_compare_json_round_trips(tmp_path: Path):
    out = _out(tmp_path)
    title = "नमस्ते"
    comparison = build_comparison([(make_report(title=title), out / "r")], out)
    write_comparison(comparison, out)
    text = (out / "compare.json").read_text(encoding="utf-8")
    assert title in text
    assert Comparison.model_validate_json(text) == comparison


def test_failed_run_shows_status(tmp_path: Path):
    out = _out(tmp_path)
    failed = make_report(status="agent_unreachable", loose_wer=None, p50=None)
    comparison = build_comparison([(failed, out / "r")], out)
    html = write_comparison(comparison, out).read_text(encoding="utf-8")
    assert comparison.rows[0].status == "agent_unreachable"
    assert "agent_unreachable" in html
    assert "n/a" in html
    assert 'href="r/report.html"' in html


def test_charts_cover_each_preset(tmp_path: Path):
    out = _out(tmp_path)
    runs = [
        (make_report(preset="clean", loose_wer=0.0, p50=500.0), out / "r1"),
        (make_report(preset="phone", loose_wer=0.2, p50=900.0), out / "r2"),
    ]
    html = write_comparison(build_comparison(runs, out), out).read_text(encoding="utf-8")
    assert html.count("<svg") == 2
    assert "20.0%" in html
    assert "900 ms" in html


def _turn(index: int, reason: str | None) -> TurnReport:
    return TurnReport(
        index=index,
        say="x",
        reference="x",
        transcript="",
        latency_ms=None,
        latency_reason=reason,
        strict_wer=None,
        loose_wer=None,
        agent_text="",
        agent_ttfb_ms=[],
    )


def _with_turns(report: Report, reasons: list[str | None]) -> Report:
    turns = [_turn(i, r) for i, r in enumerate(reasons)]
    return report.model_copy(update={"turns": turns})


def test_turns_reached_counts_turns_not_marked_unreached(tmp_path: Path):
    out = _out(tmp_path)
    report = _with_turns(make_report(), [None, "no reply", "turn not reached", "turn not reached"])
    comparison = build_comparison([(report, out / "r")], out)
    assert (comparison.rows[0].turns_reached, comparison.rows[0].turns_total) == (2, 4)
    html = write_comparison(comparison, out).read_text(encoding="utf-8")
    assert "Turns reached" in html
    assert "2/4" in html


def test_fallback_report_counts_no_turn_as_reached(tmp_path: Path):
    out = _out(tmp_path)
    report = _with_turns(make_report(status="internal_error"), ["no data", "no data", "no data"])
    comparison = build_comparison([(report, out / "r")], out)
    assert (comparison.rows[0].turns_reached, comparison.rows[0].turns_total) == (0, 3)


def test_non_completed_run_gets_muted_status_bar(tmp_path: Path):
    out = _out(tmp_path)
    runs = [
        (make_report(preset="clean", status="turn_timeout", loose_wer=0.5), out / "r1"),
        (make_report(preset="phone", loose_wer=0.2), out / "r2"),
    ]
    html = write_comparison(build_comparison(runs, out), out).read_text(encoding="utf-8")
    assert html.count('class="partial"') == 2  # one muted bar in each of the two charts
    assert ">turn_timeout</text>" in html
    assert ">50.0%</text>" not in html  # the table keeps the value, the chart does not
    assert ">20.0%</text>" in html
    assert "Muted bars" in html


def test_completed_run_bar_keeps_value_label(tmp_path: Path):
    out = _out(tmp_path)
    html = write_comparison(
        build_comparison([(make_report(loose_wer=0.2, p50=900.0), out / "r")], out), out
    ).read_text(encoding="utf-8")
    assert 'class="partial"' not in html
    assert "20.0%" in html
    assert "900 ms" in html


def test_href_across_drives_falls_back_to_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def other_drive(*_a: object, **_k: object) -> str:
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", other_drive)
    href = _report_href(tmp_path / "dir with space" / "r1", tmp_path)
    assert href.startswith("file:")
    assert href.endswith("report.html")

from pathlib import Path

from parakh.report.compare import Comparison, build_comparison, write_comparison
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

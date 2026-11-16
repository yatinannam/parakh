"""Render report.html: one self-contained page with inline CSS and SVG."""

from pathlib import Path

from jinja2 import Environment, PackageLoader

from parakh.report.diff import mark_misses
from parakh.report.model import Report

_ENV = Environment(
    loader=PackageLoader("parakh.report", "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

_BAR_AREA_H = 120.0
_BAR_W = 36
_BAR_GAP = 14


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value)} ms"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


_ENV.filters["ms"] = _ms
_ENV.filters["pct"] = _pct


def _chart_bars(report: Report) -> list[dict[str, float | int | str]]:
    top = max((t.latency_ms for t in report.turns if t.latency_ms is not None), default=0.0)
    bars: list[dict[str, float | int | str]] = []
    for pos, turn in enumerate(report.turns):
        height = 0.0 if turn.latency_ms is None or top <= 0 else turn.latency_ms / top * _BAR_AREA_H
        bars.append(
            {
                "x": _BAR_GAP + pos * (_BAR_W + _BAR_GAP),
                "height": round(height, 1),
                "y": round(_BAR_AREA_H - height + 20, 1),
                "label": _ms(turn.latency_ms),
                "turn": turn.index + 1,
            }
        )
    return bars


def render_html(report: Report) -> str:
    turns = [{"turn": t, "words": mark_misses(t.reference, t.transcript)} for t in report.turns]
    width = _BAR_GAP + max(len(report.turns), 1) * (_BAR_W + _BAR_GAP)
    return _ENV.get_template("report.html.j2").render(
        r=report,
        turns=turns,
        bars=_chart_bars(report),
        chart_w=width,
        chart_h=_BAR_AREA_H + 44,
        bar_w=_BAR_W,
    )


def write_report_html(report: Report, run_dir: Path) -> Path:
    path = run_dir / "report.html"
    path.write_text(render_html(report), encoding="utf-8")
    return path

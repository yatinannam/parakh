"""Compare several runs: compare.json and one self-contained compare.html."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from parakh.degrade.presets import PRESET_ORDER
from parakh.report.html import ENV
from parakh.report.model import Report


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


_BAR_AREA_H = 120.0
_BAR_W = 56
_BAR_GAP = 18
_UNREACHED = "turn not reached"


class CompareRow(_Strict):
    scenario_id: str
    scenario_title: str
    preset: str
    run_id: str
    # Relative to the comparison directory, with forward slashes.
    report_href: str
    status: str
    loose_wer: float | None
    strict_wer: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    stop_p50_ms: float | None
    did_not_yield: int
    false_barge_ins: int
    # A turn is reached unless its report marks it "turn not reached". Defaults keep
    # compare.json files written before these fields loadable.
    turns_reached: int = 0
    turns_total: int = 0


class Comparison(_Strict):
    schema_version: Literal[1] = 1
    created_at: str
    rows: list[CompareRow]


def _preset_rank(name: str) -> int:
    return PRESET_ORDER.index(name) if name in PRESET_ORDER else len(PRESET_ORDER)


def build_comparison(runs: list[tuple[Report, Path]], out_dir: Path) -> Comparison:
    """One row per run, sorted by scenario id, then preset order (unknown presets last)."""
    rows: list[CompareRow] = []
    for report, run_dir in runs:
        m = report.metrics
        href = Path(os.path.relpath(run_dir / "report.html", out_dir)).as_posix()
        rows.append(
            CompareRow(
                scenario_id=report.scenario_id,
                scenario_title=report.scenario_title,
                preset=report.preset,
                run_id=report.run_id,
                report_href=href,
                status=report.status,
                loose_wer=m.loose_wer,
                strict_wer=m.strict_wer,
                latency_p50_ms=m.latency.p50_ms,
                latency_p95_ms=m.latency.p95_ms,
                stop_p50_ms=None if m.stop_latency is None else m.stop_latency.p50_ms,
                did_not_yield=m.did_not_yield,
                false_barge_ins=len(m.false_barge_in_ms),
                turns_reached=sum(t.latency_reason != _UNREACHED for t in report.turns),
                turns_total=len(report.turns),
            )
        )
    rows.sort(key=lambda r: (r.scenario_id, _preset_rank(r.preset)))
    created = datetime.now(UTC).isoformat(timespec="seconds")
    return Comparison(created_at=created, rows=rows)


def _bars(rows: list[CompareRow], values: list[float | None], label: str) -> dict[str, Any]:
    """Inline-SVG bar chart data: one bar per row, in row (preset) order."""
    top = max((v for v in values if v is not None), default=0.0)
    bars: list[dict[str, float | int | str | bool]] = []
    for pos, (row, value) in enumerate(zip(rows, values, strict=True)):
        height = 0.0 if value is None or top <= 0 else value / top * _BAR_AREA_H
        partial = row.status != "completed"
        shown = "n/a" if value is None else label.format(value)
        bars.append(
            {
                "x": _BAR_GAP + pos * (_BAR_W + _BAR_GAP),
                "y": round(_BAR_AREA_H - height + 20, 1),
                "height": round(height, 1),
                "label": row.status if partial else shown,
                "partial": partial,
                "name": row.preset,
            }
        )
    return {
        "bars": bars,
        "width": _BAR_GAP + max(len(rows), 1) * (_BAR_W + _BAR_GAP),
        "height": _BAR_AREA_H + 44,
    }


def _groups(comparison: Comparison) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for row in comparison.rows:
        if not groups or groups[-1]["id"] != row.scenario_id:
            groups.append({"id": row.scenario_id, "title": row.scenario_title, "rows": []})
        groups[-1]["rows"].append(row)
    for group in groups:
        rows: list[CompareRow] = group["rows"]
        wer = [None if r.loose_wer is None else r.loose_wer * 100 for r in rows]
        group["wer_chart"] = _bars(rows, wer, "{:.1f}%")
        group["latency_chart"] = _bars(rows, [r.latency_p50_ms for r in rows], "{:.0f} ms")
        group["has_partial"] = any(r.status != "completed" for r in rows)
    return groups


def render_comparison(comparison: Comparison) -> str:
    return ENV.get_template("compare.html.j2").render(
        c=comparison, groups=_groups(comparison), bar_w=_BAR_W
    )


def write_comparison(comparison: Comparison, out_dir: Path) -> Path:
    """Write compare.json and compare.html into out_dir; return the HTML path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compare.json").write_text(
        comparison.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    path = out_dir / "compare.html"
    path.write_text(render_comparison(comparison), encoding="utf-8")
    return path

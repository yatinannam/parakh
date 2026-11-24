from pathlib import Path

from parakh.report.model import TURN_NOT_REACHED, JudgeReport
from parakh.report.rescore import rescore_report
from parakh.scenario import Scenario, load_scenario
from tests.unit.judge.helpers import report, turn

SCENARIO = """\
schema_version: 1
id: rescore-01
title: Rescore
language: {lang}
domain: clinic
clock: "2026-11-19T10:00:00+05:30"
caller:
  voice: hi-IN-SwaraNeural
turns:
  - say: "{say}"
"""

URDU = "میں جانا"


def _scenario(tmp_path: Path, say: str, lang: str = "hi-en") -> Scenario:
    path = tmp_path / "dir with space" / "s.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(SCENARIO.format(lang=lang, say=say), encoding="utf-8")
    return load_scenario(path)


def test_rescore_uses_current_reference(tmp_path: Path) -> None:
    old = turn(0, say="a b", heard="a b")
    base = report(old).model_copy(
        update={"judge": JudgeReport(status="skipped", prompt_version="v", reason="r")}
    )
    out = rescore_report(base, _scenario(tmp_path, "a b c"))
    assert out.turns[0].reference == "a b c"
    assert out.turns[0].loose_wer is not None and out.turns[0].loose_wer > 0
    assert out.metrics.loose_wer is not None and out.metrics.loose_wer > 0
    assert out.turns[0].latency_ms == old.latency_ms
    assert out.judge == base.judge and out.status == base.status


def test_rescore_marks_urdu_turns(tmp_path: Path) -> None:
    out = rescore_report(report(turn(0, say="a b", heard=URDU)), _scenario(tmp_path, "a b"))
    assert out.metrics.script_unsupported_turns == [0]


def test_rescore_leaves_unreached_and_extra_turns(tmp_path: Path) -> None:
    unreached = turn(0, heard="").model_copy(
        update={"latency_reason": TURN_NOT_REACHED, "strict_wer": None, "loose_wer": None}
    )
    extra = turn(1, say="zzz", heard="zzz")
    out = rescore_report(report(unreached, extra), _scenario(tmp_path, "a b"))
    assert out.turns[0].loose_wer is None
    assert out.turns[1] == extra

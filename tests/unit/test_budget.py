from pathlib import Path

from parakh.budget.estimate import estimate
from parakh.scenario import load_scenario

EXAMPLE = Path(__file__).parents[2] / "scenarios" / "hinglish" / "clinic-book-hinglish-01.yaml"


def test_budget_example():
    est = estimate([load_scenario(EXAMPLE)])
    assert est.stt_calls == 4
    assert est.llm_calls == 5
    assert est.within_limits is True
    assert est.notes == []


def test_budget_over_limit():
    est = estimate([load_scenario(EXAMPLE)] * 600)
    assert est.within_limits is False
    assert any("rpd" in note for note in est.notes)
    assert "rpd: 2400 STT calls > 2000" in est.notes


def test_budget_uses_clip_seconds_when_given():
    est = estimate([load_scenario(EXAMPLE)], clip_seconds=[1.0, 2.0, 3.0, 4.0])
    assert est.audio_seconds == 10.0

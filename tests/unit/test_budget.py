from pathlib import Path

from parakh.budget.estimate import estimate
from parakh.scenario import load_scenario

EXAMPLE = Path(__file__).parents[2] / "scenarios" / "hinglish" / "clinic-book-hinglish-01.yaml"


def test_budget_example():
    est = estimate([load_scenario(EXAMPLE)])
    assert est.stt_calls == 12
    assert est.llm_calls == 13
    assert est.within_limits is True
    assert est.notes == []


def test_budget_over_limit():
    est = estimate([load_scenario(EXAMPLE)] * 600)
    assert est.within_limits is False
    assert any("rpd" in note for note in est.notes)
    assert "rpd: 7200 STT calls > 2000" in est.notes


def test_budget_uses_clip_seconds_when_given():
    est = estimate([load_scenario(EXAMPLE)], clip_seconds=[1.0, 2.0, 3.0, 4.0])
    assert est.audio_seconds == 10.0


def test_budget_counts_observed_rates():
    est = estimate([load_scenario(EXAMPLE)])
    assert (est.stt_calls, est.llm_calls) == (12, 13)


def test_budget_multiplies_presets():
    scenario = load_scenario(EXAMPLE)
    est = estimate([scenario], presets=5)
    assert (est.stt_calls, est.llm_calls) == (60, 65)
    assert est.audio_seconds == 5 * estimate([scenario]).audio_seconds
    assert estimate([scenario], clip_seconds=[1.0, 2.0], presets=2).audio_seconds == 6.0

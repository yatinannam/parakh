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


def test_estimate_counts_judge_and_tokens():
    est = estimate([load_scenario(EXAMPLE)])
    assert est.judge_calls == 1
    assert est.llm_tokens == 13 * 1500
    assert estimate([load_scenario(EXAMPLE)], presets=3).judge_calls == 3
    assert estimate([load_scenario(EXAMPLE)], judge=False).judge_calls == 0


def test_estimate_notes_tokens_and_judge_limits():
    scenario = load_scenario(EXAMPLE)
    est = estimate([scenario] * 11)  # 143 LLM calls: 214,500 tokens > 200,000
    assert est.within_limits is False
    assert any("tpd" in note for note in est.notes)
    est = estimate([scenario] * 1001, judge=False)
    assert not any("judge" in note for note in est.notes)
    est = estimate([scenario] * 1001)
    assert any("judge" in note for note in est.notes)


def test_judge_limit_comes_from_the_config():
    from parakh.budget.estimate import judge_rpd
    from parakh.judge.providers import load_config

    assert judge_rpd() == load_config().providers[0].rpd

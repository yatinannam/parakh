import re
from datetime import datetime
from pathlib import Path

import pytest

from agents.clinic_agent.config import load_config
from parakh.budget.estimate import GROQ_LLM_ASSUMED, GROQ_STT_LIMITS, estimate
from parakh.scenario import load_scenario
from parakh.scenario.model import Scenario
from parakh.score.normalize import normalize

ROOT = Path(__file__).resolve().parents[2] / "scenarios"
LANG_OF = {"hinglish": "hi-en", "kannada_en": "kn-en", "tamil_en": "ta-en"}
PROFILE_OF = {"kannada_en": "kn", "tamil_en": "ta"}
PACKS: dict[str, list[Scenario]] = {
    d: [load_scenario(p) for p in sorted((ROOT / d).glob("*.yaml"))] for d in LANG_OF
}
ALL = [s for pack in PACKS.values() for s in pack]
PACK_PARAMS = list(LANG_OF)
LEGACY = {"clinic-book-hinglish-01", "clinic-bargein-hinglish-01"}


def test_pack_has_at_least_14_hinglish_scenarios():
    assert len(PACKS["hinglish"]) >= 14


@pytest.mark.parametrize("pack", ["kannada_en", "tamil_en"])
def test_kn_ta_packs_have_six_each(pack):
    assert len(PACKS[pack]) == 6


@pytest.mark.parametrize("pack", PACK_PARAMS)
def test_language_matches_directory(pack):
    for s in PACKS[pack]:
        assert s.language == LANG_OF[pack], s.id


@pytest.mark.parametrize("pack", ["kannada_en", "tamil_en"])
def test_caller_voice_differs_from_agent_profile_voice(pack):
    agent_voice = load_config(profile=PROFILE_OF[pack]).tts_voice
    for s in PACKS[pack]:
        assert s.caller.voice != agent_voice, s.id


@pytest.mark.parametrize("pack", PACK_PARAMS)
def test_ids_unique_and_match_file_stems(pack):
    stems = sorted(p.stem for p in (ROOT / pack).glob("*.yaml"))
    ids = sorted(s.id for s in PACKS[pack])
    assert ids == stems
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("pack", PACK_PARAMS)
def test_every_scenario_has_goal_and_pack_limits(pack):
    for s in PACKS[pack]:
        assert s.goal and s.goal.strip(), s.id
        assert s.limits.max_turns == 12, s.id
        assert s.limits.response_timeout_s == 15, s.id
        assert s.limits.call_timeout_s == 180, s.id
        assert s.domain == "clinic", s.id
        assert s.agent_speaks_first is True, s.id
        assert 3 <= len(s.turns) <= 6, s.id


def test_clock_matches_agent_config():
    clock = datetime.fromisoformat(load_config().clock)
    for s in ALL:
        assert s.clock == clock, s.id


def test_roman_only_voices_get_roman_text():
    for s in ALL:
        if s.caller.voice.startswith("en-IN"):
            for t in s.turns:
                assert not re.search(r"[^ -~]", t.say), s.id


def _phone_tokens(pack: list[Scenario]) -> list[tuple[str, str]]:
    return [
        (s.id, t.reference) for s in pack for t in s.turns if any(c.isdigit() for c in t.reference)
    ]


@pytest.mark.parametrize("pack", PACK_PARAMS)
def test_phone_refs_normalise_to_ten_digits(pack):
    pairs = _phone_tokens(PACKS[pack])
    assert pairs
    for sid, ref in pairs:
        digits = [tok for tok in normalize(ref).tokens if tok.isdigit()]
        assert len(digits) == 1 and len(digits[0]) == 10, (sid, ref)


def test_phone_numbers_distinct_across_packs():
    # The two M1/M2 scenarios share one number (their turns are frozen); every
    # other scenario owns numbers that appear nowhere else in any pack.
    owner: dict[str, str] = {}
    for sid, ref in _phone_tokens(ALL):
        for n in re.findall(r"\d{10}", ref):
            if sid in LEGACY and owner.get(n) in LEGACY | {None}:
                owner[n] = sid
                continue
            assert owner.get(n, sid) == sid, (n, sid, owner[n])
            owner[n] = sid


def test_ref_digits_match_goal_phone():
    # The last 10-digit number in the refs equals the goal's last number. A digit
    # correction scenario scripts the wrong number in its ref on purpose and speaks
    # the fix in words, so its goal number differs from the ref in one digit only.
    for s in ALL:
        ref_nums = [n for t in s.turns for n in re.findall(r"\d{10}", t.reference)]
        goal_nums = re.findall(r"\d{10}", s.goal or "")
        assert ref_nums and goal_nums, s.id
        last_ref, last_goal = ref_nums[-1], goal_nums[-1]
        if "corrects the last digit" in (s.goal or ""):
            assert sum(a != b for a, b in zip(last_ref, last_goal, strict=True)) == 1, s.id
        else:
            assert last_ref == last_goal, s.id


def test_at_least_two_barge_in_scenarios():
    assert sum(any(t.barge_in for t in s.turns) for s in PACKS["hinglish"]) >= 2
    for pack in ("kannada_en", "tamil_en"):
        assert any(any(t.barge_in for t in s.turns) for s in PACKS[pack])


def test_pack_budget_within_limits_for_one_preset():
    est = estimate(ALL, presets=1)
    assert est.stt_calls <= GROQ_STT_LIMITS["rpd"]
    assert est.llm_calls <= GROQ_LLM_ASSUMED["rpd"]

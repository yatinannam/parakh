import re
from datetime import datetime
from pathlib import Path

from agents.clinic_agent.config import load_config
from parakh.budget.estimate import GROQ_LLM_ASSUMED, GROQ_STT_LIMITS, estimate
from parakh.scenario import load_scenario
from parakh.score.normalize import normalize

PACK_DIR = Path(__file__).resolve().parents[2] / "scenarios" / "hinglish"
PACK = [load_scenario(p) for p in sorted(PACK_DIR.glob("*.yaml"))]
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def test_pack_has_at_least_14_hinglish_scenarios():
    assert len(PACK) >= 14


def test_ids_unique_and_match_file_stems():
    stems = sorted(p.stem for p in PACK_DIR.glob("*.yaml"))
    ids = sorted(s.id for s in PACK)
    assert ids == stems
    assert len(set(ids)) == len(ids)


def test_every_scenario_has_goal_and_pack_limits():
    for s in PACK:
        assert s.goal and s.goal.strip(), s.id
        assert s.limits.max_turns == 12, s.id
        assert s.limits.response_timeout_s == 15, s.id
        assert s.limits.call_timeout_s == 180, s.id
        assert s.language == "hi-en" and s.domain == "clinic", s.id
        assert s.agent_speaks_first is True, s.id
        assert 3 <= len(s.turns) <= 6, s.id


def test_clock_matches_agent_config():
    clock = datetime.fromisoformat(load_config().clock)
    for s in PACK:
        assert s.clock == clock, s.id


def test_roman_only_voices_get_roman_text():
    for s in PACK:
        if s.caller.voice.startswith("en-IN"):
            for t in s.turns:
                assert not _DEVANAGARI.search(t.say), s.id


def _phone_tokens() -> list[tuple[str, str]]:
    out = []
    for s in PACK:
        for t in s.turns:
            if any(c.isdigit() for c in t.reference):
                out.append((s.id, t.reference))
    return out


def test_phone_refs_normalise_to_ten_digits():
    pairs = _phone_tokens()
    assert pairs
    for sid, ref in pairs:
        digits = [tok for tok in normalize(ref).tokens if tok.isdigit()]
        assert len(digits) == 1 and len(digits[0]) == 10, (sid, ref)


def test_phone_numbers_distinct():
    # The two M1/M2 scenarios share one number (their turns are frozen); every
    # other scenario owns numbers that appear nowhere else in the pack.
    legacy = {"clinic-book-hinglish-01", "clinic-bargein-hinglish-01"}
    owner: dict[str, str] = {}
    for sid, ref in _phone_tokens():
        for n in re.findall(r"\d{10}", ref):
            if sid in legacy and owner.get(n) in legacy | {None}:
                owner[n] = sid
                continue
            assert owner.get(n, sid) == sid, (n, sid, owner[n])
            owner[n] = sid


def test_at_least_two_barge_in_scenarios():
    assert sum(any(t.barge_in for t in s.turns) for s in PACK) >= 2


def test_pack_budget_within_limits_for_one_preset():
    est = estimate(PACK, presets=1)
    assert est.stt_calls <= GROQ_STT_LIMITS["rpd"]
    assert est.llm_calls <= GROQ_LLM_ASSUMED["rpd"]

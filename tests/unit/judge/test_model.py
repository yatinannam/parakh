import json

import pytest

from parakh.judge.model import FLAGS, JudgeScores, parse_scores

BASE = {
    "understanding": 4,
    "language_match": 5,
    "task_progress": 3,
    "politeness": 5,
    "interruption_handling": None,
    "rationale": "Fine call.",
    "flags": [],
}


def _obj(**over: object) -> str:
    return json.dumps({**BASE, **over})


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        (_obj(), True),
        ("```json\n" + _obj() + "\n```", True),
        (_obj(flags=["off_script", "made_up_flag"]), True),
        ("Here you go: " + _obj(), False),
        (_obj() + " hope that helps", False),
        (json.dumps({"scores": BASE}), False),
        (_obj(understanding=0), False),
        (_obj(understanding=6), False),
        (_obj(understanding="4"), False),
        (_obj(understanding=True), False),
        (_obj(**{"pass": True}), False),
        (_obj(rationale="x" * 601), False),
        (_obj(rationale="x" * 600), True),
        ("[1, 2]", False),
        ("not json", False),
    ],
)
def test_reply_shapes(text: str, ok: bool) -> None:
    if ok:
        assert isinstance(parse_scores(text, has_barge_in=False), JudgeScores)
    else:
        with pytest.raises(ValueError):
            parse_scores(text, has_barge_in=False)


def test_unknown_flag_dropped() -> None:
    s = parse_scores(_obj(flags=["off_script", "bogus"]), has_barge_in=False)
    assert s.flags == ["off_script"]
    assert "off_script" in FLAGS and len(FLAGS) == 8


def test_interruption_forced_null_without_barge_in() -> None:
    s = parse_scores(_obj(interruption_handling=4), has_barge_in=False)
    assert s.interruption_handling is None


def test_interruption_key_may_be_omitted() -> None:
    body = {k: v for k, v in BASE.items() if k != "interruption_handling"}
    assert parse_scores(json.dumps(body), has_barge_in=False).interruption_handling is None
    with pytest.raises(ValueError):
        parse_scores(json.dumps(body), has_barge_in=True)


def test_barge_in_needs_a_rating() -> None:
    with pytest.raises(ValueError):
        parse_scores(_obj(interruption_handling=None), has_barge_in=True)
    assert parse_scores(_obj(interruption_handling=2), has_barge_in=True).interruption_handling == 2
    with pytest.raises(ValueError):
        parse_scores(_obj(interruption_handling=9), has_barge_in=True)

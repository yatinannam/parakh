"""WER engine: strict, loose, CER, turn grouping, conversation level."""

import pytest

from parakh.score.wer import (
    conversation_wer,
    group_by_turn,
    loose_cer,
    loose_wer,
    strict_wer,
)

REF_MIXED = "mujhe doctor rao ke saath appointment chahiye"
HYP_DEVA = "मुझे डॉक्टर राव के साथ अपॉइंटमेंट चाहिए"
URDU = "مجھے"


def test_identical_is_zero() -> None:
    assert strict_wer("kal subah", "kal subah") == 0.0
    assert loose_wer("kal subah", "kal subah") == 0.0


def test_known_edits() -> None:
    assert strict_wer("a b c d", "a x c") == 0.5
    assert loose_wer("a b c d", "a x c") == 0.5


def test_empty_rules() -> None:
    assert strict_wer("", "x") is None
    assert strict_wer("a b", "") == 1.0
    assert loose_wer("", "x") is None
    assert loose_wer("a b", "") == 1.0
    assert loose_cer("", "x") is None
    assert loose_cer("ab", "") == 1.0


def test_code_mixed_loose_vs_strict() -> None:
    assert loose_wer(REF_MIXED, HYP_DEVA) == 0.0
    assert strict_wer(REF_MIXED, HYP_DEVA) == 1.0


def test_loose_cer() -> None:
    assert loose_cer("abc", "abd") == pytest.approx(1 / 3)


def test_group_by_turn() -> None:
    items = [(1200.0, "a"), (6100.0, "b"), (6900.0, "c"), (12000.0, "d"), (-5.0, "z")]
    assert group_by_turn([0, 5000, 10000], items) == [["z", "a"], ["b", "c"], ["d"]]
    assert group_by_turn([0, 5000], []) == [[], []]
    assert group_by_turn([], items) == []


def test_conversation_level_merges_split_turns() -> None:
    summary = conversation_wer(["kal subah aana"], [["kal", "subah aana"]])
    assert summary.strict_wer == 0.0
    assert summary.loose_wer == 0.0
    assert summary.reason is None
    assert summary.script_unsupported_turns == []


def test_no_transcript() -> None:
    for hyps in ([[]], [[""]], []):
        summary = conversation_wer(["a"], hyps)
        assert summary.strict_wer is None
        assert summary.loose_wer is None
        assert summary.loose_cer is None
        assert summary.reason == "agent exposed no caller transcript"
        assert summary.script_unsupported_turns == []


def test_urdu_turn_excluded() -> None:
    summary = conversation_wer(
        ["kal subah", "mujhe", "shaam ko"],
        [["kal subah"], [URDU], ["shaam ko"]],
    )
    assert summary.script_unsupported_turns == [1]
    assert summary.loose_wer == 0.0
    assert summary.loose_cer == 0.0
    assert summary.strict_wer is not None and summary.strict_wer > 0.0

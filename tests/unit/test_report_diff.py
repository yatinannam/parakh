from parakh.report.diff import mark_misses


def test_substitution_marked():
    assert mark_misses("kal subah", "kal shaam") == [("kal", False), ("shaam", True)]


def test_all_match():
    assert mark_misses("haan ji", "haan ji") == [("haan", False), ("ji", False)]


def test_insertion_marked_and_deletion_ignored():
    assert mark_misses("ek do teen", "ek do char teen") == [
        ("ek", False),
        ("do", False),
        ("char", True),
        ("teen", False),
    ]
    assert mark_misses("ek do teen", "ek teen") == [("ek", False), ("teen", False)]


def test_spelling_variant_is_not_a_miss():
    assert mark_misses("theek hai", "thik hai") == [("thik", False), ("hai", False)]


def test_empty_inputs():
    assert mark_misses("", "") == []
    assert mark_misses("kal", "") == []
    assert mark_misses("", "kal") == [("kal", True)]


def test_devanagari_matches_roman():
    assert mark_misses("haan", "हाँ") == [("हाँ", False)]


def test_case_and_punctuation_kept_but_not_a_miss():
    assert mark_misses("kal subah", "Kal, subah!") == [("Kal,", False), ("subah!", False)]

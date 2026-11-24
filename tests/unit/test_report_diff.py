from parakh.report.diff import mark_misses


def test_substitution_marked():
    assert mark_misses("kal subah", "kal shaam") == [("kal", False), ("shaam", True)]


def test_all_match():
    assert mark_misses("haan ji", "haan ji") == [("haan", False), ("ji", False)]


def test_insertion_marked_and_deletion_ignored():
    # Not number words: "ek do teen" is one number to the normaliser (see the digit tests).
    assert mark_misses("kal subah aana", "kal subah jaldi aana") == [
        ("kal", False),
        ("subah", False),
        ("jaldi", True),
        ("aana", False),
    ]
    assert mark_misses("kal subah aana", "kal aana") == [("kal", False), ("aana", False)]


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


def test_split_digit_run_matches_the_whole_number():
    # Whisper heard the phone number as three groups. Loose WER joins adjacent digits
    # and scored the turn 0.0 %, so the marks must not flag the groups (first live run).
    assert mark_misses("haan mera number hai 9845012345", "हाँ, मेरा नमबर है 9845 012 345") == [
        ("हाँ,", False),
        ("मेरा", False),
        ("नमबर", False),
        ("है", False),
        ("9845", False),
        ("012", False),
        ("345", False),
    ]


def test_spoken_digits_match_the_whole_number():
    said = "nine eight four five zero one two three four five"
    assert mark_misses("9845012345", said) == [(word, False) for word in said.split()]


def test_wrong_digit_run_is_marked_as_a_whole():
    assert mark_misses("number 9845012345", "number 9845 012 346") == [
        ("number", False),
        ("9845", True),
        ("012", True),
        ("346", True),
    ]
    # Loose WER reads Hindi number words as digits too: "ek do teen" is 123, not 1243.
    assert mark_misses("ek do teen", "ek do char teen") == [
        ("ek", True),
        ("do", True),
        ("char", True),
        ("teen", True),
    ]


def test_mark_misses_uses_language():
    # ondu eradu are Kannada number words: 12 in kn-en, plain words in hi-en.
    assert mark_misses("ondu eradu", "1 2", "kn-en") == [("1", False), ("2", False)]
    assert mark_misses("ondu eradu", "1 2") == [("1", True), ("2", True)]
    assert mark_misses("venum", "வேணும்", "ta-en") == [("வேணும்", False)]

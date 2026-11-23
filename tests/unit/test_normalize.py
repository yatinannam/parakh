"""Script-tolerant normaliser: golden pairs, number words, properties, Urdu flag."""

import re
import string
from collections import Counter
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from parakh.score.normalize import (
    VARIANTS,
    Normalized,
    _loose_key,
    normalize,
    strict_tokens,
    tokens_equal,
)
from parakh.score.wer import loose_wer

_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "golden" / "normalizer_pairs.yaml"
GOLDEN = yaml.safe_load(_GOLDEN_PATH.read_text(encoding="utf-8"))

GROUP_MINIMUMS = {"hinglish": 55, "loanword": 25, "variant": 20, "number": 25, "no_match": 30}


def phrase_match(a: str, b: str) -> bool:
    ta, tb = normalize(a).tokens, normalize(b).tokens
    return len(ta) == len(tb) and all(tokens_equal(x, y) for x, y in zip(ta, tb, strict=True))


def test_golden_counts() -> None:
    pairs = GOLDEN["must_match"] + GOLDEN["must_not_match"]
    assert len(pairs) >= 150
    assert all(len(p) == 3 for p in pairs)
    counts = Counter(p[2] for p in pairs)
    assert set(counts) == set(GROUP_MINIMUMS)
    for group, minimum in GROUP_MINIMUMS.items():
        assert counts[group] >= minimum, (group, counts[group])
    assert all(p[2] == "no_match" for p in GOLDEN["must_not_match"])
    assert all(p[2] != "no_match" for p in GOLDEN["must_match"])


def test_golden_pairs_unique() -> None:
    seen = [tuple(p[:2]) for p in GOLDEN["must_match"] + GOLDEN["must_not_match"]]
    seen += [(g["a"], g["b"]) for g in GOLDEN["known_gaps"]]
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("a,b", [p[:2] for p in GOLDEN["must_match"]])
def test_must_match(a: str, b: str) -> None:
    assert phrase_match(a, b)


@pytest.mark.parametrize("a,b", [p[:2] for p in GOLDEN["must_not_match"]])
def test_must_not_match(a: str, b: str) -> None:
    assert not phrase_match(a, b)


@pytest.mark.parametrize(
    "a,b,expect,why", [(g["a"], g["b"], g["expect"], g["why"]) for g in GOLDEN["known_gaps"]]
)
@pytest.mark.xfail(strict=True)
def test_known_gap(a: str, b: str, expect: str, why: str) -> None:
    assert expect in ("match", "no_match")
    assert phrase_match(a, b) == (expect == "match"), why


@pytest.mark.parametrize(
    "a", [p[0] for p in GOLDEN["must_match"]] + [p[1] for p in GOLDEN["must_match"]]
)
def test_idempotent(a: str) -> None:
    t = normalize(a).tokens
    assert normalize(" ".join(t)).tokens == t


def test_urdu_flagged() -> None:
    assert normalize("مجھے").script_unsupported


def test_empty() -> None:
    assert normalize("") == Normalized(tokens=[], script_unsupported=False)


def test_strict_tokens_strip_danda() -> None:
    assert strict_tokens("ठीक है।") == ["ठीक", "है"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("two hundred", ["200"]),
        ("two hundred fifty", ["250"]),
        ("three hundred and five", ["305"]),
        ("two hundred fifty five", ["255"]),
        ("hundred", ["100"]),
    ],
)
def test_hundreds(text: str, expected: list[str]) -> None:
    assert normalize(text).tokens == expected


def test_hundreds_match_digits() -> None:
    assert phrase_match("two hundred", "200")


@pytest.mark.parametrize("joiner", [chr(0x200C), chr(0x200D)])
@pytest.mark.parametrize("word", ["किताब", "क्ष"])
def test_zero_width_joiners_ignored(word: str, joiner: str) -> None:
    mid = len(word) // 2
    joined = word[:mid] + joiner + word[mid:]
    assert normalize(joined).tokens == normalize(word).tokens
    assert len(normalize(joined).tokens) == 1


@pytest.mark.parametrize(
    "word,value",
    [
        ("gyarah", "11"),
        ("barah", "12"),
        ("bees", "20"),
        ("bis", "20"),
        ("बीस", "20"),
        ("pachees", "25"),
        ("pachaas", "50"),
        ("sau", "100"),
        ("teen", "3"),
        ("tiin", "3"),
        ("तीन", "3"),
        ("shunya", "0"),
        ("शून्य", "0"),
    ],
)
def test_hindi_tens(word: str, value: str) -> None:
    assert normalize(word).tokens == [value]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("do sau pachaas", ["250"]),
        ("ek sau ek", ["101"]),
        ("teen sau", ["300"]),
        ("sau", ["100"]),
        ("दो सौ पचास", ["250"]),
    ],
)
def test_sau_works_like_hundred(text: str, expected: list[str]) -> None:
    assert normalize(text).tokens == expected


def test_devanagari_numerals() -> None:
    assert normalize("९८४५ ०१२").tokens == ["9845012"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("nine oh eight", ["908"]),
        ("nine o eight", ["908"]),
        ("nine eight oh oh one", ["98001"]),
        ("oh okay", ["o", "oke"]),
        ("nine oh", ["9", "o"]),
        ("oh nine", ["o", "9"]),
    ],
)
def test_oh_is_zero_only_between_digits(text: str, expected: list[str]) -> None:
    assert normalize(text).tokens == expected


@pytest.mark.parametrize(
    "word,key",
    [("subah", "suba"), ("toh", "to"), ("woh", "vo"), ("kah", "kah"), ("yah", "ye")],
)
def test_final_h(word: str, key: str) -> None:
    assert normalize(word).tokens == [key]


def test_variants_are_fixed_points() -> None:
    for spelling, canonical in VARIANTS.items():
        assert _loose_key(canonical) == canonical, spelling
        assert canonical not in VARIANTS, spelling


_ALPHABET = (
    string.ascii_letters
    + string.digits
    + " .,?!-'"
    + "".join(chr(c) for c in range(0x0900, 0x0980))
    + "".join(chr(c) for c in range(0x0600, 0x0700))
    + "‌‍"
)
# Golden words joined at random, so the rules (numbers, oh, double) meet each other too.
_WORDS = sorted(
    {
        word
        for pair in GOLDEN["must_match"] + GOLDEN["must_not_match"]
        for side in pair[:2]
        for word in side.split()
    }
)
TEXT = st.one_of(
    st.text(alphabet=_ALPHABET, max_size=40),
    st.lists(st.sampled_from(_WORDS), max_size=8).map(" ".join),
)


@given(text=TEXT)
@settings(derandomize=True, database=None, max_examples=200, deadline=None)
def test_property_never_raises_and_tokens_are_ascii(text: str) -> None:
    for token in normalize(text).tokens:
        assert re.fullmatch(r"[a-z0-9]+", token), token


@given(text=TEXT)
@settings(derandomize=True, database=None, max_examples=200, deadline=None)
def test_property_idempotent(text: str) -> None:
    t = normalize(text).tokens
    assert normalize(" ".join(t)).tokens == t


@given(text=TEXT)
@settings(derandomize=True, database=None, max_examples=200, deadline=None)
def test_property_self_match(text: str) -> None:
    assert loose_wer(text, text) in (0.0, None)


@given(a=TEXT, b=TEXT)
@settings(derandomize=True, database=None, max_examples=200, deadline=None)
def test_property_tokens_equal_symmetric(a: str, b: str) -> None:
    for x in [a, *normalize(a).tokens]:
        for y in [b, *normalize(b).tokens]:
            assert tokens_equal(x, y) == tokens_equal(y, x)

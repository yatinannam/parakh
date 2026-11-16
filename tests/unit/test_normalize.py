"""Script-tolerant normaliser: golden pairs, idempotence, Urdu flag."""

from pathlib import Path

import pytest
import yaml

from parakh.score.normalize import Normalized, normalize, strict_tokens, tokens_equal

_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "golden" / "normalizer_pairs.yaml"
GOLDEN = yaml.safe_load(_GOLDEN_PATH.read_text(encoding="utf-8"))


def phrase_match(a: str, b: str) -> bool:
    ta, tb = normalize(a).tokens, normalize(b).tokens
    return len(ta) == len(tb) and all(tokens_equal(x, y) for x, y in zip(ta, tb, strict=True))


@pytest.mark.parametrize("a,b", GOLDEN["must_match"])
def test_must_match(a: str, b: str) -> None:
    assert phrase_match(a, b)


@pytest.mark.parametrize("a,b", GOLDEN["must_not_match"])
def test_must_not_match(a: str, b: str) -> None:
    assert not phrase_match(a, b)


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

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

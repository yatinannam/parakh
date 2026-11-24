"""Kannada-English and Tamil-English normaliser: golden pairs, scripts, numbers, properties."""

import json
import re
import string
from collections import Counter
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from parakh.scenario import load_scenario
from parakh.score.normalize import (
    LANGUAGE_VARIANTS,
    LANGUAGES,
    _key_table,
    _loose_key,
    normalize,
    tokens_equal,
)
from parakh.score.tamil import romanize_tamil
from parakh.score.wer import loose_cer, loose_wer

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"


def _load(name: str) -> dict:
    return yaml.safe_load((_GOLDEN_DIR / name).read_text(encoding="utf-8"))


GOLDEN = {"kn-en": _load("normalizer_pairs_kn.yaml"), "ta-en": _load("normalizer_pairs_ta.yaml")}
HINGLISH = _load("normalizer_pairs.yaml")
# Tokens the M3a normaliser gave for every Hinglish golden string, recorded before M3b.
HI_TOKENS: dict[str, list[str]] = json.loads(
    (_GOLDEN_DIR / "normalizer_hi_tokens.json").read_text(encoding="utf-8")
)
GROUP_MINIMUMS = {"script": 30, "loanword": 15, "variant": 10, "number": 15, "no_match": 10}


def phrase_match(a: str, b: str, language: str) -> bool:
    ta, tb = normalize(a, language).tokens, normalize(b, language).tokens
    return len(ta) == len(tb) and all(tokens_equal(x, y) for x, y in zip(ta, tb, strict=True))


def _golden(language: str) -> list[tuple[str, str, bool]]:
    g = GOLDEN[language]
    return [(p[0], p[1], True) for p in g["must_match"]] + [
        (p[0], p[1], False) for p in g["must_not_match"]
    ]


@pytest.mark.parametrize("language", list(GOLDEN))
def test_golden_counts_kn_ta(language: str) -> None:
    g = GOLDEN[language]
    pairs = g["must_match"] + g["must_not_match"]
    assert len(pairs) >= 80
    assert all(len(p) == 3 for p in pairs)
    counts = Counter(p[2] for p in pairs)
    assert set(counts) == set(GROUP_MINIMUMS)
    for group, minimum in GROUP_MINIMUMS.items():
        assert counts[group] >= minimum, (group, counts[group])
    assert all(p[2] == "no_match" for p in g["must_not_match"])
    assert all(p[2] != "no_match" for p in g["must_match"])
    seen = [tuple(p[:2]) for p in pairs] + [(k["a"], k["b"]) for k in g["known_gaps"]]
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("a,b,match", _golden("kn-en"))
def test_golden_kn(a: str, b: str, match: bool) -> None:
    assert phrase_match(a, b, "kn-en") == match


@pytest.mark.parametrize("a,b,match", _golden("ta-en"))
def test_golden_ta(a: str, b: str, match: bool) -> None:
    assert phrase_match(a, b, "ta-en") == match


@pytest.mark.parametrize(
    "language,a,b,expect,why",
    [
        (lang, k["a"], k["b"], k["expect"], k["why"])
        for lang in GOLDEN
        for k in GOLDEN[lang]["known_gaps"]
    ],
)
@pytest.mark.xfail(strict=True)
def test_known_gaps_kn_ta(language: str, a: str, b: str, expect: str, why: str) -> None:
    assert expect in ("match", "no_match")
    assert phrase_match(a, b, language) == (expect == "match"), why


@pytest.mark.parametrize("language", list(GOLDEN))
def test_golden_idempotent(language: str) -> None:
    for a, b, _match in _golden(language):
        for side in (a, b):
            t = normalize(side, language).tokens
            assert normalize(" ".join(t), language).tokens == t, side


@pytest.mark.parametrize(
    "text,language",
    [("ಫೋನ್ ೯೮೪೫", "kn-en"), ("ஃபோன் ௯௮௪௫", "ta-en")],
)
def test_native_numerals(text: str, language: str) -> None:
    assert normalize(text, language).tokens == ["fon", "9845"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_native_numerals_every_language(language: str) -> None:
    assert normalize("೯೮೪೫ ௦௧௨", language).tokens == ["9845012"]
    assert normalize("९८४५", language).tokens == ["9845"]


@pytest.mark.parametrize(
    "word,roman",
    [
        ("எனக்கு", "enakku"),
        ("ரொம்ப", "romba"),
        ("நன்றி", "nandri"),
        ("வணக்கம்", "vanakkam"),
        ("பழம்", "pazham"),
    ],
)
def test_tamil_letters_romanise(word: str, roman: str) -> None:
    assert romanize_tamil(word) == roman


@pytest.mark.parametrize(
    "word,roman",
    [
        # A stop is voiced after a nasal: mb, nd, ng, nj (and nd after the retroflex nasal).
        ("ரொம்ப", "romba"),
        ("குழந்தை", "kuzhandai"),
        ("சாயங்காலம்", "saayangaalam"),
        ("கொஞ்சம்", "konjam"),
        ("வேண்டாம்", "vendaam"),
        # A doubled stop is unvoiced.
        ("கிட்ட", "kitta"),
        ("இப்போ", "ippo"),
        ("பத்து", "patthu"),
        ("பச்சை", "pacchai"),
        # A stop at word start is unvoiced.
        ("காலை", "kaalai"),
        ("டாக்டர்", "taaktar"),
        ("தமிழ்", "thamizh"),
        # A single stop between vowels softens: g, s, d, dh, b.
        ("மகன்", "magan"),
        ("பசி", "pasi"),
        ("வீடு", "veedu"),
        ("மாதம்", "maadham"),
        ("கோபம்", "kobam"),
        # ற்ற is tr, ன்ற is ndr; ழ is zh, ள is l, ன and ண are n.
        ("குற்றம்", "kutram"),
        ("இன்று", "indru"),
        ("வழி", "vazhi"),
        ("நாளை", "naalai"),
        ("மணி", "mani"),
        ("என்", "en"),
        # Aytham before ப is f.
        ("ஃபோன்", "fon"),
    ],
)
def test_tamil_voicing_rules(word: str, roman: str) -> None:
    assert romanize_tamil(word) == roman


@pytest.mark.parametrize(
    "text",
    ["", "்", "ா", "ஃ", "௰௱", "க்க்க", "ஒ\u0bd7", "ஸ்ரீ"],
)
def test_tamil_romaniser_is_total(text: str) -> None:
    assert re.fullmatch(r"[a-z]*", romanize_tamil(text))


def test_kannada_no_schwa_drop() -> None:
    assert normalize("ಇಲ್ಲ", "kn-en").tokens == ["ila"]
    assert normalize("ಮಗ", "kn-en").tokens == ["maga"]
    assert normalize("ಧನ್ಯವಾದ", "kn-en").tokens == ["dhanyavada"]


def test_kannada_anusvara_and_short_vowels() -> None:
    assert normalize("ನಂಬರ್ ಸಂಜೆ ಜೊತೆ ನನಗೆ", "kn-en").tokens == ["nambar", "sanje", "jote", "nanage"]
    assert normalize("ಒಂಬತ್ತು", "kn-en").tokens == ["9"]


def test_numbers_by_language() -> None:
    assert normalize("ondu", "kn-en").tokens == ["1"]
    assert normalize("ondu", "hi-en").tokens == ["ondu"]
    assert normalize("ondu", "ta-en").tokens == ["ontu"]  # ta-en devoices, but no number
    assert normalize("rendu", "ta-en").tokens == ["2"]
    assert normalize("rendu", "kn-en").tokens == ["rendu"]
    assert normalize("rendu", "hi-en").tokens == ["rendu"]
    assert normalize("aaru", "kn-en").tokens == normalize("aaru", "ta-en").tokens == ["6"]
    assert normalize("ek do", "kn-en").tokens == ["ek", "do"]
    assert normalize("ek do", "en").tokens == ["ek", "do"]
    for language in LANGUAGES:
        assert normalize("two double five", language).tokens == ["255"]


@pytest.mark.parametrize(
    "text,language,expected",
    [
        ("ippattu ondu", "kn-en", ["21"]),
        ("ಇಪ್ಪತ್ತೊಂದು", "kn-en", ["21"]),
        ("ಇಪ್ಪತ್ಮೂರು", "kn-en", ["23"]),
        ("irubadhu anju", "ta-en", ["25"]),
        ("இருபத்தைந்து", "ta-en", ["25"]),
        ("தொண்ணூற்றொன்பது", "ta-en", ["99"]),
        ("nooru", "kn-en", ["100"]),
        ("nooru", "ta-en", ["100"]),
        ("eradu hundred", "kn-en", ["200"]),
        ("twenty ondu", "kn-en", ["21"]),
        ("bees ek", "hi-en", ["201"]),
    ],
)
def test_tens_and_compounds(text: str, language: str, expected: list[str]) -> None:
    assert normalize(text, language).tokens == expected


def test_en_has_no_hindi_rules() -> None:
    assert normalize("nahin do sau", "en").tokens == ["nahin", "do", "sau"]
    assert normalize("two hundred", "en").tokens == ["200"]
    assert normalize("um uh hm okay", "en").tokens == ["okay"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_roman_fillers_dropped_in_every_language(language: str) -> None:
    assert normalize("um uh hm", language).tokens == []


def test_ta_voicing_collapse() -> None:
    assert normalize("bagavan dosai thambi", "ta-en").tokens == ["pakavan", "tosai", "tampi"]
    assert normalize("pazham", "ta-en").tokens == ["palam"]
    assert normalize("bhayam", "ta-en").tokens == ["payam"]
    assert normalize("bagavan", "kn-en").tokens == ["bagavan"]


def test_number_table_collision_is_an_error() -> None:
    # Per table: ಆರು and Tamil aaru share a key in different tables, which is fine.
    with pytest.raises(ValueError, match="collides"):
        _key_table([(6, ("aaru",)), (7, ("ಆರು",))], "kn-en")


def test_unknown_language_raises() -> None:
    with pytest.raises(ValueError, match="language"):
        normalize("x", "fr")


def test_language_variants_are_fixed_points() -> None:
    for language, table in LANGUAGE_VARIANTS.items():
        for spelling, canonical in table.items():
            assert _loose_key(canonical, language) == canonical, (language, spelling)
            assert canonical not in table, (language, spelling)


def test_wer_takes_language() -> None:
    assert loose_wer("ondu eradu", "1 2", language="kn-en") == 0.0
    assert loose_wer("ondu eradu", "1 2") == 1.0
    assert loose_cer("onnu rendu", "12", language="ta-en") == 0.0


_SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


@pytest.mark.parametrize("pack", ["kannada_en", "tamil_en"])
def test_scenario_say_matches_ref(pack: str) -> None:
    # What the caller says (Dr., spoken digits, punctuation) scores 0 against its reference.
    for path in sorted((_SCENARIOS / pack).glob("*.yaml")):
        scenario = load_scenario(path)
        for turn in scenario.turns:
            assert loose_wer(turn.reference, turn.say, scenario.language) == 0.0, (path, turn.say)


def test_hinglish_unchanged() -> None:
    texts = {s for p in HINGLISH["must_match"] + HINGLISH["must_not_match"] for s in p[:2]}
    texts |= {x for k in HINGLISH["known_gaps"] for x in (k["a"], k["b"])}
    assert texts == set(HI_TOKENS)
    for text in sorted(texts):
        expected = HI_TOKENS[text]
        assert normalize(text).tokens == expected, text
        assert normalize(text, "hi-en").tokens == expected, text
        assert normalize(text, "hi").tokens == expected, text


_ALPHABET = (
    string.ascii_letters
    + string.digits
    + " .,?!-'"
    + "".join(chr(c) for c in range(0x0C80, 0x0D00))
    + "".join(chr(c) for c in range(0x0B80, 0x0C00))
    + "\u200c\u200d"
)
_WORDS = sorted(
    {
        word
        for g in GOLDEN.values()
        for pair in g["must_match"] + g["must_not_match"]
        for side in pair[:2]
        for word in side.split()
    }
)
TEXT = st.one_of(
    st.text(alphabet=_ALPHABET, max_size=40),
    st.lists(st.sampled_from(_WORDS), max_size=8).map(" ".join),
)


@pytest.mark.parametrize("language", ["kn-en", "ta-en"])
@given(text=TEXT)
@settings(derandomize=True, database=None, max_examples=200, deadline=None)
def test_property_ascii_tokens_kn_ta(language: str, text: str) -> None:
    tokens = normalize(text, language).tokens
    for token in tokens:
        assert re.fullmatch(r"[a-z0-9]+", token), token
    assert normalize(" ".join(tokens), language).tokens == tokens
    assert loose_wer(text, text, language=language) in (0.0, None)

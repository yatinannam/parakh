"""Script-tolerant normaliser for Hinglish, Kannada-English and Tamil-English scoring.

Maps native-script and Roman spellings of the same word to one loose phonetic key so a WER
engine can compare them fairly without merging words that really differ. The script decides
the romaniser (`parakh.score.scripts`); the scenario language decides the variants, the
number words and, for ta-en, the voicing collapse. Rule order matters; see the numbered
comments in `normalize`.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from parakh.score import numbers
from parakh.score.scripts import romanize
from parakh.score.variants import KANNADA_VARIANTS, TAMIL_VARIANTS

LANGUAGES: tuple[str, ...] = ("hi-en", "hi", "en", "kn-en", "ta-en")

# Loose key (after the spelling rules) to canonical key. A variant never merges two common
# distinct words: main/mein, aap/up and aur/or stay apart (spec 6.7, EC-43). Pairs that would
# need such a merge are known gaps in tests/golden/normalizer_pairs.yaml.
VARIANTS: dict[str, str] = {
    "nahin": "nahi",
    "nai": "nahi",
    "men": "mein",
    "me": "mein",
    "rav": "rao",
    # M3a: from Groq Whisper transcripts of the synthetic caller and the scenario pack.
    "yeh": "ye",  # yeh, ye, ये
    "yah": "ye",  # यह
    "subha": "suba",  # subah keeps no final h
    "sade": "sadhe",  # saade, saadhe
    "chaie": "chahie",  # chaiye, chahiye
    "parason": "parso",  # परसों
    "parson": "parso",
    "halo": "helo",  # हलो, hello
    "hailo": "helo",  # हैलो
    "bye": "bai",  # बाइ, बाई
    "bay": "bai",  # बाय
    "sory": "sori",  # sorry, सॉरी
    "sauri": "sori",  # सौरी
    "you": "yu",  # थैंक यू
    "okay": "oke",  # ओके
    "ok": "oke",
    "plij": "please",  # प्लीज़
    "plis": "please",  # प्लीस
    "taim": "time",  # टाइम
    "fone": "fon",  # phone, फ़ोन
    # Observed in the M3a live runs (Groq Whisper, language hi).
    "ach": "acha",  # अच्छ, written without the final matra
    "ayar": "ier",  # अयर for the name Iyer
    "dr": "doktor",  # Dr.
    "bae": "bai",  # बाए for bye
    "baie": "bai",  # बइए, बाइए for bye
}

LANGUAGE_VARIANTS: dict[str, dict[str, str]] = {
    "hi-en": VARIANTS,
    "hi": VARIANTS,
    "en": {},
    "kn-en": KANNADA_VARIANTS,
    "ta-en": TAMIL_VARIANTS,
}

# Roman hesitation fillers, dropped by loose key in every language.
_FILLER_KEYS = frozenset({"um", "uh", "hm"})

_PERSO_ARABIC = re.compile("[؀-ۿ]")
_VOWELS = "aeiou"
# ta-en: b to p, d to t, g to k (after the digraphs dh, th, zh, sh, ch and bh).
_DEVOICE = str.maketrans("bdg", "ptk")


@dataclass(frozen=True)
class Normalized:
    tokens: list[str]
    script_unsupported: bool


def _split_tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]", " ", text.lower()).split()


def _drop_y(m: re.Match[str]) -> str:
    return "y" if m.group(1) == m.group(2) else ""


def _spell(token: str) -> str:
    """One pass of the spelling rules; `_loose_key` repeats it until nothing changes."""
    token = re.sub(r"(?:c+h+)+", "ch", token)  # cch, chh, chch (अच्छा) all read ch
    token = re.sub(r"c(?!h)", "k", token)
    token = token.replace("ph", "f").replace("w", "v").replace("q", "k").replace("z", "j")
    # y between two different vowels drops (chahiye, jayega). Between equal vowels it stays,
    # or बताया would read as बता and नया as ना.
    token = re.sub(r"(?<=([aeiou]))y(?=([aeiou]))", _drop_y, token)
    token = token.replace("ee", "i").replace("oo", "u")
    token = re.sub(r"(.)\1+", r"\1", token)
    token = re.sub(r"ov$", "o", token)
    # Final h after a vowel (subah, toh, woh). Three-letter words keep it unless they end in
    # oh, so kah (say) and yah stay apart from ka and ya (or).
    if len(token) >= 4 or token.endswith("oh"):
        token = re.sub(r"(?<=[aeiou])h$", "", token)
    return token


def _devoice(token: str) -> str:
    """The ta-en voicing collapse.

    Tamil script does not mark voicing, so Roman spellings of one word differ there: dh and
    th give t, zh gives l, sh and ch give s, then b, d and g give p, t and k. bh gives p,
    because the b rule alone would make ph, which the spelling rules read as f.
    """
    token = re.sub("[dt]h", "t", token)
    token = token.replace("zh", "l").replace("sh", "s").replace("ch", "s").replace("bh", "p")
    return token.translate(_DEVOICE)


def _spell_ta(token: str) -> str:
    # The collapse runs before the shared rules too, because they read the z of zh as j.
    return _devoice(_spell(_devoice(token)))


@lru_cache(maxsize=16384)
def _loose_key(token: str, language: str = "hi-en") -> str:
    step = _spell_ta if language == "ta-en" else _spell
    while (spelled := step(token)) != token:
        token = spelled
    return LANGUAGE_VARIANTS[language].get(token, token)


def _spelling_key(spelling: str, language: str) -> str:
    (token,) = _split_tokens(romanize(spelling))
    return _loose_key(token, language)


def _key_table(groups: Iterable[tuple[int, Iterable[str]]], language: str) -> dict[str, int]:
    """Loose key of every spelling to its value; two values on one key is a table bug."""
    table: dict[str, int] = {}
    for value, spellings in groups:
        for spelling in spellings:
            key = _spelling_key(spelling, language)
            if table.setdefault(key, value) != value:
                raise ValueError(f"{language} number spelling {spelling!r} collides on {key!r}")
    return table


@dataclass(frozen=True)
class _Numbers:
    """Number words of one language by loose key. For English words the key is a superset
    of the raw token, which keeps the rule idempotent."""

    words: dict[str, int]
    tens: dict[str, int]
    units: dict[str, int]
    double: frozenset[str]
    triple: frozenset[str]
    hundred: frozenset[str]


def _number_table(language: str) -> _Numbers:
    spellings = numbers.SPELLINGS[language]

    def keys(words: Iterable[str]) -> frozenset[str]:
        return frozenset(_spelling_key(w, language) for w in words)

    table = _Numbers(
        words=_key_table(spellings.words, language),
        tens=_key_table(spellings.tens, language),
        units=_key_table(spellings.units, language),
        double=keys(spellings.double),
        triple=keys(spellings.triple),
        hundred=keys(spellings.hundred),
    )
    if not table.tens.keys().isdisjoint(table.words) or not table.hundred.isdisjoint(table.words):
        raise ValueError(f"{language} number word tables overlap")
    return table


# Number words are looked up by loose key, so bees, बीस and bis all give 20; a collision in
# any language's table fails at import. Tables are per language, so Kannada and Tamil aaru
# can both be 6.
_NUMBERS: dict[str, _Numbers] = {language: _number_table(language) for language in LANGUAGES}


def _below_100(keys: list[str], i: int, n: _Numbers, *, zero: bool) -> tuple[int, int] | None:
    """Value and token count of a number word at i: one word, or tens [unit]."""
    if i >= len(keys):
        return None
    key = keys[i]
    if key in n.tens:
        unit = n.units.get(keys[i + 1]) if i + 1 < len(keys) else None
        if unit is not None and 1 <= unit <= 9:
            return n.tens[key] + unit, 2
        return n.tens[key], 1
    value = n.words.get(key)
    if value is not None and (zero or value >= 1):
        return value, 1
    return None


def _hundreds(keys: list[str], i: int, n: _Numbers) -> tuple[int, int] | None:
    """Value and token count of "[X] hundred|sau [and] [Y]" at i; no X means one hundred."""
    unit = n.words.get(keys[i])
    if unit is not None and 1 <= unit <= 9 and i + 1 < len(keys) and keys[i + 1] in n.hundred:
        j = i + 2
    elif keys[i] in n.hundred:
        unit, j = 1, i + 1
    else:
        return None
    total, end = unit * 100, j
    if j < len(keys) and keys[j] == "and":
        j += 1
    rest = _below_100(keys, j, n, zero=False)
    if rest is not None:
        total += rest[0]
        end = j + rest[1]
    return total, end - i


def _single_digit(key: str, n: _Numbers) -> str | None:
    """The digit after double or triple: a digit token, a digit word, or oh (key o) as 0."""
    if len(key) == 1 and key.isdigit():
        return key
    if key == "o":
        return "0"
    value = n.words.get(key)
    return None if value is None or value > 9 else str(value)


def _numbers(keys: list[str], n: _Numbers) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(keys):
        key = keys[i]
        if key in n.double or key in n.triple:
            digit = _single_digit(keys[i + 1], n) if i + 1 < len(keys) else None
            if digit is not None:
                out.append(digit * (2 if key in n.double else 3))
                i += 2
                continue
        found = _hundreds(keys, i, n) or _below_100(keys, i, n, zero=True)
        if found is not None:
            out.append(str(found[0]))
            i += found[1]
            continue
        out.append(key)
        i += 1
    return out


def _oh_as_zero(tokens: list[str]) -> list[str]:
    """A run of oh (key o) reads as zeros only between two digit tokens: nine oh eight."""
    out = list(tokens)
    i = 0
    while i < len(out):
        j = i
        while j < len(out) and out[j] == "o":
            j += 1
        if j > i and i > 0 and out[i - 1].isdigit() and j < len(out) and out[j].isdigit():
            out[i:j] = ["0"] * (j - i)
        i = max(j, i + 1)
    return out


def _join_digits(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for tok in tokens:
        if tok.isdigit() and out and out[-1].isdigit():
            out[-1] += tok
        else:
            out.append(tok)
    return out


def normalize(text: str, language: str = "hi-en") -> Normalized:
    """Loose tokens of text for scoring in one scenario language (see LANGUAGES)."""
    if language not in _NUMBERS:
        raise ValueError(f"unsupported language {language!r}; expected one of {LANGUAGES}")
    # 1. NFC, zero-width joiners out, Perso-Arabic detection.
    text = unicodedata.normalize("NFC", text).replace("\u200c", "").replace("\u200d", "")
    unsupported = bool(_PERSO_ARABIC.search(text))
    # 2. Native digits to ASCII, then Devanagari, Kannada and Tamil to loose Roman, by script.
    # Devanagari fillers are dropped in hi-en and hi only.
    text = romanize(text, devanagari_fillers=language in ("hi-en", "hi"))
    # 3. Lowercase, strip everything outside [a-z0-9], split, loose key for non-digit tokens,
    # then drop Roman fillers.
    keys = [t if t.isdigit() else _loose_key(t, language) for t in _split_tokens(text)]
    keys = [k for k in keys if k not in _FILLER_KEYS]
    # 4. Number words by key, oh between digits, then concatenate adjacent digit tokens.
    tokens = _join_digits(_oh_as_zero(_numbers(keys, _NUMBERS[language])))
    return Normalized(tokens=tokens, script_unsupported=unsupported)


def strict_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return text.split()


def _skeleton(token: str) -> str:
    stripped = "".join(c for c in token if c not in _VOWELS and c != "y")
    return re.sub(r"(.)\1+", r"\1", stripped)


def tokens_equal(a: str, b: str) -> bool:
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        return False
    sa, sb = _skeleton(a), _skeleton(b)
    return sa == sb and len(sa) >= 3 and abs(len(a) - len(b)) <= 2

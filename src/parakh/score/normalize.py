"""Script-tolerant normaliser for Hinglish scoring.

Maps Roman and Devanagari spellings of the same word to one loose phonetic
key so a WER engine can compare them fairly without merging words that
really differ. Rule order matters; see the numbered comments in `normalize`.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from indic_transliteration import sanscript  # type: ignore[import-untyped]

from parakh.score import numbers

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

# Hesitation fillers carry no content, and a reference may leave them out, so they are
# dropped on both sides. Devanagari fillers go before transliteration, because हम्म would
# read ham (हम, we) and अम would read am (English "am"); Roman fillers go by loose key.
_DEVANAGARI_FILLERS = frozenset({"अम", "अम्म", "उम", "उम्म"})
# ह then two or more म with a virama between them: हम्म, हम्म्म, हम्मम. Plain हम (we) stays.
_HMM = re.compile("^ह(?:म्)+म+$")
_FILLER_KEYS = frozenset({"um", "uh", "hm"})

_PERSO_ARABIC = re.compile("[؀-ۿ]")
# Devanagari letters and signs, excluding danda and double danda.
_DEVANAGARI_RUN = re.compile("[ऀ-ॣ०-ॿ]+")
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_VOWELS = "aeiou"


@dataclass(frozen=True)
class Normalized:
    tokens: list[str]
    script_unsupported: bool


def _transliterate_word(word: str) -> str:
    word = word.replace("ऑ", "ओ").replace("ॉ", "ो")
    itrans: str = sanscript.transliterate(word, sanscript.DEVANAGARI, sanscript.ITRANS)
    if len(itrans) > 2 and itrans.endswith("a") and itrans[-2] not in "aeiouAEIOU":
        itrans = itrans[:-1]
    itrans = re.sub(r"M(?=[pbm])", "m", itrans)
    itrans = itrans.replace(".N", "n").replace("M", "n")
    return itrans.replace(".", "")


def _romanize_word(word: str) -> str:
    return (
        " " if word in _DEVANAGARI_FILLERS or _HMM.match(word) else f" {_transliterate_word(word)} "
    )


def _romanize_devanagari(text: str) -> str:
    return _DEVANAGARI_RUN.sub(lambda m: _romanize_word(m.group(0)), text)


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


@lru_cache(maxsize=8192)
def _loose_key(token: str) -> str:
    while (spelled := _spell(token)) != token:
        token = spelled
    return VARIANTS.get(token, token)


def _spelling_key(spelling: str) -> str:
    (token,) = _split_tokens(_romanize_devanagari(spelling))
    return _loose_key(token)


def _key_table(groups: Iterable[tuple[int, Iterable[str]]]) -> dict[str, int]:
    """Loose key of every spelling to its value; two values on one key is a table bug."""
    table: dict[str, int] = {}
    for value, spellings in groups:
        for spelling in spellings:
            key = _spelling_key(spelling)
            if table.setdefault(key, value) != value:
                raise ValueError(f"number spelling {spelling!r} collides on key {key!r}")
    return table


# Number words are looked up by loose key, so bees, बीस and bis all give 20. For English
# words the key is a superset of the raw token, which keeps the rule idempotent.
_EN_UNITS = _key_table((v, (w,)) for v, w in enumerate(numbers.EN_UNITS))
_EN_TENS = _key_table(((i + 2) * 10, (w,)) for i, w in enumerate(numbers.EN_TENS))
_WORDS = _key_table(
    [
        *((v, (w,)) for v, w in enumerate(numbers.EN_UNITS)),
        *numbers.EN_DEVANAGARI.items(),
        *numbers.HINDI.items(),
    ]
)
_DOUBLE = {_spelling_key(s) for s in numbers.DOUBLE}
_TRIPLE = {_spelling_key(s) for s in numbers.TRIPLE}
_HUNDRED = {_spelling_key(s) for s in numbers.HUNDRED}
if not _EN_TENS.keys().isdisjoint(_WORDS) or not _HUNDRED.isdisjoint(_WORDS):
    raise ValueError("number word tables overlap")


def _below_100(keys: list[str], i: int, *, zero: bool) -> tuple[int, int] | None:
    """Value and token count of a number word at i: Hindi 0-99, English 0-19, or tens [unit]."""
    if i >= len(keys):
        return None
    key = keys[i]
    if key in _EN_TENS:
        unit = _EN_UNITS.get(keys[i + 1]) if i + 1 < len(keys) else None
        if unit is not None and 1 <= unit <= 9:
            return _EN_TENS[key] + unit, 2
        return _EN_TENS[key], 1
    value = _WORDS.get(key)
    if value is not None and (zero or value >= 1):
        return value, 1
    return None


def _hundreds(keys: list[str], i: int) -> tuple[int, int] | None:
    """Value and token count of "[X] hundred|sau [and] [Y]" at i; no X means one hundred."""
    unit = _WORDS.get(keys[i])
    if unit is not None and 1 <= unit <= 9 and i + 1 < len(keys) and keys[i + 1] in _HUNDRED:
        j = i + 2
    elif keys[i] in _HUNDRED:
        unit, j = 1, i + 1
    else:
        return None
    total, end = unit * 100, j
    if j < len(keys) and keys[j] == "and":
        j += 1
    rest = _below_100(keys, j, zero=False)
    if rest is not None:
        total += rest[0]
        end = j + rest[1]
    return total, end - i


def _single_digit(key: str) -> str | None:
    """The digit after double or triple: a digit token, a digit word, or oh (key o) as 0."""
    if len(key) == 1 and key.isdigit():
        return key
    if key == "o":
        return "0"
    value = _WORDS.get(key)
    return None if value is None or value > 9 else str(value)


def _numbers(keys: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(keys):
        key = keys[i]
        if key in _DOUBLE or key in _TRIPLE:
            digit = _single_digit(keys[i + 1]) if i + 1 < len(keys) else None
            if digit is not None:
                out.append(digit * (2 if key in _DOUBLE else 3))
                i += 2
                continue
        found = _hundreds(keys, i) or _below_100(keys, i, zero=True)
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


def normalize(text: str) -> Normalized:
    # 1. NFC, zero-width joiners out, Perso-Arabic detection, Devanagari digits to ASCII.
    text = unicodedata.normalize("NFC", text).replace("\u200c", "").replace("\u200d", "")
    unsupported = bool(_PERSO_ARABIC.search(text))
    text = text.translate(_DEVANAGARI_DIGITS)
    # 2. Devanagari to loose ITRANS, dropping Devanagari fillers.
    text = _romanize_devanagari(text)
    # 3. Lowercase, strip everything outside [a-z0-9], split, loose key for non-digit tokens,
    # then drop Roman fillers.
    keys = [t if t.isdigit() else _loose_key(t) for t in _split_tokens(text)]
    keys = [k for k in keys if k not in _FILLER_KEYS]
    # 4. Number words by key, oh between digits, then concatenate adjacent digit tokens.
    tokens = _join_digits(_oh_as_zero(_numbers(keys)))
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

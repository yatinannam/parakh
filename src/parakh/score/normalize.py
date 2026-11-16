"""Script-tolerant normaliser for Hinglish scoring.

Maps Roman and Devanagari spellings of the same word to one loose phonetic
key so a WER engine can compare them fairly without merging words that
really differ. Rule order matters; see the numbered comments in `normalize`.
"""

import re
import unicodedata
from dataclasses import dataclass

from indic_transliteration import sanscript  # type: ignore[import-untyped]

VARIANTS: dict[str, str] = {
    "nahin": "nahi",
    "nai": "nahi",
    "men": "mein",
    "me": "mein",
    "rav": "rao",
}

_PERSO_ARABIC = re.compile("[؀-ۿ]")
# Devanagari letters and signs, excluding danda and double danda.
_DEVANAGARI_RUN = re.compile("[ऀ-ॣ०-ॿ]+")
_VOWELS = "aeiou"

_EN_UNITS = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_EN_TENS = {
    w: (i + 2) * 10
    for i, w in enumerate(
        ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
}
_HI_DIGITS = {
    "shunya": 0, "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4,
    "paanch": 5, "panch": 5, "chhe": 6, "che": 6, "chhah": 6, "saat": 7,
    "sat": 7, "aath": 8, "ath": 8, "nau": 9, "das": 10,
}  # fmt: skip


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


def _romanize_devanagari(text: str) -> str:
    return _DEVANAGARI_RUN.sub(lambda m: f" {_transliterate_word(m.group(0))} ", text)


def _split_tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]", " ", text.lower()).split()


def _numbers(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok in ("double", "triple") and (nxt in _EN_UNITS or nxt in _HI_DIGITS):
            digit = _EN_UNITS.get(nxt, _HI_DIGITS.get(nxt))
            if digit is not None and digit < 10:
                out.append(str(digit) * (2 if tok == "double" else 3))
                i += 2
                continue
        if tok in _EN_TENS:
            unit = _EN_UNITS.get(nxt)
            if unit is not None and 1 <= unit <= 9:
                out.append(str(_EN_TENS[tok] + unit))
                i += 2
            else:
                out.append(str(_EN_TENS[tok]))
                i += 1
            continue
        if tok == "hundred":
            out.append("100")
        elif tok in _EN_UNITS:
            out.append(str(_EN_UNITS[tok]))
        elif tok in _HI_DIGITS:
            out.append(str(_HI_DIGITS[tok]))
        else:
            out.append(tok)
        i += 1
    return out


def _join_digits(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for tok in tokens:
        if tok.isdigit() and out and out[-1].isdigit():
            out[-1] += tok
        else:
            out.append(tok)
    return out


def _loose_key(token: str) -> str:
    token = re.sub(r"c(?!h)", "k", token)
    token = token.replace("ph", "f").replace("w", "v").replace("q", "k").replace("z", "j")
    token = re.sub(r"ov$", "o", token)
    token = token.replace("ee", "i").replace("oo", "u")
    token = re.sub(r"(.)\1+", r"\1", token)
    token = re.sub(r"(?<=[aeiou])y(?=[aeiou])", "", token)
    return VARIANTS.get(token, token)


def normalize(text: str) -> Normalized:
    # 1. NFC and Perso-Arabic detection.
    text = unicodedata.normalize("NFC", text)
    unsupported = bool(_PERSO_ARABIC.search(text))
    # 2. Devanagari to loose ITRANS.
    text = _romanize_devanagari(text)
    # 3. Lowercase, strip everything outside [a-z0-9], split.
    tokens = _split_tokens(text)
    # 4. Numbers, then concatenate adjacent digit tokens.
    tokens = _join_digits(_numbers(tokens))
    # 5. Loose phonetic key for non-digit tokens.
    tokens = [t if t.isdigit() else _loose_key(t) for t in tokens]
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

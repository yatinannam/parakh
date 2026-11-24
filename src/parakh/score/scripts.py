"""Per-script romanisers for the normaliser: Devanagari, Kannada and Tamil to loose Roman.

The script decides the rules, not the scenario language, so a Devanagari word in a Kannada
run still reads as Devanagari. Devanagari and Kannada go through indic-transliteration's
ITRANS; Tamil goes through Parakh's own table in `parakh.score.tamil` (D19). Native numerals
of all three scripts become ASCII digits.
"""

import re
import unicodedata

from indic_transliteration import sanscript  # type: ignore[import-untyped]

from parakh.score.tamil import romanize_tamil

# Hesitation fillers carry no content, and a reference may leave them out, so they are
# dropped on both sides. Devanagari fillers go before transliteration, because हम्म would
# read ham (हम, we) and अम would read am (English "am"); Roman fillers go by loose key.
_DEVANAGARI_FILLERS = frozenset({"अम", "अम्म", "उम", "उम्म"})
# ह then two or more म with a virama between them: हम्म, हम्म्म, हम्मम. Plain हम (we) stays.
_HMM = re.compile("^ह(?:म्)+म+$")

# Devanagari letters and signs, excluding danda and double danda.
_DEVANAGARI_RUN = re.compile("[ऀ-ॣ०-ॿ]+")
_KANNADA_RUN = re.compile(r"[ಀ-೿]+")  # the Kannada block
_TAMIL_RUN = re.compile(r"[஀-௿]+")  # the Tamil block
# Devanagari ०-९, Kannada ೦-೯ and Tamil ௦-௯ to ASCII digits, in every language.
_DIGITS = str.maketrans("०१२३४५६७८९" + "೦೧೨೩೪೫೬೭೮೯" + "௦௧௨௩௪௫௬௭௮௯", "0123456789" * 3)


def transliterate_devanagari(word: str) -> str:
    """Loose ITRANS of one Devanagari word: candra o, final schwa and anusvara rules."""
    word = word.replace("ऑ", "ओ").replace("ॉ", "ो")
    itrans: str = sanscript.transliterate(word, sanscript.DEVANAGARI, sanscript.ITRANS)
    if len(itrans) > 2 and itrans.endswith("a") and itrans[-2] not in "aeiouAEIOU":
        itrans = itrans[:-1]
    itrans = re.sub(r"M(?=[pbm])", "m", itrans)
    itrans = itrans.replace(".N", "n").replace("M", "n")
    return itrans.replace(".", "")


def romanize_kannada(word: str) -> str:
    """ITRANS folded to ASCII letters. No final-schwa rule: Kannada words end in a vowel."""
    itrans: str = sanscript.transliterate(word, sanscript.KANNADA, sanscript.ITRANS)
    # ITRANS writes short e and o as è and ò; folding drops the accent.
    folded = "".join(
        c for c in unicodedata.normalize("NFD", itrans) if not unicodedata.combining(c)
    )
    folded = re.sub(r"M(?=[pbm])", "m", folded).replace(".N", "n").replace("M", "n")
    # Drop ITRANS marks (~ in j~na, . in .a) so a word stays one token.
    return re.sub(r"[^A-Za-z]", "", folded)


def _devanagari_word(word: str, fillers: bool) -> str:
    if fillers and (word in _DEVANAGARI_FILLERS or _HMM.match(word)):
        return " "
    return f" {transliterate_devanagari(word)} "


def romanize(text: str, *, devanagari_fillers: bool = True) -> str:
    """Native digits to ASCII, then each Devanagari, Kannada and Tamil run to loose Roman."""
    text = text.translate(_DIGITS)
    text = _DEVANAGARI_RUN.sub(lambda m: _devanagari_word(m.group(0), devanagari_fillers), text)
    text = _KANNADA_RUN.sub(lambda m: f" {romanize_kannada(m.group(0))} ", text)
    return _TAMIL_RUN.sub(lambda m: f" {romanize_tamil(m.group(0))} ", text)

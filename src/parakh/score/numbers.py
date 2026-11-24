"""Number-word spellings for the normaliser.

Plain data: `parakh.score.normalize` turns every spelling into its loose key, so the tables
list each common spelling once and the key absorbs vowel length, doubled letters and
script. Hindi words come in Roman and Devanagari, so ITRANS quirks (for example the dropped
final schwa in शून्य) produce the same key the transcript will. Kannada and Tamil words come
in Roman and native script too; their 21-99 are built from the tens and units, because each
is one written word (ಇಪ್ಪತ್ತೊಂದು, இருபத்தொன்று). `SPELLINGS` picks the tables per language.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

EN_UNITS: tuple[str, ...] = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
)  # fmt: skip

EN_TENS: tuple[str, ...] = (
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
)  # fmt: skip

# English digit words as Groq Whisper writes them in Devanagari. Three are left out because
# their keys are common words: वन (van, forest), टू (tu, you) and फोर (for).
EN_DEVANAGARI: dict[int, tuple[str, ...]] = {
    0: ("ज़ीरो", "जीरो"),
    3: ("थ्री",),
    5: ("फाइव", "फ़ाइव"),
    6: ("सिक्स",),
    7: ("सेवन",),
    8: ("एट",),
    9: ("नाइन",),
}

DOUBLE: tuple[str, ...] = ("double", "डबल")
TRIPLE: tuple[str, ...] = ("triple", "ट्रिपल")
HUNDRED: tuple[str, ...] = ("hundred", "sau", "सौ")

# Hindi 0-99, value -> spellings. Two values are left out on purpose:
# 13 (terah) loses its final h and reads tera (your), and 60 (साठ, saath) reads the same
# as साथ (with). Both are known gaps in tests/golden/normalizer_pairs.yaml.
HINDI: dict[int, tuple[str, ...]] = {
    0: ("shunya", "shoonya", "शून्य"),
    1: ("ek", "एक"),
    2: ("do", "दो"),
    3: ("teen", "tin", "तीन"),
    4: ("char", "chaar", "चार"),
    5: ("paanch", "panch", "पाँच", "पांच"),
    6: ("chhe", "chhah", "छह", "छः", "छे"),
    7: ("saat", "सात"),
    8: ("aath", "आठ"),
    9: ("nau", "नौ"),
    10: ("das", "दस"),
    11: ("gyarah", "gyaarah", "ग्यारह"),
    12: ("barah", "baarah", "बारह"),
    14: ("chaudah", "चौदह"),
    15: ("pandrah", "पंद्रह", "पन्द्रह"),
    16: ("solah", "सोलह"),
    17: ("satrah", "सत्रह"),
    18: ("atharah", "athaarah", "अठारह"),
    19: ("unnees", "unnis", "उन्नीस"),
    20: ("bees", "बीस"),
    21: ("ikkees", "ikkis", "इक्कीस"),
    22: ("baees", "bais", "बाईस"),
    23: ("teis", "तेईस"),
    24: ("chaubees", "chaubis", "चौबीस"),
    25: ("pachees", "pachchees", "पच्चीस"),
    26: ("chhabbees", "chhabbis", "छब्बीस"),
    27: ("sattaees", "sattais", "सत्ताईस"),
    28: ("atthaees", "atthais", "अट्ठाईस"),
    29: ("untees", "unatis", "उनतीस"),
    30: ("tees", "तीस"),
    31: ("iktees", "iktis", "इकतीस"),
    32: ("battees", "battis", "बत्तीस"),
    33: ("taintees", "taintis", "तैंतीस"),
    34: ("chauntees", "chautis", "चौंतीस"),
    35: ("paintees", "paintis", "पैंतीस"),
    36: ("chhattees", "chhattis", "छत्तीस"),
    37: ("saintees", "saintis", "सैंतीस"),
    38: ("adtees", "artis", "अड़तीस"),
    39: ("untaalees", "untalis", "उनतालीस"),
    40: ("chaalees", "chalis", "chaalis", "चालीस"),
    41: ("iktaalees", "iktalis", "इकतालीस"),
    42: ("bayaalees", "bayalis", "बयालीस"),
    43: ("taintaalees", "taintalis", "तैंतालीस"),
    44: ("chavaalees", "chauvalis", "चवालीस", "चौवालीस"),
    45: ("paintaalees", "paintalis", "पैंतालीस"),
    46: ("chhiyaalees", "chhiyalis", "छियालीस"),
    47: ("saintaalees", "saintalis", "सैंतालीस"),
    48: ("adtaalees", "artalis", "अड़तालीस"),
    49: ("unchaas", "unchas", "उनचास"),
    50: ("pachaas", "pachas", "पचास"),
    51: ("ikyaavan", "ikyavan", "इक्यावन"),
    52: ("baavan", "bavan", "बावन"),
    53: ("tirpan", "tirepan", "तिरपन", "तिरेपन"),
    54: ("chauvan", "चौवन"),
    55: ("pachpan", "पचपन"),
    56: ("chhappan", "छप्पन"),
    57: ("sattaavan", "sattavan", "सत्तावन"),
    58: ("atthaavan", "atthavan", "अट्ठावन"),
    59: ("unsath", "उनसठ"),
    61: ("iksath", "इकसठ"),
    62: ("baasath", "basath", "बासठ"),
    63: ("tirsath", "तिरसठ"),
    64: ("chaunsath", "chausath", "चौंसठ"),
    65: ("painsath", "पैंसठ"),
    66: ("chhiyaasath", "chhiyasath", "छियासठ"),
    67: ("sadsath", "सड़सठ"),
    68: ("adsath", "अड़सठ"),
    69: ("unhattar", "उनहत्तर"),
    70: ("sattar", "सत्तर"),
    71: ("ikhattar", "इकहत्तर"),
    72: ("bahattar", "बहत्तर"),
    73: ("tihattar", "तिहत्तर"),
    74: ("chauhattar", "चौहत्तर"),
    75: ("pachhattar", "पचहत्तर"),
    76: ("chhihattar", "छिहत्तर"),
    77: ("satattar", "सतहत्तर"),
    78: ("athhattar", "अठहत्तर"),
    79: ("unaasi", "unasi", "उन्यासी"),
    80: ("assi", "अस्सी"),
    81: ("ikyaasi", "ikyasi", "इक्यासी"),
    82: ("bayaasi", "bayasi", "बयासी"),
    83: ("tiraasi", "tirasi", "तिरासी"),
    84: ("chauraasi", "chaurasi", "चौरासी"),
    85: ("pachaasi", "pachasi", "पचासी"),
    86: ("chhiyaasi", "chhiyasi", "छियासी"),
    87: ("sattaasi", "sattasi", "सत्तासी"),
    88: ("atthaasi", "atthasi", "अट्ठासी"),
    89: ("navaasi", "navasi", "नवासी"),
    90: ("nabbe", "नब्बे"),
    91: ("ikyaanve", "ikyanve", "इक्यानवे"),
    92: ("baanve", "banve", "बानवे"),
    93: ("tiraanve", "tiranve", "तिरानवे"),
    94: ("chauraanve", "chauranve", "चौरानवे"),
    95: ("pachaanve", "pachanve", "पचानवे"),
    96: ("chhiyaanve", "chhiyanve", "छियानवे"),
    97: ("sattaanve", "sattanve", "सत्तानवे"),
    98: ("atthaanve", "atthanve", "अट्ठानवे"),
    99: ("ninyaanve", "ninyanve", "निन्यानवे"),
}

# Kannada 0-19 and 100, value -> spellings (Roman, then Kannada script). The tens are apart,
# because a tens word followed by a unit word combines: ippattu ondu is 21.
KANNADA: dict[int, tuple[str, ...]] = {
    0: ("sonne", "ಸೊನ್ನೆ"),
    1: ("ondu", "ಒಂದು"),
    2: ("eradu", "yeradu", "ಎರಡು"),
    3: ("mooru", "ಮೂರು"),
    4: ("naalku", "naaku", "ನಾಲ್ಕು", "ನಾಕು"),
    5: ("aidu", "ayidu", "ಐದು"),
    6: ("aaru", "ಆರು"),
    7: ("elu", "yelu", "eelu", "ಏಳು"),
    8: ("entu", "yentu", "ಎಂಟು"),
    9: ("ombattu", "ombhattu", "ombathu", "ಒಂಬತ್ತು"),
    10: ("hattu", "hathu", "ಹತ್ತು"),
    11: ("hannondu", "ಹನ್ನೊಂದು"),
    12: ("hanneradu", "ಹನ್ನೆರಡು"),
    13: ("hadimooru", "ಹದಿಮೂರು"),
    14: ("hadinaalku", "ಹದಿನಾಲ್ಕು"),
    15: ("hadinaidu", "ಹದಿನೈದು"),
    16: ("hadinaaru", "ಹದಿನಾರು"),
    17: ("hadinelu", "ಹದಿನೇಳು"),
    18: ("hadinentu", "ಹದಿನೆಂಟು"),
    19: ("hattombattu", "ಹತ್ತೊಂಬತ್ತು"),
    100: ("nooru", "ನೂರು"),
}
KANNADA_TENS: dict[int, tuple[str, ...]] = {
    20: ("ippattu", "ippathu", "ಇಪ್ಪತ್ತು"),
    30: ("moovattu", "ಮೂವತ್ತು"),
    40: ("nalavattu", "nalvattu", "ನಲವತ್ತು", "ನಲ್ವತ್ತು"),
    50: ("aivattu", "ಐವತ್ತು"),
    60: ("aravattu", "ಅರವತ್ತು"),
    70: ("eppattu", "ಎಪ್ಪತ್ತು"),
    80: ("embattu", "ಎಂಬತ್ತು"),
    90: ("tombattu", "ತೊಂಬತ್ತು"),
}

# Tamil 0-19 and 100: Roman, then Tamil script, colloquial forms (onnu, rendu) beside the
# written ones (ondru, irandu).
TAMIL: dict[int, tuple[str, ...]] = {
    0: ("poojyam", "poojiyam", "பூஜ்யம்", "பூஜ்ஜியம்"),
    1: ("onnu", "ondru", "onru", "ஒன்று", "ஒண்ணு"),
    2: ("rendu", "irandu", "இரண்டு", "ரெண்டு"),
    3: ("moonu", "moondru", "moonru", "மூன்று", "மூணு"),
    4: ("naalu", "naangu", "naanku", "நான்கு", "நாலு"),
    5: ("anju", "ainthu", "aindhu", "ஐந்து", "அஞ்சு"),
    6: ("aaru", "ஆறு"),
    7: ("ezhu", "ஏழு"),
    8: ("ettu", "எட்டு"),
    9: ("onbadhu", "onbathu", "ombadhu", "ombodhu", "ஒன்பது"),
    10: ("pathu", "padhu", "paththu", "பத்து"),
    11: ("padhinonnu", "padhinondru", "பதினொன்று", "பதினொண்ணு"),
    12: ("pannendu", "pannirandu", "பன்னிரண்டு", "பன்னெண்டு"),
    13: ("padhimoonu", "padhimoondru", "பதின்மூன்று", "பதிமூணு"),
    14: ("padhinaalu", "padhinaangu", "பதினான்கு", "பதினாலு"),
    15: ("padhinanju", "padhinainthu", "பதினைந்து", "பதினஞ்சு"),
    16: ("padhinaaru", "பதினாறு"),
    17: ("padhinezhu", "பதினேழு"),
    18: ("padhinettu", "பதினெட்டு"),
    19: ("patthonbadhu", "பத்தொன்பது"),
    100: ("nooru", "நூறு"),
}
TAMIL_TENS: dict[int, tuple[str, ...]] = {
    20: ("irubadhu", "இருபது"),
    30: ("muppadhu", "முப்பது"),
    40: ("naarpadhu", "நாற்பது"),
    50: ("aimbadhu", "ஐம்பது"),
    60: ("arubadhu", "அறுபது"),
    70: ("ezhubadhu", "எழுபது"),
    80: ("enbadhu", "எண்பது"),
    90: ("thonnooru", "தொண்ணூறு"),
}

# English digit words in Kannada and Tamil script. one, two and four are left out: their
# keys are on, too and for.
EN_KANNADA: dict[int, tuple[str, ...]] = {
    0: ("ಜೀರೋ",), 3: ("ತ್ರೀ",), 5: ("ಫೈವ್",), 6: ("ಸಿಕ್ಸ್",), 7: ("ಸೆವೆನ್",),
    8: ("ಎಯ್ಟ್", "ಏಟ್"), 9: ("ನೈನ್",),
}  # fmt: skip
EN_TAMIL: dict[int, tuple[str, ...]] = {
    0: ("ஜீரோ",), 3: ("த்ரீ",), 5: ("ஃபைவ்",), 6: ("சிக்ஸ்",), 7: ("செவன்",),
    8: ("எய்ட்",), 9: ("நைன்",),
}  # fmt: skip

_KANNADA_SIGNS = {
    "ಅ": "", "ಆ": "ಾ", "ಇ": "ಿ", "ಈ": "ೀ", "ಉ": "ು", "ಊ": "ೂ",
    "ಎ": "ೆ", "ಏ": "ೇ", "ಐ": "ೈ", "ಒ": "ೊ", "ಓ": "ೋ", "ಔ": "ೌ",
}  # fmt: skip
_TAMIL_SIGNS = {
    "அ": "", "ஆ": "ா", "இ": "ி", "ஈ": "ீ", "உ": "ு", "ஊ": "ூ",
    "எ": "ெ", "ஏ": "ே", "ஐ": "ை", "ஒ": "ொ", "ஓ": "ோ", "ஔ": "ௌ",
}  # fmt: skip

Group = tuple[int, tuple[str, ...]]


def _kannada_join(tens: str, unit: str) -> tuple[str, ...]:
    """ಇಪ್ಪತ್ತು and ಒಂದು give ಇಪ್ಪತ್ತೊಂದು; before a consonant, ಇಪ್ಪತ್ತಮೂರು and ಇಪ್ಪತ್ಮೂರು."""
    stem = tens[:-1]
    if unit[0] in _KANNADA_SIGNS:
        return (stem + _KANNADA_SIGNS[unit[0]] + unit[1:],)
    return (stem + unit, stem[:-1] + unit)


def _tamil_join(tens: str, unit: str) -> tuple[str, ...]:
    """இருபது and ஒன்று give இருபத்தொன்று; before a consonant, இருபத்துமூன்று."""
    stem = tens[:-2] + tens[-2] + "்" + tens[-2]
    if unit[0] in _TAMIL_SIGNS:
        return (stem + _TAMIL_SIGNS[unit[0]] + unit[1:],)
    return (stem + "ு" + unit,)


def _compounds(
    tens: dict[int, tuple[str, ...]],
    units: dict[int, tuple[str, ...]],
    block: int,
    join: Callable[[str, str], tuple[str, ...]],
) -> list[Group]:
    """Native-script spellings of 21-99 (tens plus 1-9, as one word) for one script block."""

    def native(spellings: tuple[str, ...]) -> list[str]:
        return [s for s in spellings if block <= ord(s[0]) < block + 0x80]

    return [
        (t + u, tuple(w for a in native(tens[t]) for b in native(units[u]) for w in join(a, b)))
        for t in tens
        for u in range(1, 10)
    ]


@dataclass(frozen=True)
class Spellings:
    """The number words of one language, as spelling groups; the normaliser keys them."""

    words: list[Group]  # one word, one value
    tens: list[Group]  # a unit word right after one of these adds to it: twenty one
    units: list[Group]  # the unit words that may follow a tens word
    double: tuple[str, ...]
    triple: tuple[str, ...]
    hundred: tuple[str, ...]


def _units_of(*tables: Iterable[Group]) -> list[Group]:
    return [(v, w) for table in tables for v, w in table if 1 <= v <= 9]


_EN_WORDS: list[Group] = [(v, (w,)) for v, w in enumerate(EN_UNITS)]
_EN_TENS_WORDS: list[Group] = [((i + 2) * 10, (w,)) for i, w in enumerate(EN_TENS)]
_HINDI = Spellings(
    words=[*_EN_WORDS, *EN_DEVANAGARI.items(), *HINDI.items()],
    tens=_EN_TENS_WORDS,
    units=_EN_WORDS,
    double=DOUBLE,
    triple=TRIPLE,
    hundred=HUNDRED,
)
_KANNADA_WORDS: list[Group] = [*_EN_WORDS, *EN_KANNADA.items(), *KANNADA.items()]
_TAMIL_WORDS: list[Group] = [*_EN_WORDS, *EN_TAMIL.items(), *TAMIL.items()]

# Number words by scenario language: a word is never read as a number in a language it does
# not belong to (ondu is 1 only in kn-en, rendu is 2 only in ta-en).
SPELLINGS: dict[str, Spellings] = {
    "hi-en": _HINDI,
    "hi": _HINDI,
    "en": Spellings(_EN_WORDS, _EN_TENS_WORDS, _EN_WORDS, ("double",), ("triple",), ("hundred",)),
    "kn-en": Spellings(
        words=[*_KANNADA_WORDS, *_compounds(KANNADA_TENS, KANNADA, 0x0C80, _kannada_join)],
        tens=[*_EN_TENS_WORDS, *KANNADA_TENS.items()],
        units=_units_of(_KANNADA_WORDS),
        double=("double", "ಡಬಲ್"),
        triple=("triple", "ಟ್ರಿಪಲ್"),
        hundred=("hundred",),
    ),
    "ta-en": Spellings(
        words=[*_TAMIL_WORDS, *_compounds(TAMIL_TENS, TAMIL, 0x0B80, _tamil_join)],
        tens=[*_EN_TENS_WORDS, *TAMIL_TENS.items()],
        units=_units_of(_TAMIL_WORDS),
        double=("double", "டபுள்"),
        triple=("triple", "ட்ரிபிள்"),
        hundred=("hundred",),
    ),
}

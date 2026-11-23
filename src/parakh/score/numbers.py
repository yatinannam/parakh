"""Number-word spellings for the normaliser.

Plain data: `parakh.score.normalize` turns every spelling into its loose key, so the tables
list each common spelling once and the key absorbs vowel length, doubled letters and
script. Hindi words come in Roman and Devanagari, so ITRANS quirks (for example the dropped
final schwa in शून्य) produce the same key the transcript will.
"""

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

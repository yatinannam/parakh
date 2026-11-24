"""Tamil script to Roman, by Parakh's own table.

indic-transliteration's Tamil output is unusable for scoring (எனக்கு gives `èனghghu`, with ன
left as is), so Parakh romanises Tamil itself (D19). Tamil script does not mark voicing, so a
stop takes its sound from context, by the common pronunciation rules:

- after a nasal it is voiced: ம்ப mb, ந்த ndh, ங்க ng, ஞ்ச nj, ண்ட nd;
- doubled, or at word start, it is unvoiced: க்க kk, ட்ட tt, த்த tth, at word start த th;
- single between vowels it softens: க g, ச s, ட d, த dh, ப b;
- otherwise it is unvoiced.

The dental த always carries an h (th, dh) and the retroflex ட never does (t, d), so the two
stay apart (வந்து vandhu, having come; வண்டு vandu, beetle). ற்ற is tr and ன்ற is ndr; ழ is zh,
ள is l, ன and ண are n; ஃ before ப is f. Long and short e and o both give e and o, because
the loose key would read ee and oo as i and u. Characters outside the table (numerals,
symbols, a stray virama) give nothing.
"""

_VOWELS = {
    "அ": "a", "ஆ": "aa", "இ": "i", "ஈ": "ee", "உ": "u", "ஊ": "oo",
    "எ": "e", "ஏ": "e", "ஐ": "ai", "ஒ": "o", "ஓ": "o", "ஔ": "au",
}  # fmt: skip
_SIGNS = {
    "ா": "aa", "ி": "i", "ீ": "ee", "ு": "u", "ூ": "oo",
    "ெ": "e", "ே": "e", "ை": "ai", "ொ": "o", "ோ": "o", "ௌ": "au",
}  # fmt: skip
_VIRAMA = "்"
_AYTHAM = "ஃ"
# Stop: (unvoiced, soft between vowels, voiced after a nasal).
_STOPS = {
    "க": ("k", "g", "g"),
    "ச": ("ch", "s", "j"),
    "ட": ("t", "d", "d"),
    "த": ("th", "dh", "dh"),
    "ப": ("p", "b", "b"),
}
_NASALS = {"ங": "ng", "ஞ": "nj", "ண": "n", "ந": "n", "ம": "m", "ன": "n"}
_OTHERS = {
    "ய": "y", "ர": "r", "ல": "l", "வ": "v", "ழ": "zh", "ள": "l", "ற": "r",
    "ஜ": "j", "ஷ": "sh", "ஸ": "s", "ஹ": "h", "ஶ": "sh",
}  # fmt: skip
_CONSONANTS = {*_STOPS, *_NASALS, *_OTHERS}

# One unit per letter: (consonant, vowel). The consonant is "" for an independent vowel, the
# vowel is None for a dead consonant (virama) or the aytham.
_Unit = tuple[str, str | None]


def _units(word: str) -> list[_Unit]:
    units: list[_Unit] = []
    i = 0
    while i < len(word):
        ch = word[i]
        nxt = word[i + 1] if i + 1 < len(word) else ""
        if ch in _VOWELS:
            units.append(("", _VOWELS[ch]))
        elif ch == _AYTHAM:
            units.append((ch, None))
        elif ch in _CONSONANTS:
            if nxt == _VIRAMA or nxt in _SIGNS:
                units.append((ch, None if nxt == _VIRAMA else _SIGNS[nxt]))
                i += 1
            else:
                units.append((ch, "a"))
        elif ch in _SIGNS:
            units.append(("", _SIGNS[ch]))  # a sign with no consonant reads as its vowel
        i += 1
    return units


def _sound(units: list[_Unit], i: int) -> str:
    """The consonant sound of unit i, from its neighbours."""
    letter, vowel = units[i]
    prev = units[i - 1] if i > 0 else None
    nxt = units[i + 1] if i + 1 < len(units) else None
    prev_dead = prev is not None and prev[1] is None
    doubled = prev_dead and prev is not None and prev[0] == letter
    first_of_pair = vowel is None and nxt is not None and nxt[0] == letter
    after_nasal = prev_dead and prev is not None and prev[0] in _NASALS
    after_vowel = prev is not None and prev[1] is not None
    if letter == _AYTHAM:
        return "" if nxt is not None and nxt[0] in ("ப", "ஜ") else "h"
    if prev is not None and prev[0] == _AYTHAM and letter in ("ப", "ஜ"):
        return "f" if letter == "ப" else "z"
    if letter in _STOPS:
        hard, soft, voiced = _STOPS[letter]
        if first_of_pair:
            return hard[0]
        if doubled:
            return hard
        if after_nasal:
            return voiced
        if i == 0:
            return "s" if letter == "ச" else hard
        return soft if after_vowel and vowel is not None else hard
    if letter == "ற":
        if first_of_pair:
            return "t"
        return "dr" if after_nasal else "r"
    if letter in _NASALS:
        if vowel is None and nxt is not None and nxt[0] in _STOPS:
            return "m" if letter == "ம" else "n"
        return _NASALS[letter]
    return _OTHERS.get(letter, "")


def romanize_tamil(word: str) -> str:
    """Roman spelling of one run of Tamil script, lowercase ASCII letters only."""
    units = _units(word)
    return "".join(_sound(units, i) + (units[i][1] or "") for i in range(len(units)))

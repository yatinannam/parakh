"""Word-level alignment that marks which transcript words miss the reference."""

from parakh.score.normalize import normalize, tokens_equal


def _words_equal(a: str, b: str) -> bool:
    na, nb = normalize(a).tokens, normalize(b).tokens
    return len(na) == len(nb) and all(tokens_equal(x, y) for x, y in zip(na, nb, strict=True))


def _is_number(word: str) -> bool:
    tokens = normalize(word).tokens
    return bool(tokens) and all(token.isdigit() for token in tokens)


def _units(words: list[str]) -> list[list[str]]:
    """Group each run of number words into one unit, as the normaliser joins adjacent digits."""
    units: list[list[str]] = []
    for word in words:
        if units and _is_number(word) and _is_number(units[-1][-1]):
            units[-1].append(word)
        else:
            units.append([word])
    return units


def mark_misses(reference: str, transcript: str) -> list[tuple[str, bool]]:
    """Return (word, is_miss) per transcript word; misses are substitutions and insertions.

    Words are the raw whitespace-separated words a reader sees (case and punctuation kept),
    not normalised keys; equality goes through the loose normaliser. A run of number words,
    such as a phone number heard as "9845 012 345", is compared as one number and marked as
    a whole, because loose WER joins adjacent digits the same way.
    """
    ref = [" ".join(unit) for unit in _units(reference.split())]
    hyp_units = _units(transcript.split())
    hyp = [" ".join(unit) for unit in hyp_units]
    rows, cols = len(ref), len(hyp)
    dist = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows + 1):
        dist[i][0] = i
    for j in range(cols + 1):
        dist[0][j] = j
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            cost = 0 if _words_equal(ref[i - 1], hyp[j - 1]) else 1
            dist[i][j] = min(dist[i - 1][j] + 1, dist[i][j - 1] + 1, dist[i - 1][j - 1] + cost)
    misses = [True] * cols
    i, j = rows, cols
    while j > 0:
        if i > 0:
            equal = _words_equal(ref[i - 1], hyp[j - 1])
            if dist[i][j] == dist[i - 1][j - 1] + (0 if equal else 1):
                misses[j - 1] = not equal
                i, j = i - 1, j - 1
                continue
            if dist[i][j] == dist[i - 1][j] + 1:
                i -= 1
                continue
        j -= 1
    return [(word, miss) for unit, miss in zip(hyp_units, misses, strict=True) for word in unit]

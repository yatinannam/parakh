"""Word-level alignment that marks which transcript words miss the reference."""

from parakh.score.normalize import normalize, tokens_equal


def _words_equal(a: str, b: str) -> bool:
    na, nb = normalize(a).tokens, normalize(b).tokens
    return len(na) == len(nb) and all(tokens_equal(x, y) for x, y in zip(na, nb, strict=True))


def mark_misses(reference: str, transcript: str) -> list[tuple[str, bool]]:
    """Return (word, is_miss) per transcript word; misses are substitutions and insertions.

    Words are the raw whitespace-separated words a reader sees (case and punctuation kept),
    not normalised keys; equality goes through the loose normaliser.
    """
    ref, hyp = reference.split(), transcript.split()
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
    out: list[tuple[str, bool]] = []
    i, j = rows, cols
    while j > 0:
        if i > 0:
            equal = _words_equal(ref[i - 1], hyp[j - 1])
            if dist[i][j] == dist[i - 1][j - 1] + (0 if equal else 1):
                out.append((hyp[j - 1], not equal))
                i, j = i - 1, j - 1
                continue
            if dist[i][j] == dist[i - 1][j] + 1:
                i -= 1
                continue
        out.append((hyp[j - 1], True))
        j -= 1
    out.reverse()
    return out

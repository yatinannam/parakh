"""Strict and loose word error rate on the agent's own transcript of the caller."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

import jiwer

from parakh.score.normalize import normalize, strict_tokens, tokens_equal

T = TypeVar("T")
U = TypeVar("U")

NO_TRANSCRIPT_REASON = "agent exposed no caller transcript"


@dataclass(frozen=True)
class WerSummary:
    strict_wer: float | None
    loose_wer: float | None
    loose_cer: float | None
    reason: str | None
    script_unsupported_turns: list[int]


def _edit_distance(ref: Sequence[U], hyp: Sequence[U], equal: Callable[[U, U], bool]) -> int:
    """Plain DP edit distance; substitution, insertion and deletion cost 1."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i]
        for j, h in enumerate(hyp, start=1):
            cost = 0 if equal(r, h) else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def _rate(ref: Sequence[U], hyp: Sequence[U], equal: Callable[[U, U], bool]) -> float | None:
    if not ref:
        return None
    if not hyp:
        return 1.0
    return _edit_distance(ref, hyp, equal) / len(ref)


def strict_wer(ref: str, hyp: str) -> float | None:
    ref_tokens, hyp_tokens = strict_tokens(ref), strict_tokens(hyp)
    if not ref_tokens:
        return None
    if not hyp_tokens:
        return 1.0
    return float(jiwer.wer(" ".join(ref_tokens), " ".join(hyp_tokens)))


def loose_wer(ref: str, hyp: str, language: str = "hi-en") -> float | None:
    """None when the reference is empty or the hypothesis holds Urdu script (EC-41)."""
    hyp_norm = normalize(hyp, language)
    if hyp_norm.script_unsupported:
        return None
    return _rate(normalize(ref, language).tokens, hyp_norm.tokens, tokens_equal)


def loose_cer(ref: str, hyp: str, language: str = "hi-en") -> float | None:
    ref_chars = " ".join(normalize(ref, language).tokens)
    hyp_chars = " ".join(normalize(hyp, language).tokens)
    return _rate(ref_chars, hyp_chars, lambda a, b: a == b)


def group_by_turn(turn_starts_ms: list[float], items: list[tuple[float, T]]) -> list[list[T]]:
    """Put each item in the last turn whose start is at or before its time.

    Items within a turn are ordered by time (stable for equal times).
    """
    if not turn_starts_ms:
        return []
    groups: list[list[T]] = [[] for _ in turn_starts_ms]
    for t_ms, value in sorted(items, key=lambda item: item[0]):
        turn = 0
        for index, start in enumerate(turn_starts_ms):
            if start <= t_ms:
                turn = index
        groups[turn].append(value)
    return groups


def _no_transcript() -> WerSummary:
    return WerSummary(None, None, None, NO_TRANSCRIPT_REASON, [])


def conversation_wer(
    refs: list[str], hyps_by_turn: list[list[str]], language: str = "hi-en"
) -> WerSummary:
    """Headline WER over the whole call, so VAD splitting or merging turns cancels out.

    The language picks the normaliser's variants and number words (spec 6.7).
    """
    joined = [" ".join(segments) for segments in hyps_by_turn]
    if not any(text.strip() for text in joined):
        return _no_transcript()
    unsupported = [
        i for i, text in enumerate(joined) if normalize(text, language).script_unsupported
    ]
    kept = [i for i in range(min(len(refs), len(joined))) if i not in unsupported]
    loose_ref = " ".join(refs[i] for i in kept)
    loose_hyp = " ".join(joined[i] for i in kept)
    return WerSummary(
        strict_wer=strict_wer(" ".join(refs), " ".join(joined)),
        loose_wer=loose_wer(loose_ref, loose_hyp, language),
        loose_cer=loose_cer(loose_ref, loose_hyp, language),
        reason=None,
        script_unsupported_turns=unsupported,
    )

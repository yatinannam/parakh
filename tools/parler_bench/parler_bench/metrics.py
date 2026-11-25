"""Benchmark metrics and the adopt-or-not verdict. Standard library only, no torch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

# Planning ruling 6 (D21): Parler is adopted only if all three hold.
MAX_RTF = 10.0
MAX_RSS_MB = 6000.0
MAX_LOOSE_WER = 0.25
WER_LANGUAGES = ("hi", "kn", "ta")


def rtf(synth_s: float, audio_s: float) -> float:
    """Real-time factor: synthesis wall time over audio duration (inf for empty audio)."""
    if audio_s <= 0:
        return float("inf")
    return synth_s / audio_s


def summarise(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Mean and max RTF over the non-warm-up rows, and peak RSS over all rows."""
    timed = [r for r in rows if not r.get("warmup")]
    rtfs = [rtf(r["synth_s"], r["audio_s"]) for r in timed]
    return {
        "n": len(timed),
        "rtf_mean": sum(rtfs) / len(rtfs) if rtfs else float("inf"),
        "rtf_max": max(rtfs) if rtfs else float("inf"),
        "peak_rss_mb": max((r.get("rss_mb", 0.0) for r in rows), default=0.0),
    }


def passes(
    summary: Mapping[str, float], wer_by_lang: Mapping[str, float]
) -> tuple[bool, list[str]]:
    """Check the three thresholds. Returns (ok, reasons for failing)."""
    reasons: list[str] = []
    if summary["rtf_mean"] > MAX_RTF:
        reasons.append(f"RTF mean {summary['rtf_mean']:.1f} above {MAX_RTF:g}")
    if summary["peak_rss_mb"] > MAX_RSS_MB:
        reasons.append(f"peak RSS {summary['peak_rss_mb']:.0f} MB above {MAX_RSS_MB:g} MB")
    for lang in WER_LANGUAGES:
        wer = wer_by_lang.get(lang)
        if wer is None:
            reasons.append(f"no loose WER for {lang}")
        elif wer > MAX_LOOSE_WER:
            reasons.append(f"loose WER {lang} {wer:.0%} above {MAX_LOOSE_WER:.0%}")
    return (not reasons, reasons)


def safe_revision(lookup: Callable[[], str | None]) -> str | None:
    """Model revision from a network lookup; None if it fails, so bench.json is still written."""
    try:
        return lookup()
    except Exception:  # offline, auth or Hub error: the revision is only metadata
        return None

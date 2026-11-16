"""Fail when tracked text files contain emoji.

Usage: python -m tools.no_emoji [PATH ...]
With no paths, scans every file listed by `git ls-files`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Inclusive code point ranges treated as emoji or emoji modifiers.
_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F000, 0x1FAFF),  # pictographs, emoticons, transport, flags, supplemental symbols
    (0x2600, 0x27BF),  # miscellaneous symbols, dingbats
    (0x2B00, 0x2BFF),  # miscellaneous symbols and arrows (stars, circles)
    (0x231A, 0x231B),
    (0x2328, 0x2328),
    (0x23CF, 0x23CF),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0xFE0F, 0xFE0F),  # variation selector-16 (emoji presentation)
    (0x20E3, 0x20E3),  # combining enclosing keycap
)

_SNIFF_BYTES = 8192


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _RANGES)


def find_emoji(text: str) -> list[tuple[int, int, str]]:
    """Return (line, column, character) for each emoji, 1-based."""
    hits: list[tuple[int, int, str]] = []
    # Split on "\n" only: str.splitlines() also breaks on form feed, U+2028 and
    # others, which would shift line numbers away from what an editor shows.
    for line_no, line in enumerate(text.split("\n"), start=1):
        for col, ch in enumerate(line, start=1):
            if _is_emoji(ch):
                hits.append((line_no, col, ch))
    return hits


def _read_text(path: Path) -> str | None:
    """Return file text, or None for binary or non-UTF-8 files."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:_SNIFF_BYTES]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_paths(paths: list[Path]) -> list[tuple[Path, int, int, str]]:
    """Scan files and return (path, line, column, character) for each emoji."""
    results: list[tuple[Path, int, int, str]] = []
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        results.extend((path, line, col, ch) for line, col, ch in find_emoji(text))
    return results


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True).stdout.decode(
        "utf-8"
    )
    return [Path(p) for p in out.split("\0") if p]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        paths = [Path(a) for a in args]
        # A path named on the command line must exist; a typo must not look clean.
        bad = [p for p in paths if not p.is_file()]
        for p in bad:
            print(f"{p}: not a readable file", file=sys.stderr)
        if bad:
            return 2
    else:
        paths = _tracked_files()
    hits = scan_paths(paths)
    for path, line, col, ch in hits:
        print(f"{path}:{line}:{col}: U+{ord(ch):04X}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())

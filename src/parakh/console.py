"""Console safety: never crash on a character the terminal encoding cannot show."""

import sys
from typing import TextIO


def configure_console(*streams: TextIO) -> None:
    """Make streams write unencodable characters as backslash escapes.

    The encoding is kept. Streams without reconfigure (pytest capture, StringIO)
    are skipped.
    """
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")

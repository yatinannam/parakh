import io

from parakh.console import configure_console


def test_console_survives_cp1252():
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    configure_console(stream)
    stream.write("हाँ")
    stream.flush()
    assert stream.encoding == "cp1252"
    assert stream.buffer.getvalue() == rb"\u0939\u093e\u0901"  # type: ignore[attr-defined]


def test_console_skips_streams_without_reconfigure():
    configure_console(io.StringIO())

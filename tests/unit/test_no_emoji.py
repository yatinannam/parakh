from tools.no_emoji import find_emoji, main, scan_paths


def test_plain_text_clean():
    assert find_emoji("Latency p95 is 840 ms.\n") == []


def test_emoji_flagged_with_position():
    assert find_emoji("ok\nall good \u2705\n") == [(2, 10, "\u2705")]


def test_flag_and_star_and_pictograph_flagged():
    hits = find_emoji("\U0001f1ee\U0001f1f3 \u2b50 \U0001f680")
    assert {h[2] for h in hits} >= {"\U0001f1ee", "\u2b50", "\U0001f680"}


def test_variation_selector_flagged():
    assert find_emoji("\u2764\ufe0f")


def test_non_emoji_unicode_not_flagged():
    assert find_emoji("\u0926\u094b \u0964 \u00b120 ms 2 \u00d7 2 \u2014 \u20b9500 ky\u0101") == []


def test_binary_and_undecodable_files_skipped(tmp_path):
    d = tmp_path / "dir with space"
    d.mkdir()
    (d / "a.wav").write_bytes(b"RIFF\x00\xff\xfe\x00")
    (d / "b.md").write_text("fine\n", encoding="utf-8")
    (d / "c.md").write_text("bad \U0001f600\n", encoding="utf-8")
    (d / "d.txt").write_bytes(b"\xff\xfe not utf-8")
    hits = scan_paths([d / "a.wav", d / "b.md", d / "c.md", d / "d.txt"])
    assert [(p.name, line) for p, line, _, _ in hits] == [("c.md", 1)]


def test_main_reports_and_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "dir with space" / "x.md"
    bad.parent.mkdir()
    bad.write_text("a\n\U0001f600\n", encoding="utf-8")
    assert main([str(bad)]) == 1
    assert "x.md:2:1: U+1F600" in capsys.readouterr().out
    good = bad.with_name("y.md")
    good.write_text("plain\n", encoding="utf-8")
    assert main([str(good)]) == 0

import pytest

from tools.parler_bench.parler_bench.metrics import passes, rtf, summarise

GOOD_WER = {"hi": 0.1, "kn": 0.2, "ta": 0.25}


def _rows(*rtfs, rss=3000.0, warmup=True):
    rows = [{"language": "en", "audio_s": 2.0, "synth_s": 30.0, "rss_mb": rss, "warmup": warmup}]
    rows += [
        {"language": "hi", "audio_s": 2.0, "synth_s": 2.0 * r, "rss_mb": rss, "warmup": False}
        for r in rtfs
    ]
    return rows


def test_rtf():
    assert rtf(6.0, 2.0) == pytest.approx(3.0)
    assert rtf(1.0, 0.0) == float("inf")


def test_summarise_excludes_warmup():
    s = summarise(_rows(2.0, 6.0, rss=4100.0))
    assert s["rtf_mean"] == pytest.approx(4.0)
    assert s["rtf_max"] == pytest.approx(6.0)
    assert s["peak_rss_mb"] == pytest.approx(4100.0)
    assert s["n"] == 2


def test_summarise_empty_is_inf():
    assert summarise([])["rtf_max"] == float("inf")


def test_passes_thresholds():
    ok, why = passes({"rtf_mean": 4.0, "rtf_max": 10.0, "peak_rss_mb": 6000.0}, GOOD_WER)
    assert ok and why == []
    ok, why = passes({"rtf_mean": 11.0, "rtf_max": 12.0, "peak_rss_mb": 100.0}, GOOD_WER)
    assert not ok and len(why) == 1 and "RTF" in why[0]
    ok, why = passes({"rtf_mean": 1.0, "rtf_max": 1.0, "peak_rss_mb": 6001.0}, GOOD_WER)
    assert not ok and len(why) == 1 and "RSS" in why[0]
    ok, why = passes(
        {"rtf_mean": 1.0, "rtf_max": 1.0, "peak_rss_mb": 1.0}, {**GOOD_WER, "kn": 0.26}
    )
    assert not ok and len(why) == 1 and "kn" in why[0]
    ok, why = passes({"rtf_mean": 1.0, "rtf_max": 1.0, "peak_rss_mb": 1.0}, {"hi": 0.1})
    assert not ok and any("kn" in w for w in why) and any("ta" in w for w in why)


def test_safe_revision():
    from tools.parler_bench.parler_bench.metrics import safe_revision

    def boom():
        raise OSError("offline")

    assert safe_revision(lambda: "abc123") == "abc123"
    assert safe_revision(boom) is None

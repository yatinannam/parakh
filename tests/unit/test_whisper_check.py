import json
from pathlib import Path

import httpx
import pytest

from tools.whisper_check import check, main

BENCH = {
    "rows": [
        {"file": "s1.wav", "text": "hello doctor", "language": "en", "warmup": True},
        {"file": "s2.wav", "text": "namaste doctor rao", "language": "hi", "warmup": False},
        {"file": "s3.wav", "text": "namaskara doctor rao", "language": "kn", "warmup": False},
        {"file": "s4.wav", "text": "vanakkam doctor rao", "language": "ta", "warmup": False},
    ],
    "summary": {"rtf_mean": 3.0, "rtf_max": 4.0, "peak_rss_mb": 4000.0},
}


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "out dir"
    out.mkdir()
    (out / "bench.json").write_text(json.dumps(BENCH), encoding="utf-8")
    for row in BENCH["rows"]:
        (out / row["file"]).write_bytes(b"RIFFfake")
    return out


def _transport(replies: dict[str, str], seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("latin-1")
        lang = next(line for line in body.split("\r\n") if line in ("hi", "kn", "ta", "en"))
        seen.append({"lang": lang, "auth": request.headers["authorization"]})
        return httpx.Response(200, json={"text": replies[lang]})

    return httpx.MockTransport(handler)


async def test_whisper_check_scores_by_language(tmp_path):
    out = _out(tmp_path)
    seen: list[dict] = []
    replies = {
        "en": "hello doctor",
        "hi": "namaste doctor rao",
        "kn": "namaskara doctor rao",
        "ta": "vanakkam doctor rao",
    }
    result = await check(
        out, api_key="k", transport=_transport(replies, seen), quota_dir=tmp_path / "q"
    )
    assert result["passes"] is True
    assert result["wer_by_lang"]["hi"] == 0.0
    assert {s["lang"] for s in seen} == {"en", "hi", "kn", "ta"}
    assert all(s["auth"] == "Bearer k" for s in seen)
    written = json.loads((out / "wer.json").read_text(encoding="utf-8"))
    assert written["passes"] is True


async def test_whisper_check_fails_on_bad_language(tmp_path):
    out = _out(tmp_path)
    replies = {
        "en": "x",
        "hi": "namaste doctor rao",
        "kn": "totally wrong words",
        "ta": "vanakkam doctor rao",
    }
    result = await check(
        out, api_key="k", transport=_transport(replies, []), quota_dir=tmp_path / "q"
    )
    assert result["passes"] is False
    assert any("kn" in r for r in result["reasons"])


def test_whisper_check_refuses_without_key(tmp_path, monkeypatch, capsys):
    out = _out(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main([str(out)]) == 2
    err = capsys.readouterr().err
    assert "GROQ_API_KEY" in err


def test_whisper_check_missing_bench_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert main([str(tmp_path)]) == 2


@pytest.mark.parametrize("bad", ["{not json", "[]"])
def test_whisper_check_unreadable_bench_is_error(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    (tmp_path / "bench.json").write_text(bad, encoding="utf-8")
    assert main([str(tmp_path)]) == 2

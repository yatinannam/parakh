"""Check that Parler clips are intelligible: transcribe them with Groq Whisper, score loose WER.

Usage: python -m tools.whisper_check OUT_DIR [--groq-url URL]
Reads OUT_DIR/bench.json, writes OUT_DIR/wer.json. Exit 0 pass, 1 fail, 2 error.
Only synthetic clips (Parler output of synthetic text) are sent. The key is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from parakh.budget import DailyCounter, TokenBucket, send_with_backoff
from parakh.budget.guard import remote_call
from parakh.env import load_env
from parakh.score.wer import loose_wer
from tools.parler_bench.parler_bench.metrics import passes

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"
WHISPER_RPM = 20
WHISPER_RPD = 2000
QUOTA_ROOT = Path(".cache/quota")
WER_LANGUAGE = {"hi": "hi-en", "kn": "kn-en", "ta": "ta-en", "en": "en"}


async def check(
    out_dir: Path,
    *,
    api_key: str,
    groq_url: str = GROQ_URL,
    transport: httpx.AsyncBaseTransport | None = None,
    quota_dir: Path = QUOTA_ROOT,
) -> dict[str, Any]:
    """Transcribe each clip in bench.json, write wer.json and return it."""
    bench = json.loads((out_dir / "bench.json").read_text(encoding="utf-8"))
    remote_call("groq", real=False)
    bucket = TokenBucket(WHISPER_RPM)
    counter = DailyCounter(quota_dir, "groq", MODEL, WHISPER_RPD)
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(transport=transport, timeout=60.0) as client:
        for row in bench["rows"]:
            lang = row["language"]
            wav = (out_dir / row["file"]).read_bytes()

            async def send(wav: bytes = wav, name: str = row["file"], lang: str = lang):
                return await client.post(
                    groq_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (name, wav, "audio/wav")},
                    data={"model": MODEL, "language": lang, "response_format": "json"},
                )

            resp = await send_with_backoff(
                send, provider="groq", model=MODEL, real=False, bucket=bucket, counter=counter
            )
            resp.raise_for_status()
            hyp = str(resp.json()["text"])
            wer = loose_wer(row["text"], hyp, WER_LANGUAGE[lang])
            rows.append({"file": row["file"], "language": lang, "hyp": hyp, "wer": wer})
    wer_by_lang: dict[str, float] = {}
    for lang in WER_LANGUAGE:
        values = [r["wer"] for r in rows if r["language"] == lang and r["wer"] is not None]
        if values:
            wer_by_lang[lang] = sum(values) / len(values)
    ok, reasons = passes(bench["summary"], wer_by_lang)
    result = {"rows": rows, "wer_by_lang": wer_by_lang, "passes": ok, "reasons": reasons}
    (out_dir / "wer.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisper_check", description=__doc__)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--groq-url", default=GROQ_URL)
    args = parser.parse_args(argv)
    load_env()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        print("error: GROQ_API_KEY is not set (put it in .env)", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(check(args.out_dir, api_key=key, groq_url=args.groq_url))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: cannot read the benchmark output: {type(exc).__name__}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"error: Groq request failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    except Exception as exc:  # quota, 402 and rate-limit errors from the budget layer
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for lang, wer in result["wer_by_lang"].items():
        print(f"loose WER {lang}: {wer:.0%}")
    if result["passes"]:
        print("PASS: Parler meets all three thresholds")
        return 0
    print("FAIL: " + "; ".join(result["reasons"]))
    return 1


if __name__ == "__main__":
    sys.exit(main())

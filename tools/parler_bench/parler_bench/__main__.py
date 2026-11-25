"""Benchmark Indic Parler-TTS on this CPU.

Run: uv run --project tools/parler_bench python -m parler_bench --out tools/parler_bench/out
Needs HF_TOKEN in .env (read here, never printed) and a 3.75 GB model download.
Then score intelligibility: uv run python -m tools.whisper_check tools/parler_bench/out
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from importlib import metadata
from pathlib import Path

import psutil
import soundfile as sf
import yaml
from dotenv import load_dotenv
from parler_bench.metrics import rtf, safe_revision, summarise

MODEL_ID = "ai4bharat/indic-parler-tts"
SENTENCES = Path(__file__).with_name("sentences.yaml")
REPO_ROOT = Path(__file__).resolve().parents[3]


class PeakRss:
    """Samples this process's resident memory in a thread and keeps the maximum."""

    def __init__(self, interval_s: float = 0.2) -> None:
        self._proc = psutil.Process()
        self._interval = interval_s
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def sample(self) -> float:
        self.peak_mb = max(self.peak_mb, self._proc.memory_info().rss / 1e6)
        return self.peak_mb

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.sample()

    def __enter__(self) -> PeakRss:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self.sample()


def _heavy_lock(owner: str):
    """Use Parakh's heavy-model lock (stdlib plus psutil) so Parler and Whisper never overlap."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from parakh.heavy import heavy_model_lock

    return heavy_model_lock(owner)


def run(out: Path) -> int:
    load_dotenv(Path.cwd() / ".env", override=False)
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        print("error: HF_TOKEN is not set (put it in .env)", file=sys.stderr)
        return 2
    import torch
    from huggingface_hub import model_info
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    out.mkdir(parents=True, exist_ok=True)
    sentences = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))["sentences"]
    revision = safe_revision(lambda: model_info(MODEL_ID, token=token).sha)
    torch.set_num_threads(os.cpu_count() or 1)
    rows: list[dict] = []
    with PeakRss() as mem:
        t0 = time.perf_counter()
        model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_ID, token=token)
        model.eval()
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=token)
        desc_tokenizer = AutoTokenizer.from_pretrained(
            model.config.text_encoder._name_or_path, token=token
        )
        load_s = time.perf_counter() - t0
        rate = model.config.sampling_rate
        for i, item in enumerate(sentences):
            desc = desc_tokenizer(item["description"], return_tensors="pt")
            prompt = tokenizer(item["text"], return_tensors="pt")
            start = time.perf_counter()
            with torch.inference_mode():
                audio = model.generate(
                    input_ids=desc.input_ids,
                    attention_mask=desc.attention_mask,
                    prompt_input_ids=prompt.input_ids,
                    prompt_attention_mask=prompt.attention_mask,
                )
            synth_s = time.perf_counter() - start
            wav = audio.cpu().numpy().squeeze()
            name = f"s{i + 1:02d}-{item['language']}.wav"
            sf.write(str(out / name), wav, rate)
            audio_s = len(wav) / rate
            mem.sample()
            rows.append(
                {
                    "file": name,
                    "language": item["language"],
                    "text": item["text"],
                    "warmup": i == 0,
                    "audio_s": audio_s,
                    "synth_s": synth_s,
                    "rtf": rtf(synth_s, audio_s),
                    "rss_mb": mem.peak_mb,
                }
            )
            print(f"{name}: {audio_s:.1f} s audio, RTF {rows[-1]['rtf']:.1f}")
    bench = {
        "rows": rows,
        "summary": summarise(rows),
        "warmup_s": rows[0]["synth_s"],
        "load_s": load_s,
        "versions": {
            "torch": torch.__version__,
            "parler_tts": metadata.version("parler_tts"),
            "transformers": metadata.version("transformers"),
            "model_revision": revision,
        },
    }
    (out / "bench.json").write_text(json.dumps(bench, indent=2), encoding="utf-8")
    print(f"wrote {out / 'bench.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="parler_bench", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    with _heavy_lock("parler_bench"):
        return run(args.out)


if __name__ == "__main__":
    sys.exit(main())

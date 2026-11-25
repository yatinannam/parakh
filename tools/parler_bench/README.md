# Parler benchmark

Isolated uv project. It benchmarks `ai4bharat/indic-parler-tts` on this CPU. torch,
transformers and parler-tts live only here, never in Parakh's own lock or CI.

1. Put `HF_TOKEN` in `.env` (free account; accept the model terms).
2. `uv run --project tools/parler_bench python -m parler_bench --out tools/parler_bench/out`
   (downloads 3.75 GB; writes WAVs and `bench.json`).
3. `uv run python -m tools.whisper_check tools/parler_bench/out` (main env, Groq Whisper;
   writes `wer.json`; exit 0 pass, 1 fail, 2 error).

Adopt Parler only if mean RTF <= 10 (mean after the warm-up sentence; the maximum is
reported alongside it, not gated), peak RSS <= 6000 MB and loose WER <= 25 % in each of
Hindi, Kannada and Tamil (planning ruling 6, D21).

# API keys

Parakh uses free tiers only. If any provider asks for a credit or debit card at any point, stop, do not enter one, and record what happened in this file (spec EC-17).

Keys live in `.env` at the repo root. `.env` is gitignored; `.env.example` lists the names with empty values. Never paste a key into a commit, an issue, a log or a chat.

## Groq (required from M1)

Used by the test agent (Whisper STT and chat LLM) and by the LLM judge.

1. Sign up at <https://console.groq.com> with an email or GitHub login. No card is needed for the free tier.
2. Open **API Keys** and create a key named `parakh-dev`.
3. Copy `.env.example` to `.env` and set `GROQ_API_KEY=<key>`.
4. Optional, recommended: in **Settings, Data Controls**, turn on Zero Data Retention.
5. Verify. This only lists models; no prompts or audio are sent:

   ```
   uv run python -m tools.check_keys
   ```

   Expected output: `groq: ok (<n> models; whisper-large-v3-turbo: yes)`.
   Exit code 2 means the key is missing, 1 means the request failed (the HTTP status is printed, the key is not).

Free-tier limits are per organisation, not per key. A second key does not add quota. See `docs/research/2026-11-15-free-tier-and-platform-notes.md`.

## Gemini (judge fallback, optional)

The judge asks Groq first and falls back to Gemini. The key is optional: without it the judge runs on Groq alone, and with neither key a run's judge is `skipped`.

1. Open Google AI Studio (aistudio.google.com) and sign in with a Google account.
2. Create an API key. Check that no card is asked for at any step (EC-17); if one is, stop and do not continue.
3. Put the key in `.env` as `GEMINI_API_KEY=...`. `.env` stays out of git.
4. Check it with `uv run python -m tools.check_keys`. It prints `gemini: set` or `gemini: not set (optional)` and never the value.

The free tier may use inputs for training and human review, so the judge sends synthetic transcripts only.

`rpd: 20` in `src/parakh/judge/judge.yaml` is conservative. Check AI Studio for the project's real limit and raise it there if it is higher.

## Hugging Face (Parler benchmark, optional)

Only the Indic Parler-TTS benchmark in `tools/parler_bench/` uses it. Parakh itself never does. The model `ai4bharat/indic-parler-tts` (Apache-2.0) is gated, with automatic approval.

1. Sign up at <https://huggingface.co> with an email. No card is needed. If one is asked for at any step, stop (EC-17).
2. While logged in, open <https://huggingface.co/ai4bharat/indic-parler-tts> and accept the model's terms. Access is granted at once.
3. In **Settings, Access Tokens**, create a token with the **Read** role.
4. Put it in `.env` as `HF_TOKEN=...`. `.env` stays out of git.
5. Check it with `uv run python -m tools.check_keys`. It prints `hf_token: set` or `hf_token: not set (optional)` and never the value.

The benchmark's only Hugging Face requests are the model download (about 3.75 GB) and a lookup of the model revision. It synthesises the sentences on the laptop. Its synthetic clips then go to Groq Whisper for the intelligibility check.

## OpenRouter (Task 1 only)

Used only to run Calibrate's text simulation inside WSL. Its key never goes into this repo's `.env`; see [`calibrate-wsl.md`](calibrate-wsl.md).

## If a key leaks

1. Revoke it at the provider first (Groq console, API Keys, delete).
2. Create a new key and update `.env`.
3. If it reached a commit, treat the old key as public even after rewriting history. GitHub push protection and gitleaks should block this before it happens.

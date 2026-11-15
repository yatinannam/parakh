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

## Gemini (M3)

Judge fallback only. The free tier may use inputs for training and human review, so it receives synthetic transcripts only. Set-up steps are added in M3.

## OpenRouter (Task 1 only)

Used only to run Calibrate's text simulation inside WSL. Its key never goes into this repo's `.env`; see [`calibrate-wsl.md`](calibrate-wsl.md).

## If a key leaks

1. Revoke it at the provider first (Groq console, API Keys, delete).
2. Create a new key and update `.env`.
3. If it reached a commit, treat the old key as public even after rewriting history. GitHub push protection and gitleaks should block this before it happens.

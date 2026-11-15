# Free tiers and platform notes

Date: 2026-11-15. Figures marked "third-party" come from aggregator sites, not the provider's own docs. Re-check before relying on them; free tiers change often.

## Laptop facts (checked)

- Windows 11, Intel Core Ultra 5 225U, 16 GB RAM, no discrete GPU.
- Python 3.11 installed (`py -3.11`). ffmpeg 9.0.2 on PATH.
- WSL2 with Ubuntu installed (stopped). Docker Desktop's WSL distro present.
- Repo lives inside OneDrive (`Documents/Yatin/Projects/parakh`), so anything inside it syncs.
- `gh` CLI logged in as `yatinannam`. Repo `yatinannam/parakh` is **public**, so GitHub Actions minutes are free.

## Prebuilt Windows wheels for Python 3.11 (checked with `pip download --only-binary=:all:`)

| Package | Wheel? |
|---|---|
| `pipecat-ai` 1.11.0 | yes (pure Python) |
| `faster-whisper` 1.2.1 | yes (pure Python) |
| `ctranslate2` 4.9.0 | yes, `cp311-win_amd64` |
| `onnxruntime` 1.32.0 | yes, `cp311-win_amd64` |
| `edge-tts` 7.3.1 | yes (pure Python) |
| `simpleaudio` | **no** (Calibrate dependency) |

## LLM and speech APIs

| Provider | Free tier (approx.) | Data use | Card needed? |
|---|---|---|---|
| Groq | Whisper large-v3 / v3-turbo: 20 RPM, 2,000 RPD, 7,200 audio-seconds per hour (third-party, matches a docs snapshot). Chat-model limits vary by model and sources conflict. Limits are per organisation, not per key. | Groq says it does not train on customer data; inference logs kept up to 30 days; Zero Data Retention can be switched on in Data Controls. | No for free tier. A card is needed only to move up to the Developer tier. |
| Google Gemini API | Per-model RPM/RPD shown in AI Studio; Dec 2025 cuts reportedly reduced Flash free quota sharply (third-party). | **Unpaid tier content may be used to improve Google products, and human reviewers may read it.** Synthetic data only. | No. |
| OpenRouter `:free` models | About 50 requests/day with < $10 lifetime credits, 20 RPM (third-party). | Varies by upstream provider. Synthetic data only. | No. |
| edge-tts | Unofficial client for Microsoft Edge read-aloud. No key, no published quota. Has broken before when Microsoft changed its auth token. | Text goes to Microsoft. Synthetic text only. | No. |

Rule from CLAUDE.md: send only synthetic data to free-tier LLM APIs.

## Local models

- faster-whisper `small` int8 on CPU: fine for scoring, weak on Hinglish (CLAUDE.md). Model download is about 0.5 GB.
- Indic Parler-TTS: no published CPU real-time factor found. Third-party reports call CPU inference slow. Must benchmark here before relying on it. Run it and Whisper one after the other, never together.

## Sources

- [Groq free tier rate limits (third-party)](https://klymentiev.com/blog/groq-api-free-tier)
- [Groq: Your data](https://console.groq.com/docs/your-data)
- [Gemini API data logging and sharing](https://ai.google.dev/gemini-api/docs/logs-policy)
- [Gemini API terms preview](https://ai.google.dev/gemini-api/terms_preview)
- [OpenRouter free model limits (third-party)](https://www.truefoundry.com/es/blog/openrouter-rate-limits-your-free-tier-depends-on-what-youve-already-paid)
- [Indic Parler-TTS model card](https://huggingface.co/ai4bharat/indic-parler-tts)

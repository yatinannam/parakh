# Calibrate analysis (Task 1, source review)

Date: 2026-11-15
Subject: [ARTPARK-SAHAI-ORG/calibrate](https://github.com/ARTPARK-SAHAI-ORG/calibrate), PyPI `calibrate-agent`
Commit reviewed: `96eacf0` (2026-11-11, "Simulated caller talks over the agent when it cuts in (#219)")
License: CC-BY-SA-4.0. Parakh is MIT. **No Calibrate code is copied into this repo.** This note describes behaviour in our own words and points at file paths for reference only.

Status: source review done. The "run one simulation" half of Task 1 is still open; see [Blockers for running it](#blockers-for-running-it-on-this-laptop-for-free).

## What Calibrate is

An evaluation framework for text and voice agents, built on Pipecat (`pipecat-ai==1.11.0`, pinned). CLI modes: STT benchmark, TTS benchmark, LLM tests, text simulations, voice simulations. It also has a hosted web app and cloud sync (`api.calibrate.artpark.ai`), plus Langfuse tracing.

## Coverage against Parakh's three questions

| Parakh question | Calibrate today | Evidence (path in Calibrate repo) |
|---|---|---|
| Code-mixed Hinglish scoring | **Partial, and not for external agents.** Personas speak `english`, `hindi` or `kannada`; no Hinglish or code-mixed persona language. STT WER uses jiwer plus AI4Bharat-style Indic normalisation (NFC and `IndicNormalizer`) per single language. LLM-judge "semantic WER" variants exist. For external WebSocket agents, the STT judge is **skipped on purpose**, because the agent may transcribe in a different script (romanised Hindi vs Devanagari) and positional pairing gives a misleading score. | `calibrate_agent/stt/metrics.py`, `calibrate_agent/stt/semantic_wer/`, `calibrate_agent/agent/run_simulation.py` (comment near the STT judge step) |
| 8 kHz codec and noise degradation | **None found.** No resampling to 8 kHz, no mu-law/A-law, no noise mixing, no SNR control, no packet loss. Searches for `8000`, `mulaw`, `ulaw`, `g711`, `codec`, `noise`, `snr`, `telephon`, `resampl` in the package return only unrelated hits (silence buffers, output file codec names, comments about VAD noise). | grep over `calibrate_agent/` |
| Latency measurement | **Yes.** Sim-side wall-clock end-to-end latency (end of simulated-user turn to first agent audio), mean per simulation. Pipecat TTFB metrics and Pipecat's `UserBotLatencyObserver` for the internal agent. Only the mean is reported; no p50/p95, no per-turn breakdown found in the summary row. | `calibrate_agent/agent/run_simulation.py` (`EndToEndLatencyTracker`), `calibrate_agent/agent/bot.py` |

Other things Calibrate already does well:
- Persona and scenario simulations, text and voice.
- Interruptions: persona-level `sensitivity` (0/20/40/60 % of agent turns) with word-count cut-in, and scenario-level `when_agent_says` phrase trigger. The newest commit makes the simulated caller keep talking over the agent.
- LLM judges per evaluator, binary or rating, with configurable `judge_model` (OpenRouter id).
- External agents: text over HTTP (OpenAI-style `messages` POST) and voice over WebSocket **only if the agent speaks Pipecat's protobuf frame protocol**.

## What Calibrate lacks (Parakh's opening)

1. Telephone-channel degradation: 8 kHz, G.711 mu-law, band-limit, noise at set SNR, packet loss, clipping.
2. Code-mixed scoring that tolerates script (Devanagari vs Roman) and spelling variants, usable for external agents.
3. A deterministic task-success check on the agent's end state (Calibrate leans on LLM judges and tool-call tests).
4. Latency distribution (p50/p95 per turn) and barge-in stop latency (time for the agent to go quiet after the caller cuts in).
5. A free path. See below.
6. Kannada-English and Tamil-English code-mixing.

## Blockers for running it on this laptop for free

1. **Windows install fails.** Calibrate depends on `simpleaudio`, which has no prebuilt Windows wheel for Python 3.11 (`pip download simpleaudio --only-binary=:all: --platform win_amd64 --python-version 3.11` finds nothing). It would need MSVC Build Tools to compile. WSL2 Ubuntu is already installed on this laptop and is the cleaner route (it also keeps the CC-BY-SA package away from the Parakh environment).
2. **Voice simulation is not free as shipped.**
   - The simulated caller's LLM is a fixed constant, `google/gemini-3.5-flash-lite` on OpenRouter, a paid model (`calibrate_agent/agent/bot.py`).
   - The simulated caller's voice is ElevenLabs for English and Hindi, Google Chirp3-HD for Kannada. Google Cloud TTS needs a billing account (card). The ElevenLabs free plan gates some library voices, and third-party sources disagree on whether its free plan includes API access.
   - Default judge is `openai/gpt-5.4-mini` (paid), though `judge_model` can be overridden per evaluator.
3. **Text simulation can be free.** `--model` and `--provider` are CLI flags, and `judge_model` is per evaluator, so an OpenRouter `:free` model can drive both sides. OpenRouter accounts with no purchased credits get about 50 free-model requests per day and 20 per minute (third-party figures; confirm on openrouter.ai). One short simulation fits.

## Verdict (provisional, pending the run)

Calibrate covers simulation, personas, interruptions and mean latency. It does not cover phone-channel degradation, script-tolerant code-mixed scoring for external agents, deterministic task success, or a free voice path. Parakh should stand alone, and stay compatible: its transport should speak Pipecat's WebSocket protocol so one test agent works with both tools.

## Sources

- [calibrate-agent on PyPI](https://pypi.org/project/calibrate-agent/)
- [ARTPARK-SAHAI-ORG/calibrate](https://github.com/ARTPARK-SAHAI-ORG/calibrate) at `96eacf0`
- [OpenRouter free tier limits (TrueFoundry summary)](https://www.truefoundry.com/es/blog/openrouter-rate-limits-your-free-tier-depends-on-what-youve-already-paid)
- [ElevenLabs: why can't I use some voices from the Voice Library](https://elevenlabs.io/docs/help-center/product/voice-customization/voice-library/why-cant-i-use-some-voices-from-the-voice-library)

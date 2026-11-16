# Calibrate analysis (Task 1)

Date: 2026-11-15
Subject: [ARTPARK-SAHAI-ORG/calibrate](https://github.com/ARTPARK-SAHAI-ORG/calibrate), PyPI `calibrate-agent`
Commit reviewed: `96eacf0` (2026-11-11, "Simulated caller talks over the agent when it cuts in (#219)")
License: CC-BY-SA-4.0. Parakh is MIT. **No Calibrate code is copied into this repo.** This note describes behaviour in our own words and points at file paths for reference only.

Status: done. Source review on 2026-11-15; one text simulation run on free models on 2026-11-16 (see [Run](#run-2026-11-16)).

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
3. **Text simulation can be free, but not from the CLI alone.** `--model` and `--provider` are CLI flags and `judge_model` is per evaluator, but the CLI passes `--model` to the agent only. The simulated user keeps `user_model="openai/gpt-4.1"` (paid) with no flag to change it, and the judge falls back to `openai/gpt-5.4-mini` (paid) when an evaluator names no `judge_model` (`calibrate_agent/llm/run_simulation.py`, `calibrate_agent/judges.py`). Parakh's MIT wrapper `tools/calibrate_eval/run_text_sim.py` forces one `:free` model onto all three roles. OpenRouter accounts with no purchased credits get about 50 free-model requests per day and 20 per minute (third-party figures). One short simulation fits.

## Run (2026-11-16)

Set-up: WSL2 Ubuntu 24.04, Python 3.12.3, `calibrate-agent==0.0.81` (pulls `pipecat-ai==1.11.0`) in its own virtual environment under `~/calibrate-eval`, outside this repo. Steps: [`docs/runbooks/calibrate-wsl.md`](../runbooks/calibrate-wsl.md). The OpenRouter key reported `is_free_tier: true` and usage 0 before and after; no card, no credits.

Model: `nvidia/nemotron-3-ultra-550b-a55b:free` for the agent, the simulated user and the judge. Picked from the `:free` list as the largest instruction-tuned model; a one-request probe returned HTTP 200 first.

Config: [`tools/calibrate_eval/text_sim_config.json`](../../tools/calibrate_eval/text_sim_config.json). One synthetic clinic receptionist, one Hinglish caller persona (persona language `english`, since Calibrate has no code-mixed option), one booking scenario, one binary evaluator `booked_correctly`, at most 6 turns.

| Attempt | Outcome | Requests | Wall time |
|---|---|---|---|
| 1 | Pipecat setup timeout before any LLM call | 0 | 125 s |
| 2 | Agent called `end_call` as its first action; judge scored 0 | 2 | about 45 s |
| 3 | Full Hinglish booking, read back and confirmed; `booked_correctly` = 1 | 8 | 99 s |
| 4 | Same as 3 after the tracing fix; `booked_correctly` = 1 | 8 | 416 s |

About 19 free requests in total, plus one probe. Attempt 3 transcript, abridged:

```
Agent: Hello, Parakh Clinic. How can I help you today?
User:  Hello, mujhe Dr. Rao ke saath follow-up appointment chahiye kal subah 10:30 ke aas-paas. Possible hai?
Agent: Ji, Dr. Rao kal subah 9:00 se 12:00 tak available hain. 10:30 ka slot available hai. Aapka 10-digit mobile number batayein please.
User:  Mera mobile number hai 9845012345.
Agent: Theek hai. Booking confirm karte hain: Dr. Rao, kal subah 10:30, mobile number 9845012345. Kya ye sahi hai? Haan ya naa bolo.
User:  Haan, ye sahi hai. Shukriya, bye.
Agent: end_call (reason: booking confirmed, caller said goodbye)
```

### Findings from the run

1. **Cold start can exceed Pipecat's setup timeout.** Pipecat 1.11 waits for its deferred-import warm-up inside the 20 s pipeline setup timeout. The first run after install spent about 100 s importing and timed out in setup; the next run set up in 0.4 s. On a CPU laptop, rerun once after a fresh install.
2. **The agent prompt must say how the call opens and ends.** Calibrate gives the agent a built-in `end_call` tool ("End the current call when the conversation is complete"). With `agent_speaks_first` and only a system prompt in context, the model ended the call before anyone spoke. Adding "open the call yourself; never end it before the caller has spoken" fixed it. Parakh's own test agent needs the same rule.
3. **`ENABLE_TRACING=false` turns tracing on.** Calibrate reads `bool(os.getenv("ENABLE_TRACING"))`, so any non-empty value enables OpenTelemetry export (to `localhost:4318` here, refused, so nothing left the machine). The wrapper now removes the variable instead.
4. **Text simulations report no latency.** Per-request TTFB appears only in the DEBUG log, not in `metrics.json` or `results.csv`. Free-tier TTFB ranged from 0.8 s to 58 s within one run, so free-model latency is not a usable agent metric; Parakh must time its own test agent, not a hosted free model.
5. **Free-tier slowness trips Pipecat's idle timeout.** Attempt 4 ended on the pipeline idle timeout after a 71 s agent reply, not on `end_call`. The judge still scored the transcript.
6. **Hinglish held despite the language rule.** Calibrate appends "You must always speak in english." to the agent prompt for an `english` persona, yet the agent matched the caller's Hinglish, as our prompt asked. Code-mixing works in text, but nothing scores it: the judge prompt had to state that Hinglish is not an error.
7. **The judge is a single free LLM call** and its reasoning is in English, as asked. It is advisory; it cannot replace a deterministic end-state check.

## Verdict

Final, after the run. Calibrate covers simulation, personas, interruptions and mean latency, and its text simulation runs free once a wrapper forces a `:free` model onto every role. It does not cover phone-channel degradation, script-tolerant code-mixed scoring for external agents, deterministic task success, latency distribution, or a free voice path. The run confirmed each gap rather than closing any.

**Parakh stands alone and stays Pipecat-compatible** (spec approach A): its transport speaks Pipecat's WebSocket protocol so one test agent works with both tools. Parakh does not depend on, vendor or copy Calibrate.

## Sources

- [calibrate-agent on PyPI](https://pypi.org/project/calibrate-agent/)
- [ARTPARK-SAHAI-ORG/calibrate](https://github.com/ARTPARK-SAHAI-ORG/calibrate) at `96eacf0`
- [OpenRouter free tier limits (TrueFoundry summary)](https://www.truefoundry.com/es/blog/openrouter-rate-limits-your-free-tier-depends-on-what-youve-already-paid)
- [ElevenLabs: why can't I use some voices from the Voice Library](https://elevenlabs.io/docs/help-center/product/voice-customization/voice-library/why-cant-i-use-some-voices-from-the-voice-library)

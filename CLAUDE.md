# Parakh

Parakh tests voice agents on Indian speech: Hinglish code-mixing, phone-quality audio, and interruptions. It is a side project by Yatin, based in Bangalore.

## Hard constraints
- Everything must be free, with no credit or debit card. Use free API tiers only (Groq, Gemini).
- Hardware is a Windows laptop: Intel Core Ultra 5 225U, 16 GB RAM, no discrete GPU. All local models must run on CPU.
- Send only synthetic data to free-tier LLM APIs, because some providers may train on it.
- Never commit secrets. Keep keys in `.env` and keep `.env` in `.gitignore`.
- License is MIT. Do not copy code from Calibrate (ARTPARK-SAHAI, CC-BY-SA-4.0).

## Stack plan
Python 3.11, pydantic, pytest, edge-tts for caller audio (Indic Parler-TTS cached offline later), numpy/scipy/ffmpeg for degradation (8 kHz, mu-law, noise), faster-whisper small int8 on CPU for scoring, jiwer plus a script-tolerant normalizer for WER, a free-tier LLM as judge, a Pipecat test agent, GitHub Actions for CI.

## Pipeline
Scenario YAML -> generate and cache caller audio -> degrade -> send to agent over WebSocket with timestamps -> capture reply audio and transcript -> score latency, WER, task success (deterministic end state) and an LLM-judge rating -> JSON and HTML report.

## Task 1 (do this first)
Install `calibrate-agent` and run one simulation. Then check its repo for code-mixed Hinglish scoring, 8 kHz codec and noise degradation, and latency measurement. Report what it covers and what it lacks. The result decides whether Parakh stands alone or complements Calibrate.

## Build order
1. MVP: one scenario, clean audio, a Pipecat agent, latency plus WER.
2. Degradation presets: phone codec, noise, interruptions.
3. Indic layer: script-tolerant scorer and 10-20 Hinglish scenarios, then Kannada-English and Tamil-English.
4. HMS adapter and a GitHub Actions workflow.
5. Public release: README, scenario pack, comparison run.

## Known limits
Synthetic caller audio is cleaner than real speech, so add a small set of real recordings. Whisper small is weak on Hinglish, so prefer the agent's own transcript when available. Run Parler and Whisper one after the other, not together.

# `pipecat.evals` and Parakh

Date: 2026-11-16 (checked again against the installed package on 2026-11-17)
Subject: the `pipecat.evals` package in `pipecat-ai==1.16.0` (BSD-2-Clause), the version Parakh pins.
Outcome: decision D14 in the [design spec](../superpowers/specs/2026-11-15-parakh-design.md#12-decisions). Parakh keeps its own call driver; `pipecat.evals` is complementary.

This note describes behaviour in our own words, with module paths inside the installed `pipecat` package for reference. No Pipecat code is copied into Parakh; `pipecat-ai` is used only as a dependency.

## What it is

`pipecat.evals` is new in Pipecat 1.16. It is a behavioural test harness for Pipecat bots, run from the `pipecat eval` CLI command or from Python.

| Feature | What it does | Module |
|---|---|---|
| Scripted scenarios | YAML turns with expected events per turn: transcription, LLM response, TTS response, function calls with arguments, substring and regex checks on the text. | `evals/script.py` |
| Simulated scenarios | A persona LLM plays the caller from a persona, a goal and a success criterion, and holds the conversation on its own. | `evals/simulation.py`, `evals/persona.py` |
| Cached TTS user | The harness synthesises the user's turns with a real TTS service and caches the audio on disk, so repeat runs do not call the TTS again. | `evals/tts.py` (`CachingTTSService`) |
| LLM judge | Natural-language criteria on bot text and on function calls, scored by an LLM. | `evals/judge.py`, `evals/simulation_judge.py` |
| Suite runner | Runs a manifest of scenario files and collects the results. | `evals/suite.py` |
| Paced user audio | The harness sends user audio to the bot in real time, one 40 ms frame per tick, with silence between turns. | `evals/client_transport.py` |
| Latency budgets | `within_ms` on an expectation: the event must arrive within that many milliseconds of the turn's user send. The default is 60 s, so timing is not asserted unless it is set. | `evals/script.py` (`EvalExpectation`) |

## What it requires of the bot

The bot under test must run Pipecat's eval transport: `EvalTransport` (a variant of the single-client WebSocket server transport, `evals/transport.py`) or `EvalFastAPIWebsocketTransport` (`evals/fastapi_transport.py`), with `EvalSerializer` (`evals/serializer.py`). The wire format is RTVI plus eval messages of its own: `eval-connect`, `eval-configure`, `eval-context`, `eval-cancel` and `eval-image` from the harness, and `eval-bot-audio` and `eval-bot-image` from the bot.

So a bot has to be modified, or built for it, before `pipecat.evals` can test it. A bot that serves Pipecat's standard `ProtobufFrameSerializer` over a WebSocket, as Parakh's clinic agent does, cannot be driven by it unchanged.

## What it lacks for Parakh

| Parakh need | `pipecat.evals` 1.16 |
|---|---|
| Telephone-channel degradation (8 kHz, G.711 mu-law, noise at a set SNR, packet loss) | None. User audio goes to the bot as synthesised. |
| Script-tolerant WER for code-mixed speech (a Devanagari transcript scored against a Roman Hinglish reference) | None. Transcription checks are substring or regex matches, or an LLM judge. |
| Latency distributions (per-turn latency, p50, p95, max per run and per preset) | None. `within_ms` is a pass or fail budget per expectation, measured from the user send rather than from the end of the user's speech. |
| Unmodified agents | No. The bot must run the eval transport and serializer. |

## Decision (D14)

Decided by Claude, delegated by Yatin, on 2026-11-16.

Parakh keeps its own call driver (`src/parakh/caller`, `src/parakh/transport`). It speaks Pipecat's standard protobuf frame protocol, so it can test an unmodified Pipecat agent, and it owns the parts `pipecat.evals` does not have: the 20 ms real-time pacer with a jitter check, the virtual playback clock, latency measured from the caller's speech end, telephone degradation (M2) and the script-tolerant scorer.

`pipecat.evals` is complementary. A team that already runs it for behavioural checks (function calls, response content, a persona caller) can run Parakh on the same bot for audio-channel and Hinglish recognition measurements. Parakh does not depend on it and copies none of its code.

Revisit the decision if a later Pipecat release lets `pipecat.evals` drive a bot that serves the standard protobuf serializer, or adds a degradation hook to the user-audio path.

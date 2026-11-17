# M1 run: the clinic agent and the Hinglish scenario

Runs one real call on this laptop: the Pipecat clinic test agent (Groq Whisper STT, Groq LLM, edge-tts) answers, Parakh plays the Hinglish caller over a WebSocket, then writes `report.json` and `report.html` with per-turn latency and strict and loose WER.

Only synthetic data leaves the laptop: the scenario text goes to edge-tts, its synthesised audio and the agent's transcripts go to Groq (spec constraint, `CLAUDE.md`).

## Before you start

- `uv sync --all-groups` once. It installs the `agent` group (`pipecat-ai[websocket,silero,groq]`).
- `ffmpeg -version` works. Parakh refuses to run without it.
- `.env` holds `GROQ_API_KEY`. Check it with `uv run python -m tools.check_keys`; see [`api-keys.md`](api-keys.md).

## 1. Check the Groq budget

```
uv run parakh budget scenarios/hinglish
```

Output on 2026-11-17:

```
scenarios: 1
STT calls: 4 (limits {'rpm': 20, 'rpd': 2000, 'audio_s_per_hour': 7200})
LLM calls: 5 (assumed limits {'rpm': 30, 'rpd': 1000}; check the console)
audio seconds: 15
RPM is not estimated
within limits
```

The estimate counts one STT request per caller turn and one LLM request per agent reply. The real agent uses more. Its VAD splits a caller turn at each pause, and every segment is one Groq STT request; tool calls add LLM requests. The completed runs below used 11 STT and 8 to 10 LLM requests each (counted from the agent log). That is still far inside the free tier: about 180 runs a day on the STT limit, and an 11-request call spread over about 70 s stays under 20 RPM. Leave a minute between runs anyway.

## 2. Start the agent (terminal 1)

```
uv run --group agent python -m agents.clinic_agent --port 8765
```

It lists the Groq models first (no prompts or audio are sent) and exits with code 2 if the key is missing or a configured model is not available. Then it loads Silero VAD and the Smart Turn model. It is ready when the log shows:

```
Starting websocket server on 127.0.0.1:8765
PipelineWorker#0: StartFrame#0 reached the end of the pipeline, pipeline is now ready.
```

The first start takes about 10 s. One pipeline serves call after call and resets the conversation and the bookings when a caller connects, so you can run Parakh again, straight away, without restarting it.

## 3. Run the scenario (terminal 2)

```
uv run parakh run scenarios/hinglish/clinic-book-hinglish-01.yaml --agent ws://127.0.0.1:8765 --preset clean
```

The call takes about 70 s. Parakh prints:

```
run dir: runs\6b5d9138
status: completed
latency p50/p95: 4808 / 6769 ms
loose WER: 16.7%
```

## 4. Open the report

```
start runs\<id>\report.html
```

`runs/<id>/` also holds `report.json`, `events.jsonl` (every event with a monotonic timestamp), `caller.wav` and `agent.wav`. Both WAVs start at the same t0, so they line up. `runs/` is gitignored; never commit it.

To re-render the page after a Parakh upgrade: `uv run parakh report runs/<id>`.

## 5. Stop the agent

Press Ctrl+C in terminal 1. Check that nothing still listens on the port:

```
Get-NetTCPConnection -LocalPort 8765 -State Listen
```

## What the report shows

- **Latency** per turn: from the end of the caller's speech to the arrival of the first agent audio frame above -45 dBFS. It uses the frame's arrival time, not the playback clock. p50 and p95 are over the turns that have one.
- **Strict WER** compares words as written. The agent's Whisper writes Hinglish in Devanagari and the references are Roman, so strict WER is about 100 % by construction. It is there to show the script gap.
- **Loose WER** goes through the script-tolerant normaliser (Devanagari to Roman, numbers to digits, spelling variants). It is the headline (D11).
- **Heard** marks each transcript word that loose WER counts as a miss. A run of number words, such as a phone number heard as "9845 012 345", is compared and marked as one number.
- **Agent TTFB** lists the agent's own time-to-first-byte values in arrival order (EC-77). The clinic agent reports them for its Groq STT and LLM requests; its edge-tts service reports none.
- **Agent replied** is each bot-output segment once, recorded when the agent starts it.

## Statuses and exit codes

| Status | Meaning | Exit |
|---|---|---|
| `completed` | Every caller turn was played and answered, or the agent hung up after answering the last one | 0 |
| `agent_hung_up_early` | The agent closed the socket before the first caller turn | 1 |
| `turn_timeout` | No agent audio within `response_timeout_s` (8 s) of a wait starting | 2 |
| `call_timeout` | `call_timeout_s` (180 s) passed since the call started | 2 |
| `agent_disconnected` | The agent closed the socket mid-call | 2 |
| `agent_unreachable` | The WebSocket could not be opened (agent not started, wrong port) | 2 |
| `protocol_error` | The agent sent something that is not a Pipecat protobuf frame | 2 |
| `internal_error` | Parakh hit an unexpected error during the call or scoring; the warning in `report.json` says why | 2 |
| `interrupted` | You pressed Ctrl+C during the run; Parakh writes the report, then stops | 130 (Typer's Ctrl+C code) |

Exit code 2 also covers `timing unreliable`: the caller could not keep its 20 ms pace, so latency cannot be trusted. Every status still writes `report.json` and `report.html`.

Errors before the call starts (an invalid scenario, ffmpeg missing, caller audio that edge-tts cannot synthesise or ffmpeg cannot decode) print a message without a traceback, write no run directory and exit 2. `parakh tts build` and `parakh report` exit 2 the same way on their own errors.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| Agent log: `ERROR ... TTSSettings: the following fields are NOT_GIVEN: model, voice, language` at each pipeline start | Pipecat 1.16 checks that a TTS service fills its settings; the edge-tts service does not | Harmless; the call works |
| Agent log: `RTVIProcessor and RTVIObserver found, skipping default ones` | A Pipecat 1.16 notice | Harmless |
| Status `turn_timeout`; agent log: `GroqSTTService#0 error: Unknown error occurred: Request timed out.` | A Groq STT request timed out, so the agent never heard that turn | Provider hiccup. Run again after a minute |
| Report warning `agent error: ... No audio was received ...` or `... completed with no audio`; agent log: `EdgeTTSService#0 exception ... No audio was received` | edge-tts returned no audio for Devanagari text spoken by the English voice: an aside such as "(किस दिन?)", or in run `106c8e4e` a whole reply | An aside is skipped and the call goes on; its text still shows under "Agent replied". If the whole reply was Devanagari, nothing is spoken and the call ends `turn_timeout`; run again |
| Status `agent_unreachable` | The agent is not running or uses another port | Start the agent; wait for the ready line |
| HTTP 429 from Groq in the agent log | A free-tier rate limit | Stop. Copy the exact line into the run log below. Wait before trying again |
| Any request for payment or a card | Not the free tier | Stop. Do not enter one. Record it in [`api-keys.md`](api-keys.md) (EC-17) |
| `events.jsonl` has `rtvi_repeat` events | Pipecat 1.16 sends each transcript as `user-input` and `user-transcription`, and each spoken segment twice under one `segment_id`; Parakh records the first and logs the repeat | Expected |

## The first real run, turn by turn

Run `6b5d9138` (2026-11-17, Parakh `63add5c`). This is what `report.html` shows for turn 2; `[...]` marks a word the page highlights as a miss:

```
Turn 2  latency 6840 ms, strict WER 100.0%, loose WER 22.2%
Said: Kal subah, agar possible ho toh saadhe das baje.
Reference: Kal subah, agar possible ho toh saadhe das baje.
Heard: कल [सुबा] अगर पॉसिबल हो [तो] साधे दास बजे.
Agent replied: Good, 11:00 works. And your 10-digit phone number, please?
Agent TTFB: 469 ms, 469 ms, 377 ms, 489 ms
```

And turn 3, where Whisper split the phone number into groups:

```
Turn 3  latency 3248 ms, strict WER 140.0%, loose WER 0.0%
Said: Haan, mera number hai nine eight four five, zero one two, three four five.
Reference: haan mera number hai 9845012345
Heard: हाँ, मेरा नमबर है 9845 012 345
Agent replied: आपका फोन नंबर 9845012345 है, सही है?
```

What the runs show:

- Loose WER is low (16.7 %) while the booking is wrong. The caller asked for "saadhe das baje" (10:30). Whisper wrote "साधे दास बजे" and the loose normaliser accepts that spelling, but the LLM never read it as 10:30. The `book_appointment` tool calls in the agent log: run `d75b0c02` booked 10:00 without reading the booking back; `3ace8164` read it back and booked 11:00; `6b5d9138` read back only the phone number, told the caller "phone 9845012345", and booked 11:00 with phone 9876543210. WER alone misses all of this; the deterministic end-state check (M4) will catch it.
- Strict WER of 100 % or more is the script gap, not recognition errors: every Devanagari word misses its Roman reference. Turn 3 is 140 % because the reference has 5 words and Whisper wrote 7.
- The agent's own TTFB values are 0.1 to 0.6 s per request, while end-to-end latency is 2.7 to 6.8 s. Most of the gap is outside the Groq requests: end-of-turn detection (VAD plus Smart Turn), and edge-tts synthesising a whole sentence before the first audio frame, because the test agent does not stream TTS.

## Run log

Agent models for every run: STT `whisper-large-v3-turbo` (language `hi`), LLM `openai/gpt-oss-20b`, TTS `en-IN-NeerjaNeural`, Pipecat 1.16.0. Caller voice `hi-IN-SwaraNeural`, preset `clean`.

| Date | Run | Parakh | Agent models | Status | Latency p50 / p95 | Strict WER | Loose WER | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-11-17 | `d75b0c02` | `adba9eb` | whisper-large-v3-turbo, gpt-oss-20b, en-IN-NeerjaNeural | completed | 2984 / 4908 ms | 206.7 % | 120.0 % | Every transcript and reply recorded twice (Pipecat sends each twice); fixed in `9f2e95e`. 11 STT, 10 LLM requests |
| 2026-11-17 | `3ace8164` | `adba9eb` plus the uncommitted `9f2e95e` fix | same | completed | 4308 / 5406 ms | 100.0 % | 16.7 % | First correct report. HTML marked the split phone number as misses at loose WER 0.0 %; fixed in `7892417`. No agent TTFB; fixed in `63add5c`. 11 STT, 8 LLM requests |
| 2026-11-17 | `494218f0` | `63add5c` | same | turn_timeout | 2585 / 2585 ms (1 turn) | 100.0 % | 73.3 % | Groq STT `Request timed out.` on turn 2; the agent never replied. Not a 429. 4 STT (1 timed out), 4 LLM requests |
| 2026-11-17 | `6b5d9138` | `63add5c` | same | completed | 4808 / 6769 ms | 100.0 % | 16.7 % | Exit 0. Agent TTFB shown. Booked 11:00, not 10:30, with the wrong phone. 11 STT, 9 LLM requests |
| 2026-11-17 | `106c8e4e` | `bc511b0` | same | turn_timeout | n/a (0 turns) | 100.0 % | 73.3 % | First of two back-to-back runs on one agent process, to check the agent's pipeline-per-call restart. The LLM answered the first caller turn in Devanagari only; the English edge-tts voice returned no audio, so nothing was spoken. The agent's two RTVI `error` messages were logged only as `rtvi_unknown`; they are warnings since `b3d4ae0`. 2 STT, 3 LLM requests |
| 2026-11-17 | `6b86baa1` | `bc511b0` | same | completed | 3086 / 5905 ms | 100.0 % | 16.7 % | Second back-to-back run, connected 2.7 s after the first hung up. It passed only because the agent's new pipeline was listening 0.33 s after the hang-up; an offline check that reconnected at once was accepted and cut off, or refused. Fixed in `ac615c3`. 10 STT, 9 LLM requests |
| 2026-11-17 | `e6d15d50` | `839fe79` plus the uncommitted `ac615c3` agent fix | same | completed | 3722 / 6076 ms | 100.0 % | 16.7 % | First of two back-to-back runs on one long-lived agent pipeline. 10 STT, 10 LLM requests |
| 2026-11-17 | `11ae9abd` | same | same | completed | 4011 / 5784 ms | 100.0 % | 16.7 % | Second back-to-back run, 3 s after the first: the same `PipelineWorker#0` served it, its first LLM request had an empty context, and its booking was `bk-001` again (fresh store). 10 STT, 10 LLM requests |

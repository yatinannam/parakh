# M2 run: presets, barge-in and the comparison page

Runs the Hinglish scenarios against the clinic test agent under the five degradation presets, scores barge-in stop latency, and writes a comparison page across presets. Start with [`run-m1.md`](run-m1.md): the agent, the key check and the single-run report are the same.

Only synthetic data leaves the laptop: scenario text and the six babble talker texts go to edge-tts, and the synthesised (and degraded) audio and the agent's transcripts go to Groq (`CLAUDE.md`). Noise is generated on the laptop (white, pink, brown) or built from Parakh's own TTS babble; no noise dataset is downloaded (EC-64).

## The presets

| Preset | What the caller's line adds | Seeded parts |
|---|---|---|
| `clean` | Nothing: the clip resampled to the agent's rate (M1). | none |
| `phone` | 300-3400 Hz band-pass, 8 kHz, G.711 mu-law, back up to the agent's rate. | none |
| `phone_noisy` | `phone` plus babble (six own-TTS talkers) at 10 dB SNR, also between turns. | noise track, turn slices |
| `phone_lossy` | `phone` plus 3 % packet loss (independent 20 ms frames, zero-filled). | loss mask |
| `bad_line` | `phone` plus pink noise at 5 dB SNR, 5 % loss in bursts (mean 3 frames), hard clip at -10 dBFS. | all of the above |

The seed is sha256 of the scenario id and preset, so a rerun degrades the same way (`report.json` records it). SNR is set and measured at the mixing point, on 16 kHz audio, before the telephone stage; the noise level is set once per call from all the call's clips, so the line keeps one noise floor during turns and between them.

To hear a preset on one clip: `uv run parakh degrade <clip.wav> --preset bad_line` writes `<clip>.bad_line.wav` and prints the SNR, lost frames and clipped samples.

## 1. Check the Groq budget

```
uv run parakh budget scenarios/hinglish --preset all
```

The estimate counts 3 STT and 3 LLM requests per caller turn (plus one LLM request for the greeting), times the number of presets. For 2 scenarios and 5 presets: 120 STT and 130 LLM requests, within the free limits (2,000 STT requests a day). Real use was lower (table below), but noise presets can add STT requests when the agent's VAD reacts to the noise.

## 2. Start the agent (terminal 1)

```
uv run --group agent python -m agents.clinic_agent --port 8765
```

Wait for `Starting websocket server on 127.0.0.1:8765`. The agent speaks with `hi-IN-SwaraNeural` (M2), which reads Devanagari, English and Roman Hinglish.

## 3. Run a batch (terminal 2)

```
uv run parakh run scenarios/hinglish/clinic-book-hinglish-01.yaml --agent ws://127.0.0.1:8765 --preset all
uv run parakh run scenarios/hinglish/clinic-bargein-hinglish-01.yaml --agent ws://127.0.0.1:8765 --preset clean --preset phone
```

`--preset` repeats, and `all` means the five presets in comparison order. More than one run (several presets, or a scenario directory) makes a batch: every run goes in `runs/<batch_id>/<run_id>/`, runs are 3 s apart, and `runs/<batch_id>/compare.html` and `compare.json` are rewritten after every run. The command prints `run dir:` as each run starts and `comparison:` at the end, and exits with the highest exit code of its runs. Ctrl+C stops the batch, writes a partial report for the run in progress and the comparison for every run with a report, prints the comparison path, and exits 2.

To build a comparison from run directories you already have: `uv run parakh compare runs/<id> runs/<id> ... --out <dir>`.

## 4. Read the comparison page

Open `runs/<batch_id>/compare.html`. Each scenario has a table with a column per preset (status, strict and loose WER, latency p50 and p95, barge-in stop latency, did-not-yield count, false barge-ins, a link to the run's `report.html`) and two bar charts: loose WER and latency p50 by preset.

In a run's `report.html`:
- Each turn shows its line: `SNR x dB (at mixing), lost a/b frames, clipped c samples`.
- A barge-in turn shows `barge-in after 1200 ms: stopped in X ms (interruption)` (or `(audio)` when the agent's audio stopped first), `did not yield within 2 s`, or `agent finished first` when the reply ended before the barge-in point.
- Metrics add barge-in stop latency (p50, p95, max), the did-not-yield count, and false barge-ins: the agent's `user-started-speaking` (or, without those, its interruptions) outside every caller turn plus 500 ms (EC-25).

## 5. Stop the agent

Ctrl+C in terminal 1.

## What the M2 runs showed

From batches `7eb38dc8` and `cb4a98c6` (booking scenario, all presets) and `e4935d41` (barge-in scenario):

- Babble at 10 dB SNR (`phone_noisy`) stops this agent cold. Its Silero VAD takes the babble bed for speech within about 0.5 s of connecting, interrupts its own greeting, and never decides the caller has finished, so it never replies. All three `phone_noisy` runs ended `turn_timeout` with no caller turn reached and one false barge-in. This is EC-25 at full strength: the noise bed holds the agent's turn detection open.
- `bad_line` completes, but recognition collapses: Groq Whisper returns Devanagari that has little to do with the caller (loose WER 100.0 % and 103.3 %; strict WER above 100 % from insertions). Latency stays near clean (p50 about 2.9 s), so the agent answers fast and wrongly.
- `phone` and `phone_lossy` keep recognition usable: loose WER 20.0 % and 30.0 % against 16.7 % on `clean` (`7eb38dc8`).
- Barge-in works on this agent: interrupted 1200 ms into its reply, it stopped in 362 ms on `clean` and 419 ms on `phone`, both through Pipecat's interruption frame; no false barge-ins.
- Run-to-run variation is large on this agent, so compare across batches, not one run. The same preset completed in one batch and timed out in the next: once because the LLM (`openai/gpt-oss-20b`) answered a turn with empty content and no tool call (`cb4a98c6`, `clean`), once because a reply needed two booking tool calls after a 3 s end-of-turn wait and took about 9 s (`7eb38dc8`, `phone`, under the old 8 s response timeout).

The live runs also found three problems, fixed during M2:
- The agent's old voice, `en-IN-NeerjaNeural`, returns no audio for Devanagari text (edge-tts `NoAudioReceived`), and the LLM often answers a Devanagari transcript in Devanagari, so the agent went silent. It now uses `hi-IN-SwaraNeural` (commit `aae4c49`).
- A call that hangs up while the agent's VAD still hears the noise bed leaves a speech segment that Pipecat closes about 0.4 s later and Groq transcribes about 0.8 s after that; back to back, that transcript became the next call's first caller turn. Batch runs are now 3 s apart (`1600845`).
- Both Hinglish scenarios allow 15 s for a reply (`35afb4a`), so a slow tool-chain reply is measured as latency instead of ending the call.

## Groq requests per run

Counted from the agent log (one Groq Whisper request per transcription, one chat request per LLM generation), batches `cb4a98c6` and `e4935d41`:

| Run | Preset | Status | STT | LLM |
|---|---|---|---|---|
| booking | `clean` | turn_timeout (turn 2) | 4 | 4 |
| booking | `phone` | completed | 11 | 13 |
| booking | `phone_noisy` | turn_timeout (no turn) | 1 | 2 |
| booking | `phone_lossy` | completed | 13 | 15 |
| booking | `bad_line` | completed | 14 | 15 |
| barge-in | `clean` | completed | 5 | 6 |
| barge-in | `phone` | completed | 6 | 8 |

Seven runs used 54 STT and 63 LLM requests, against an estimate of 84 and 91. No 429 or 402 was seen.

## Troubleshooting

- **Every `phone_noisy` run times out with no caller turn.** Expected with this agent (above). It is a finding about the agent's VAD under babble, not a Parakh fault.
- **A 429 mid-batch.** Stop the batch (Ctrl+C), wait for the Groq window to reset, and rerun only the missing presets; `parakh compare` can then join the old and new run directories in one page.
- **The machine runs low on memory.** Claude Code stops background commands when memory is critically low, which stops the agent. Close other heavy programs and restart the agent; runs that never started leave nothing behind. A slow machine also shows in the report as pacing jitter; above 30 ms p99 the run is `timing_unreliable` (exit 2).
- **The agent replies late or not at all on one run and fine on the next.** LLM variation (empty replies, tool chains). Rerun the batch and compare batches.

## Run log

| Date | Batch | Parakh | Scenario | Runs | Notes |
|---|---|---|---|---|---|
| 2026-11-20 | `1e9eaf4f` | `30f6831` | booking | all presets | Agent voice `en-IN-NeerjaNeural`: Devanagari replies silent, 4 of 5 `turn_timeout`; led to `aae4c49`. |
| 2026-11-20 | `7eb38dc8` | `aae4c49` | booking | all presets | `clean` completed (loose WER 16.7 %, p50 4196 ms); `phone_lossy` contaminated by the previous call's babble segment; led to `1600845` and `35afb4a`. |
| 2026-11-21 | `cb4a98c6` | `35afb4a` | booking | all presets | `phone`, `phone_lossy`, `bad_line` completed; `clean` timed out on an empty LLM reply; `phone_noisy` never greeted. |
| 2026-11-21 | `e4935d41` | `35afb4a` | barge-in | `clean`, `phone` | Both completed; stop latency 362 ms and 419 ms, via interruption; loose WER 10.0 % and 3.3 %. |

One barge-in turn, `e4935d41/75ff1539` (`clean`), turn 2: the caller cut in 1200 ms into the agent's reply with "Sorry, ek minute, mujhe kal subah ka slot chahiye, saadhe das baje." The agent's interruption frame arrived 362 ms after the caller started. Whisper heard "सौरी एक मिनिट मुझे कल सुबाह का स्लोट चाहिए साधे दास बजे", and the agent asked "कृपया बताइए, आप किस समय स्लॉट में अपॉइंटमेंट चाहते हैं?"

Agent models for every run: STT `whisper-large-v3-turbo` (language `hi`), LLM `openai/gpt-oss-20b`, TTS `hi-IN-SwaraNeural` (`en-IN-NeerjaNeural` in `1e9eaf4f`), Pipecat 1.16.0.

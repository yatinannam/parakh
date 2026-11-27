# Parakh

[![CI](https://github.com/yatinannam/parakh/actions/workflows/ci.yml/badge.svg)](https://github.com/yatinannam/parakh/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](.python-version)

A test harness for voice agents that serve Indian callers: Hinglish, Kannada-English and Tamil-English code-mixing, phone-quality audio and interruptions.

Voice agents built for Indian callers break in ways that generic tests do not show. Callers mix Hindi, Kannada or Tamil with English in one sentence, they call over narrowband phone lines, and they cut in. Generic scoring also misreports what does work: an agent whose speech-to-text writes a correct Hinglish turn in Devanagari gets a word error rate of 100 % against a Roman-script reference. Parakh plays a scripted synthetic caller to an agent in real time, records both directions, and measures response latency and script-tolerant recognition accuracy on the agent's own transcript. Five telephone-line presets (band-limited 8 kHz G.711 mu-law audio, babble and street-like noise, packet loss, clipping) degrade the caller's audio the way a phone line does, a scheduled barge-in tests whether the agent stops talking when the caller cuts in, and a comparison page shows how the agent degrades from a clean line to a bad one. It runs on a CPU-only laptop and uses free API tiers only.

## Results from the first run

One call to the Pipecat clinic test agent in this repository, scenario `clinic-book-hinglish-01`, preset `clean`. Run `6b5d9138` on 2026-11-17, Parakh `63add5c`.

| Metric | Value |
|---|---|
| Status | `completed`, exit code 0 |
| Caller turns | 4 of 4 played and answered |
| Response latency p50 / p95 | 4808 ms / 6769 ms |
| Strict WER (conversation) | 100.0 % |
| Loose WER (conversation, headline) | 16.7 % |
| Loose CER | 7.6 % |
| Caller send jitter p99 | 19.1 ms (limit 30 ms) |

These numbers come from one run of one scenario on a CPU-only laptop (Intel Core Ultra 5 225U, 16 GB RAM, Windows 11) against free tiers. The agent used Groq `whisper-large-v3-turbo` (language `hi`), Groq `openai/gpt-oss-20b` and edge-tts `en-IN-NeerjaNeural` on Pipecat 1.16.0; the caller voice was edge-tts `hi-IN-SwaraNeural`. They show what Parakh measures. They are not a benchmark of any provider. The agent's own time to first byte per Groq request was 0.1 to 0.6 s, while end-to-end latency per turn was 2.7 to 6.8 s, so most of the latency sat outside the Groq requests.

Strict WER is 100 % because the agent's Whisper writes Hinglish in Devanagari and the references are Roman. Loose WER recovers most of it. Turn 3 in `report.html`:

```
Turn 3  latency 3248 ms, strict WER 140.0%, loose WER 0.0%
Said: Haan, mera number hai nine eight four five, zero one two, three four five.
Reference: haan mera number hai 9845012345
Heard: हाँ, मेरा नमबर है 9845 012 345
Agent replied: आपका फोन नंबर 9845012345 है, सही है?
```

Under strict WER every Devanagari word misses its Roman reference, and Whisper wrote the phone number as three groups, so strict WER is 7 errors over 5 reference words. The normaliser turns the reference into `han mera number hai 9845012345` and the transcript into `han mera namabar hai 9845012345`; `number` and `namabar` match on their consonant skeleton `nmbr`, so loose WER is 0.

WER cannot see whether the call achieved its goal. The caller asked for half past ten ("saadhe das baje"); the agent booked 11:00 and, while reading the right phone number back to the caller, stored a different one (from the agent's tool-call log). The deterministic end-state check planned for M4 is built to catch this. The full run log is in the [M1 runbook](docs/runbooks/run-m1.md#the-first-real-run-turn-by-turn).

## Results under degradation (M2)

The same clinic agent, run through all five presets in batches of back-to-back calls ([M2 runbook](docs/runbooks/run-m2.md)). Loose WER and latency p50 for the booking scenario `clinic-book-hinglish-01`, from batch `cb4a98c6` on 2026-11-21 (Parakh `35afb4a`), with the `clean` baseline from batch `7eb38dc8`, where that preset completed:

| Preset | Status | Loose WER | Latency p50 |
|---|---|---|---|
| `clean` (batch `7eb38dc8`) | `completed` | 16.7 % | 4196 ms |
| `phone` | `completed` | 20.0 % | 2811 ms |
| `phone_noisy` | `turn_timeout`, no caller turn reached | n/a | n/a |
| `phone_lossy` | `completed` | 30.0 % | 3200 ms |
| `bad_line` | `completed` | 100.0 % | 2878 ms |

- **Narrowband audio costs little; loss costs more; a bad line breaks recognition.** `phone` and `phone_lossy` keep loose WER at 20 to 30 %. Under `bad_line` the agent's Groq Whisper returns Devanagari that has little to do with the caller (loose WER 100.0 % and 103.3 % in the two batches), while latency stays near clean: the agent answers fast and wrongly.
- **Babble stops this agent.** Under `phone_noisy` its Silero VAD takes the babble for speech within about 0.5 s of connecting, interrupts its own greeting and never decides the caller has finished. All three `phone_noisy` runs ended `turn_timeout` with one false barge-in each. Parakh reports this as a finding about the agent's turn detection, not as a harness fault.
- **Barge-in works.** In `clinic-bargein-hinglish-01` (batch `e4935d41`) the caller cut in 1200 ms into the agent's reply. The agent stopped in 362 ms on `clean` and 419 ms on `phone`, both through Pipecat's interruption frame, with no false barge-ins; loose WER was 10.0 % and 3.3 %.
- **Variation between runs is large.** The same preset completed in one batch and timed out in the next, once on an empty LLM reply and once on a reply that needed two tool calls and took about 9 s. Compare batches, not single runs. Seven runs used 54 STT and 63 LLM requests, with no rate-limit error.

The two WER figures differ because the final normaliser has rules learned from these transcripts, and the slow-caller scenario had its references fixed after the run. The 6.3 % figure uses both, so it is optimistic for these exact transcripts; the 10.9 % figure is what the normaliser of the time scored.

These numbers come from one agent on one laptop against free tiers; they show what Parakh measures and are not a benchmark of any provider.

## Results from the Hinglish pack (M3a)

All 14 scenarios of [`scenarios/hinglish/`](scenarios/hinglish/) ran against the same clinic agent under `clean`, with the advisory judge on, on 2026-11-23. The [M3a runbook](docs/runbooks/run-m3a.md) has the per-run table, the calibration and the run log.

| Measure | Value |
|---|---|
| Scenarios completed under `clean` | 14 of 14 |
| Mean loose WER | 6.3 % rescored with the final normaliser (range 0 to 21 %); 10.9 % as run |
| Strict WER | about 100 %, except the Devanagari scenario (9.5 %) and the English-heavy one (42.9 %) |
| Judge task progress (1 to 5) | 1 or 2 on 12 of 14 calls; 5 only on the Devanagari scenario |
| Under `phone` (4 scenarios) | Devanagari 9.5 %, Hindi numbers 7.4 %, unknown doctor 6.9 %, English-heavy 80.0 % |
| Agent LLM use | 811 tokens per request (88,430 tokens over 109 requests) |
| Judge use | 20 judged runs, 21,319 tokens, 1 attempt each, no fallback |
| HTTP 429 or 402 | none |

- **Recognition is not the weak part; the agent's handling is.** Loose WER is low, yet the agent rarely finishes a booking correctly. Whisper writes `साढ़े` as `साधे`, and the agent's LLM books "साधे 11" as 11:00 instead of 11:30. Whisper also splits, drops or repeats phone digits, and the agent then asks again until the call ends. It books without reading the details back in 12 of 14 calls. WER alone cannot show this; the judge's flags `wrong_details`, `repeated_question` and `no_confirmation` do.
- **The caller can talk over the agent.** The agent's TTS splits a reply at `डॉ.` and the next sentence takes over 800 ms to synthesise, so the 800 ms end-of-turn rule fires mid-reply (EC-88).
- **An English-heavy caller breaks on a phone line.** With Whisper language `hi`, band-limited English comes back as Devanagari phonetics, and loose WER under `phone` is 80.0 % (EC-91).
- **The agent's reset works.** A `phone_lossy` call right after a `phone_noisy` call had a clean first turn and no false barge-in (EC-84).
- **The judge agrees with a hand check.** On 10 calls it was within 1 point of the controller's own scores on every item, and never lowered language match for a Hinglish reply. Calibration is pending Yatin's confirmation: the table has not been checked by him yet.

These numbers come from one agent on one laptop against free tiers. They show what Parakh measures and are not a benchmark of any provider.

## Results from Kannada-English and Tamil-English (M3b)

The packs [`scenarios/kannada_en/`](scenarios/kannada_en/) and [`scenarios/tamil_en/`](scenarios/tamil_en/) have six scenarios each. They ran under `clean` on 2026-11-25 against the clinic agent with the matching language profile ([M3b runbook](docs/runbooks/run-m3b.md)).

| Measure | Kannada-English | Tamil-English |
|---|---|---|
| Scenarios completed | 6 of 6, one after a re-run | 6 of 6, one after a re-run |
| Mean loose WER, rescored with the final normaliser | 51.7 % (58.0 % as run) | 43.8 % (49.8 % as run) |
| English-heavy caller | 13.8 % | 22.2 % |
| Turns left out because Whisper wrote them in Urdu or Arabic script | 2 of 24 | 7 of 24 |
| Agent LLM use | 44 requests, 36,707 tokens | 47 requests, 43,119 tokens |

- **Recognition is the bottleneck.** The Hinglish pack scored 6.3 %. Word alignment shows that most Kannada and Tamil errors are words Whisper misheard ("Allah Allah, hat again Allah" for "illa illa, hattu gante alla"), not spellings the normaliser missed.
- **Script drift silenced the agent.** Whisper wrote some goodbyes in Urdu script, the agent's LLM replied in that script, and the Kannada and Tamil voices cannot read it, so the agent went silent (EC-92). A prompt rule now keeps replies in the scripts the voice reads; both affected scenarios then completed.
- **The Tamil figure covers fewer turns.** Turns in Urdu or Arabic script are left out of loose WER and listed in the report, so compare the packs together with that count.
- **The judge's rubric needs a Kannada and Tamil sentence.** In a spot check of 8 calls it marked down a Tamil reply in the caller's own language, and scored English replies to callers who used English words below its own rubric. A `judge-v2` rubric is flagged for review.

## Real recordings (M3b)

Synthetic caller audio is cleaner than real speech, so Parakh can also play your own voice reading the scripted lines ([`record-real.md`](docs/runbooks/record-real.md)). Save one file per turn as `data/real/<scenario_id>/turn-01.m4a` (any format ffmpeg reads), check the clips, start the agent with local speech recognition, and run with `--real`:

```
uv run parakh recordings status scenarios/hinglish/clinic-book-hinglish-01.yaml
uv run --group agent python -m agents.clinic_agent --profile hi --stt local --port 8765
uv run parakh run scenarios/hinglish/clinic-book-hinglish-01.yaml --agent ws://127.0.0.1:8765 --real
```

The audio never leaves the machine:
- `--real` accepts only an agent URL on `127.0.0.1`, `localhost` or `::1`. It refuses redirects and checks that the connected peer is a loopback address.
- Parakh sends silence until the agent reports a local speech-to-text model (`stt_model` starting `local:`). An agent that reports another model, or none within 5 s, ends the run `real_data_refused` (exit 2) before any recorded frame is sent.
- The judge is skipped, and `data/real/` and `runs/` are gitignored.
- The agent's own LLM (Groq, for the clinic agent) still receives the text transcript of what you said. Record only the scripted line, in a room with no other voices.
- Never run `--real` through a port forward, which makes a remote agent look local.

The author recorded 4 Hinglish scenarios (16 clips) on 2026-11-26. All 8 runs, under `clean` and `phone`, completed through the local-STT agent, with no Groq speech-to-text request in the agent logs. Through the same agent, real speech scored 61.3 % mean loose WER against 33.8 % for the synthetic caller. The local `small` model is itself far weaker than Groq's Whisper, so these figures measure it as much as the speech.

## Indic Parler-TTS (pending)

edge-tts is the only caller voice engine so far, and its audio terms are unclear, so the public scenario pack ships text, not audio. [Indic Parler-TTS](https://huggingface.co/ai4bharat/indic-parler-tts) (Apache-2.0) could supply publishable audio and an offline fallback. [`tools/parler_bench/`](tools/parler_bench/README.md) benchmarks it on the CPU in its own uv project, so torch never enters Parakh's lock or CI. Parler is adopted only if it reaches a real-time factor of 10 or less, a peak memory of 6 GB or less, and a loose WER of 25 % or less in each of Hindi, Kannada and Tamil when Groq Whisper transcribes its clips (D21). The model is gated with automatic approval, so it needs a free Hugging Face read token (`HF_TOKEN`, see the [API keys runbook](docs/runbooks/api-keys.md)). The benchmark has not run yet: it needs about 7 GB of free memory.

## Quick start

Prerequisites:

- Windows 10 or 11, or Linux. CI runs on `windows-latest` and `ubuntu-latest`.
- Python 3.11 (pinned in `.python-version`) and [uv](https://docs.astral.sh/uv/) 0.11 or later.
- ffmpeg on `PATH`. Parakh refuses to run without it.
- A free [Groq](https://console.groq.com/) API key for the test agent and the judge. A free Gemini key is optional: it is only the judge's fallback. No credit or debit card is needed anywhere in this project.

Install, including the test agent's dependency group:

```
git clone https://github.com/yatinannam/parakh.git
cd parakh
uv sync --all-groups
```

Put the key in `.env`, which is gitignored. Copy `.env.example` to `.env` (`cp .env.example .env`, or `Copy-Item .env.example .env` in PowerShell), set `GROQ_API_KEY`, then check it. The check only lists models and never prints the key ([API keys runbook](docs/runbooks/api-keys.md)).

```
uv run python -m tools.check_keys
```

Start the clinic test agent in one terminal. It checks the key and its configured Groq models, loads Silero VAD, and is ready when the log shows `Starting websocket server on 127.0.0.1:8765` and `pipeline is now ready` (about 10 s on the first start).

```
uv run --group agent python -m agents.clinic_agent --port 8765
```

Run the Hinglish scenario from a second terminal. The call takes about 70 s.

```
uv run parakh run scenarios/hinglish/clinic-book-hinglish-01.yaml --agent ws://127.0.0.1:8765 --preset clean
```

```
run dir: runs\6b5d9138
status: completed
latency p50/p95: 4808 / 6769 ms
loose WER: 16.7%
```

Open the report: `start runs\<id>\report.html` on Windows, `xdg-open runs/<id>/report.html` on Linux. The run directory also holds `report.json`, `events.jsonl` and the two audio tracks `caller.wav` and `agent.wav`, which start at the same instant. `runs/` is gitignored. The [M1 runbook](docs/runbooks/run-m1.md) covers the Groq budget, troubleshooting and how to read the report.

To run the scenario under every preset and compare them, repeat `--preset` or pass `all`:

```
uv run parakh run scenarios/hinglish/clinic-book-hinglish-01.yaml --agent ws://127.0.0.1:8765 --preset all
```

That writes one run directory per preset under `runs/<batch_id>/` and `runs/<batch_id>/compare.html`. The [M2 runbook](docs/runbooks/run-m2.md) covers batches, the comparison page and the run log.

For the Kannada-English or Tamil-English pack, start the agent with the matching profile, which sets its speech-to-text language hint and its voice. One agent process serves one language; a run against the wrong profile proceeds with the warning `agent language hi does not match scenario language kn-en`.

```
uv run --group agent python -m agents.clinic_agent --profile kn --port 8765
uv run parakh run scenarios/kannada_en --agent ws://127.0.0.1:8765 --preset clean
```

## Degradation presets and barge-in

Each preset adds one factor to the one before it. The seed is the sha256 of the scenario id and the preset, so a rerun degrades the same way.

| Preset | What the caller's line adds |
|---|---|
| `clean` | Nothing: the clip resampled to the agent's rate. |
| `phone` | 300-3400 Hz band-pass, 8 kHz, G.711 mu-law, back up to the agent's rate. |
| `phone_noisy` | `phone` plus babble (six own-TTS talkers of invented text) at 10 dB SNR. |
| `phone_lossy` | `phone` plus 3 % packet loss (independent 20 ms frames, zero-filled). |
| `bad_line` | `phone` plus pink noise at 5 dB SNR, 5 % loss in bursts (mean 3 frames) and a hard clip at -10 dBFS. |

The stages run in this order: peak-normalise to -3 dBFS, add noise, hard clip, telephone band-pass, 8 kHz resample and mu-law, packet loss, resample to the agent's rate. The mu-law codec is written from the G.711 algorithm and matches `ffmpeg -c:a pcm_mulaw` byte for byte on every input. SNR is speech-active RMS against noise RMS, set and measured on 16 kHz audio at the mixing point; the noise level is set once per call, so the line keeps one noise floor during turns and between them (a noise bed streams in the gaps). Every turn's measured SNR, lost frames and clipped samples appear in `report.html`. Noise is synthetic white, pink and brown noise and Parakh's own babble; no noise dataset is downloaded.

To hear a preset on one clip: `uv run parakh degrade clip.wav --preset bad_line` writes `clip.bad_line.wav` and prints the SNR, lost frames and clipped samples.

**Barge-in.** A turn with `barge_in: { after_agent_ms: N }` starts N ms into the agent's reply, on the playback clock. Parakh then measures:

- **Stop latency**: from the caller's first frame to the first of the agent's interruption frame and the end of its last audio before 800 ms of quiet (or 500 ms of quiet that holds the caller's speech end, if that comes first); shorter pauses are part of the reply. Above 2000 ms the turn is `did_not_yield`; if the reply ended before the barge-in point, the turn is `agent_finished_first`.
- **Response latency of that turn**, counted from the moment the agent yielded, so its own tail of speech is not counted as slowness.
- **False barge-ins**: interruptions or `user-started-speaking` messages from the agent while the caller was silent.

**Comparison page.** `compare.html` has one table per scenario with a column per preset (status, strict and loose WER, latency p50 and p95, stop latency, did-not-yield count, false barge-ins and a link to the run's report) and bar charts of loose WER and latency p50 by preset. It is rewritten after every run of a batch, so a stopped batch still leaves a page. `compare.json` holds the same numbers.

## Scenario packs

[`scenarios/hinglish/`](scenarios/hinglish/) holds 14 synthetic clinic-booking scenarios that share one frozen clock (`2026-11-19T10:00:00+05:30`, so "kal" is 2026-11-20). Each has a `goal`, which the judge reads. They cover the M1 baseline and the M2 barge-in scenario (turns frozen), a second doctor, out-of-hours and slot queries, a spoken correction, "double" and "triple" digits, phone numbers in Hindi number words, an English-heavy caller, a Devanagari script, a barge-in that corrects the time, fast (+25 %) and slow (-20 %) callers with fillers, and a request for a doctor the clinic does not have. The runbook lists each scenario with its voice and purpose.

```
uv run parakh run scenarios/hinglish --agent ws://127.0.0.1:8765 --preset clean
```

A full pack batch takes about 20 to 25 minutes and an estimated 155,700 agent LLM tokens per preset (measured about 88,000 over 15 clean runs), against the agent model's 200,000 a day. On the development laptop a command that long can be killed when memory runs low, so run the pack in batches of 4 or 5 scenarios and join them with `parakh compare <run dir>... --out runs/m3a-pack`, or resume a stopped batch:

```
uv run parakh run scenarios/hinglish --agent ws://127.0.0.1:8765 --preset clean --resume runs/<batch_id>
```

`--resume` skips every (scenario, preset) pair that already has a `completed` report in that batch and runs the rest. The comparison page shows the newest report per pair. Use it after a run ends `rate_limited` (the agent reported a Groq 429), after Ctrl+C, or after the laptop slept mid-call.

[`scenarios/kannada_en/`](scenarios/kannada_en/) and [`scenarios/tamil_en/`](scenarios/tamil_en/) hold six scenarios each (M3b), with the same clinic and clock: a booking, a second doctor for a son, a barge-in that corrects the time, the phone number in Kannada or Tamil number words, the caller's lines in Kannada or Tamil script, and an English-heavy caller. Run each against an agent with the matching `--profile`. Phone numbers are distinct across all 26 scenarios.

## LLM judge (advisory)

Parakh asks an LLM to rate each call, because WER and latency cannot show whether the agent did its job. The judge is advisory: it never changes a run's status or the exit code.

- **Free tiers, synthetic data only.** The judge calls Groq `openai/gpt-oss-120b` first, which has its own free per-model limits apart from the agent's model. Gemini `gemini-flash-lite-latest` is the fallback, used only if `GEMINI_API_KEY` is set. Both are configured in `src/parakh/judge/judge.yaml`. The payload holds only the scenario goal, the scripted lines, the agent's transcript of them, the agent's replies, barge-in results and the run status. It never holds paths, URLs, agent info or warnings.
- **Data note.** The judge sends the scenario goal, the scripted lines, the agent's transcript of them and the agent's replies to Groq (or Gemini). With an agent other than the synthetic clinic agent, check that its replies carry no real data, or pass `--no-judge`.
- **Scores and flags.** Five scores from 1 to 5: understanding, language match, interruption handling (null without a barge-in), task progress and politeness. Also a short rationale and flags such as `wrong_details`, `no_confirmation`, `repeated_question` and `ignored_interruption`. Hinglish in either script counts as a correct register.
- **Robust to bad replies.** The judge runs in JSON object mode at temperature 0. An invalid reply is retried (4 attempts per provider), then the next provider is tried, then the result is `judge_error` with a reason that names the failing field. A transcript that contains instructions is treated as data and flagged.
- **Statuses.** `ok`, `skipped` (nothing to judge, or no key), `judge_error` and `rate_limited`.
- **Cached and reproducible.** Verdicts are cached in `.cache/judge/` by provider, model, prompt version and payload, and the report records the model id, the model version and the prompt version (`judge-v1`).
- **Never on real recordings.** A `--real` run's judge is `skipped` before any request.
- **Quota guard.** A token bucket and a daily counter per model keep Parakh inside the free limits, for requests and, on Groq, for tokens (8,000 a minute and 200,000 a day for the judge model). On HTTP 429 it honours `Retry-After` (and gives up at once if that is over 60 s); on HTTP 402 it disables the provider and never retries.

`parakh run` judges by default; pass `--no-judge` to skip it. `parakh judge <run dir>...` rates finished runs, or re-rates them after a rubric change (`--force` ignores the cache). It exits 2 when any report ends `judge_error` or `rate_limited`.

## CLI reference

| Command | What it does | Options |
|---|---|---|
| `parakh run SCENARIO --agent URL` | Synthesises the caller audio (cached), runs real-time calls for each scenario and preset, scores them, and writes `report.json` and `report.html` to a new run directory per run. More than one run (several presets, or a scenario directory) is a batch: runs go in `runs/<batch_id>/` and `compare.html` and `compare.json` are rewritten after every run. | `--agent` ws:// or wss:// URL (required). `--preset` (repeatable, or `all`; default `clean`): `clean`, `phone`, `phone_noisy`, `phone_lossy`, `bad_line`. `--runs-dir` (default `runs`). `--agent-rate` sample rate sent to the agent (default 16000). `--cache-dir` (default `.cache/tts`). `--judge/--no-judge` (default on) rates each run with the advisory judge. `--resume BATCH_DIR` skips the pairs that already completed in that batch. `--real` plays your recordings from `data/real/` instead of synthetic audio, only to a local agent with local speech-to-text, and skips the judge. |
| `parakh recordings status PATH...` | For scenario files or directories, lists each turn's recording as found or missing, and the files that match no turn. Decodes each recording on this machine: `ERROR` for a silent or undecodable file, `CHECK` for a clip far too short or too long for its line. Exits 2 when a turn is missing, silent or undecodable; `CHECK` is advice only. | `--real-dir` (default `data/real`). |
| `parakh heavy run OWNER -- CMD...` | Runs a command while holding the heavy-model lock, so Parler and Whisper never load together. Exits with the command's code, or 2 when the lock is held (the message names the holder and its PID). | |
| `parakh degrade CLIP --preset P` | Degrades one 16-bit mono WAV with a preset and writes `<clip>.<preset>.wav`; prints the SNR, lost frames and clipped samples. | `--preset` (required). `--out` output path. `--rate` output sample rate (default 16000). `--seed` (default 0). `--cache-dir` (default `.cache/tts`). |
| `parakh compare RUN_DIR...` | Builds `compare.html` and `compare.json` from existing run directories, for example to join runs from several batches. | `--out` directory for the page (default: the common parent of the run directories). |
| `parakh judge RUN_DIR...` | Rates finished runs with the advisory judge, then rewrites `report.json` and `report.html`. Exits 2 when any report ends `judge_error` or `rate_limited`. | `--force` asks again even when a verdict is cached. |
| `parakh rescore RUN_DIR...` | Recomputes WER from each run's stored transcripts and the scenarios' current references, then rewrites `report.json` and `report.html`. Prints `<run_dir>: loose WER <old> -> <new>`. Exits 2 on an unreadable report or a scenario id not found. | `--scenarios DIR` (default `scenarios/`, searched recursively by `id`). |
| `parakh tts build PATH...` | Synthesises and caches the caller audio for scenario files or directories, and prints how many clips were built or cached. | `--cache-dir` (default `.cache/tts`). |
| `parakh report RUN_DIR` | Re-renders `report.html` from the run's `report.json`. | |
| `parakh budget PATH...` | Estimates Groq STT and LLM requests and audio seconds for scenario files or directories, against the free-tier limits. Exits 2 if over. | `--preset` (repeatable, or `all`), because the estimate scales with the number of runs. |
| `parakh version` | Prints the Parakh version. | |

The estimate counts 3 STT and 3 LLM requests per caller turn, plus one LLM request for the agent's greeting, times the number of presets. It also gives agent LLM tokens (900 per request, measured at 811 in M3a and 874 in M3b), one judge call per run, and judge tokens (1,100 per call). That is a guide, not a bound: the clinic agent's STT runs once per VAD segment, tool calls add LLM turns, and noise presets can add STT requests when the agent's VAD reacts to noise. The seven M2 runs used 54 STT and 63 LLM requests against an estimate of 84 and 91.

Exit codes of `parakh run`; a batch exits with the highest code of its runs. Every status still writes `report.json` and `report.html`. Barge-in results do not change the exit code until the M4 thresholds.

| Exit | Status |
|---|---|
| 0 | `completed`: every caller turn was played and answered, or the agent hung up after answering the last one. |
| 1 | `agent_hung_up_early`: the agent closed the socket before the first caller turn. |
| 2 | `turn_timeout`, `call_timeout`, `agent_disconnected`, `agent_unreachable`, `protocol_error`, `internal_error`, `rate_limited` (the agent reported a 429; resumable), `interrupted` (Ctrl+C: the partial report and the comparison are written first), `real_data_refused` (a `--real` run whose agent did not prove local speech-to-text; no recorded audio was sent), or any status when the caller could not keep its 20 ms pace (`timing_unreliable`). |

Errors found before a call starts (unknown preset, a URL that is not ws:// or wss://, an invalid scenario, ffmpeg missing, caller audio that edge-tts cannot synthesise or ffmpeg cannot decode) print a message without a traceback, write no run directory and exit 2. `tts build` exits 2 the same way for an invalid scenario, a synthesis or decode failure and a missing ffmpeg, and `report` for a `report.json` that is missing, not UTF-8 or not a valid report.

## How the measurement works

**Real-time pacer.** For the whole call the caller sends one 20 ms frame every 20 ms: caller speech during a turn, silence between turns, as on a real line. The k-th frame targets `t0 + k * 20 ms` on `time.perf_counter_ns()`; a late tick sends at once and never shifts the schedule, because asyncio timers on Windows are about 15.6 ms coarse and relative sleeps drift. The lateness of every tick is recorded, and a run whose p99 lateness exceeds 30 ms is marked `timing_unreliable` and exits 2. The recorder writes `events.jsonl` from its own thread, so a stalled disk write cannot delay a frame.

**Virtual playback clock.** Agents often send speech faster than real time. Parakh models a phone speaker: each agent frame starts playing at the later of its arrival and the end of the previous frame, so `playback_end = max(playback_end, arrival) + duration`. "The agent is speaking" means the clock has not yet reached the playback end of the last frame above -45 dBFS. A silent frame that arrives behind queued audio is not placed, so streamed silence never pushes later speech back, and an agent that streams silence between replies is not speaking. When the agent sends an interruption frame, the queue is flushed and the agent track is cut there. The clock also records each reply's onset: the playback start of its current run of loud audio, where a gap above 200 ms starts a new run.

**Turn-taking.** With `agent_speaks_first`, the caller waits for the agent's greeting. The next caller turn starts once the agent is quiet on the playback clock and either it has sent RTVI `bot-stopped-speaking` or 800 ms have passed since its last audio above -45 dBFS ended. A caller-first scenario starts after 1000 ms with no agent audio. No agent audio within `response_timeout_s` (default 8 s) of a wait starting ends the call as `turn_timeout`; `call_timeout_s` (default 180 s) bounds the whole call. Agent audio during a caller turn does not interrupt it. A turn with `barge_in` is the exception: it starts once the agent is speaking and the playback clock has reached the reply onset plus `after_agent_ms`.

**Latency.** Per turn: the arrival time of the first agent audio frame above -45 dBFS after the caller's speech end and before the next caller turn, minus the caller's speech end. Speech end is the send time of the frame that holds the clip's `speech_end_ms` (measured on the clean clip at -45 dBFS), not the end of trailing silence. The report gives p50, p90, p95 and max, and lists the agent's own TTFB metrics per turn when it sends them. For a barge-in turn, latency counts from the moment the agent yielded (see above), and a turn where the agent never yielded has none.

**WER on the agent's own transcript.** Parakh scores what the agent heard: its final transcriptions of the caller (RTVI messages or Pipecat transcription frames), grouped into turns by time window. If the agent exposes no transcript, WER is null with a reason; Parakh never substitutes its own speech-to-text. If it exposes one but heard nothing in a turn the caller played, that turn's WER is 100 % (EC-46). Pipecat 1.16 sends each transcript twice (`user-input` and the deprecated `user-transcription`) and repeats bot output segments; Parakh records each once and logs the repeat as an `rtvi_repeat` event. The headline is conversation-level loose WER over all turns, so a VAD that splits or merges turns does not distort it; per-turn WER is a diagnostic.

- **Strict WER**: jiwer on NFC text, lowercased, punctuation stripped.
- **Loose WER**: Parakh's own Levenshtein over normalised tokens. Two tokens match when their loose keys are equal, or, for words, when their consonant skeletons are equal (three or more consonants) and their lengths differ by at most 2. Numbers must match exactly. **Loose CER** is the same over the characters of the normalised text.

**Script-tolerant normaliser**, applied to reference and hypothesis alike, in this order:

1. Unicode NFC; remove zero-width joiners and non-joiners; flag Perso-Arabic script as `script_unsupported`.
2. Devanagari to Roman with `indic-transliteration` (ITRANS), word by word. Candra o (`ॉ`, `ऑ`) is read as `ो`, `ओ` first, so `डॉक्टर` gives `doktar`. Anusvara and chandrabindu become `n`, or `m` before p, b and m, so `मैं` gives `main`. The inherent final schwa is dropped when ITRANS ends a word in a short `a` after a consonant, so `कल` gives `kal`.
3. Lowercase, keep only `a-z` and `0-9`, split into tokens.
4. Number words to digits, looked up by loose key: English words, "X hundred [and] Y", "double" and "triple", Hindi words for 0 to 100 (except 13 and 60, which collide with `tera` and `साथ`), "sau", Devanagari numerals, and "oh" as 0 between digits; then adjacent digit tokens are joined, so a phone number in groups becomes one token. Fillers (`um`, `uh`, `hm`, `अम`, `उम`, `हम्म`) are dropped on both sides.
5. Loose phonetic key for words: `c` (not before h) to `k`, `ph` to `f`, `w` to `v`, `q` to `k`, `z` to `j`, final `ov` to `o`, `ee` to `i`, `oo` to `u`, double letters to single (`aa` to `a`), `y` dropped only between two different vowels, a final `h` after a vowel dropped only in words of 4 or more letters; then a variant table grown from observed Whisper spellings (`nahin` and `nai` to `nahi`, `men` and `me` to `mein`, `yeh` to `ye`). The table never merges two common words: `main` and `mein`, `कह` and `का`, `बताया` and `बता` stay distinct. Urdu-script turns are listed and left out of loose WER.

Two worked examples, both checked against the current code:

| Input | Steps | Tokens |
|---|---|---|
| `हाँ` (Whisper) | ITRANS `hA.N`; chandrabindu to `n`: `hAn`; lowercase | `han` |
| `haan` (reference) | double `aa` to `a` | `han` |
| `nine eight four five, zero one two, three four five` (reference) | number words to digits, then joined | `9845012345` |
| `9845 012 345` (Whisper) | adjacent digit groups joined | `9845012345` |

The normaliser has a golden file of 269 pairs: 200 that must match (Hinglish, loanwords, variants, numbers), 55 that must not, and 14 known gaps kept as strict expected failures ([`tests/golden/normalizer_pairs.yaml`](tests/golden/normalizer_pairs.yaml)). Hypothesis property tests check that normalising twice gives the same result, that tokens are ASCII, and that matching is reflexive and symmetric. Spec [section 6.7](docs/superpowers/specs/2026-11-15-parakh-design.md#67-scoring) gives the full rules.

**Kannada-English and Tamil-English (M3b).** The normaliser takes the scenario language. The script of each word picks its romaniser: Devanagari and Kannada go through ITRANS, and Tamil through Parakh's own table, because `indic-transliteration` writes எனக்கு as `èனghghu`. Tamil script does not mark voicing, so the Tamil table voices a stop by context (ம்ப `mb`, a single க between vowels `g`), and `ta-en` collapses `b`/`p`, `d`/`t` and `g`/`k` in the loose key while keeping the dental and retroflex stops and ழ and ல apart. Each language has its own number words (Kannada and Tamil 0 to 100 in both scripts, plus English) and its own variant table, and a word is never a number outside its language: `ondu` is 1 only in Kannada-English. Kannada and Tamil numerals become digits. The Hinglish output is frozen token for token. Two more golden files hold 163 Kannada and 181 Tamil entries, including 13 and 24 known gaps.

## Architecture

```mermaid
flowchart LR
  scenario["Scenario YAML<br/>scenarios/"]
  tts["Caller TTS + cache<br/>edge-tts, ffmpeg, .cache/tts"]
  degrader["Degrader<br/>five presets, seeded"]
  subgraph caller ["Call driver: src/parakh/caller"]
    driver["20 ms pacer<br/>virtual playback clock<br/>turn machine"]
    recorder["Recorder<br/>events.jsonl, caller.wav, agent.wav"]
  end
  agent["Agent under test<br/>agents/clinic_agent"]
  latency["Latency scorer<br/>and barge-in stop latency"]
  wer["WER scorer<br/>strict and loose"]
  normaliser["Script-tolerant normaliser"]
  report["report.json<br/>report.html"]
  compare["compare.html<br/>across presets"]
  hms["Mock HMS, M4"]
  task["Task success, M4"]
  judge["LLM judge, advisory"]
  quota["Quota guard<br/>bucket, daily counter, 429 backoff"]

  scenario --> tts
  tts --> degrader
  degrader --> driver
  driver -->|"caller audio: Pipecat protobuf over WebSocket"| agent
  agent -->|"agent audio, RTVI transcripts and metrics"| driver
  driver --> recorder
  recorder --> latency
  recorder --> wer
  wer --> normaliser
  latency --> report
  wer --> report
  report --> compare
  agent -.->|"tool calls"| hms
  hms -.-> task
  task -.-> report
  recorder --> judge
  judge --> report
  quota --> judge
```

Dashed parts are planned (M4). The agent runs as a separate process. Scoring runs after the call ends, so local models never compete with the live call for CPU. Because the transport is Pipecat's standard protobuf frame protocol, Parakh tests an unmodified Pipecat agent. The [knowledge graph](docs/kg/README.md) maps every component, decision, risk and document; the [design spec](docs/superpowers/specs/2026-11-15-parakh-design.md) has the details.

## Scenario format

A scenario is a YAML file validated by pydantic. This is the booking scenario, [`scenarios/hinglish/clinic-book-hinglish-01.yaml`](scenarios/hinglish/clinic-book-hinglish-01.yaml):

```yaml
schema_version: 1
id: clinic-book-hinglish-01
title: Book a follow-up with Dr. Rao (Hinglish)
language: hi-en
domain: clinic
clock: "2026-11-19T10:00:00+05:30"
agent_speaks_first: true
caller:
  voice: hi-IN-SwaraNeural
  rate: "+0%"
turns:
  - say: "Hello, mujhe Dr. Rao ke saath follow-up appointment chahiye."
    ref: "hello mujhe doctor rao ke saath follow up appointment chahiye"
  - say: "Kal subah, agar possible ho toh saadhe das baje."
  - say: "Haan, mera number hai nine eight four five, zero one two, three four five."
    ref: "haan mera number hai 9845012345"
  - say: "Haan, sahi hai. Thank you, bye."
limits: { max_turns: 12, response_timeout_s: 15, call_timeout_s: 180 }
```

| Field | Meaning |
|---|---|
| `say` | Text the caller's TTS speaks, in the script the voice reads best. |
| `ref` | Reference transcript for WER. Defaults to `say`. |
| `clock` | Frozen "now" for the scenario, with a timezone offset. In M1 the clinic agent reads the same value from its own `config.yaml`. |
| `agent_speaks_first` | Wait for the agent's greeting (default `true`), or speak after 1 s of silence. |
| `caller` | edge-tts voice, rate and pitch. |
| `limits` | `max_turns` (at least 1), `response_timeout_s` (default 8; the Hinglish scenarios use 15, because a reply with two tool calls can take about 9 s) and `call_timeout_s` (finite, above 0). |
| `barge_in` | On a turn: `{ after_agent_ms: N }` (N of 0 or more) starts the turn N ms into the agent's reply. |

[`scenarios/hinglish/clinic-bargein-hinglish-01.yaml`](scenarios/hinglish/clinic-bargein-hinglish-01.yaml) uses `barge_in: { after_agent_ms: 1200 }` on its second turn. The schema also accepts `hms_seed` and `expect` (M4). All scenario content is synthetic: invented names, numbers and clinics.

## Status

| Milestone | Scope | State |
|---|---|---|
| M0 | Repository hygiene, CI, tooling, Task 1 evaluation of Calibrate | Complete (2026-11-16) |
| M1 | One Hinglish scenario, clean audio, Pipecat clinic test agent, latency and strict and loose WER, JSON and HTML report | Complete (2026-11-17) |
| M2 | Degradation presets (telephone band, 8 kHz, G.711 mu-law, noise, packet loss, clipping), barge-in with stop latency, comparison page, batch runs | Complete (2026-11-21) |
| M3a | Hinglish pack of 14 scenarios, normaliser hardened on 269 golden pairs, quota guard and resume, advisory LLM judge | Complete (2026-11-23) |
| M3b | Kannada-English and Tamil-English scenarios, a small real-recording set, the Indic Parler-TTS benchmark, the heavy-model lock | In progress: all done except the Parler benchmark, which needs about 7 GB of free memory |
| M4 | Mock hospital management system and end-state adapter for deterministic task success; end-to-end CI workflow | Planned |
| M5 | Public release: scenario pack, comparison run across presets and agent setups | Planned |

## Repository layout

```
src/parakh/
  scenario/            Scenario model and YAML loader
  tts/                 edge-tts caller audio, ffmpeg decoding, content-addressed cache, real recordings
  degrade/             Mu-law codec, band-pass, noise, packet loss, seeds, the five presets
  caller/              Call driver: pacer, playback clock, turn machine, recorder, caller line (degraded turns and noise bed), the real-data gate
  transport/           Pipecat protobuf codec, RTVI parsing, WebSocket connection, loopback checks
  score/               Latency, barge-in stop latency, script-tolerant normaliser (Devanagari, Kannada and Tamil romanisers, per-language numbers), strict and loose WER
  report/              report.json model, report.html, the comparison page across presets, rescoring
  judge/               Advisory LLM judge: prompt, strict scores, providers (judge.yaml), cache, fallback
  budget/              Groq usage estimate, the remote_call() guard, token bucket, daily counter and 429 backoff
  audio.py             WAV, dBFS, resampling, framing, silence trim
  heavy.py             The heavy-model lock (Parler and Whisper never load together)
  run.py               One scored run and the exit code (batch.py: preflight and batch runs)
  cli.py               Command-line interface (cli_report.py: compare, report, judge, rescore, recordings; cli_util.py: helpers)
agents/clinic_agent/   Pipecat test agent: Silero VAD, Groq or local faster-whisper STT, Groq LLM, edge-tts; hi, kn and ta profiles
scenarios/             The Hinglish (14), Kannada-English (6) and Tamil-English (6) packs
data/real/             Your recordings of the caller turns; gitignored, never leave the machine
tests/unit/            Unit tests; no network, no keys
tests/integration/     Real-time calls against an in-process fake Pipecat agent
tests/golden/          Normaliser pairs that must and must not match, per language
tools/                 no_emoji, kg_render, check_keys, whisper_check; calibrate_eval (WSL only); parler_bench (own uv project)
docs/                  Spec, plans, research, runbooks, reviews, knowledge graph
.github/               CI workflow and Dependabot config
```

## Development

```
uv sync --all-groups
uv run pre-commit install
uv run pytest -q
```

| Check | Command | Pre-commit | CI |
|---|---|---|---|
| Lint | `uv run ruff check .` | yes (with `--fix`) | yes |
| Format | `uv run ruff format --check .` | yes (formats) | yes |
| Types | `uv run pyright` | no | yes |
| Tests | `uv run pytest -q` | no | yes |
| No emoji in tracked files | `uv run python -m tools.no_emoji` | yes | yes |
| Knowledge-graph views in sync | `uv run python -m tools.kg_render --check` | yes | yes |
| Secret scan | gitleaks | yes | yes (full history) |
| YAML, TOML, whitespace, large files | pre-commit-hooks | yes | no |

CI runs on Ubuntu and Windows and installs ffmpeg. Unit and integration tests need no network and no API keys. GitHub Actions and pre-commit hooks are pinned to full commit SHAs, and a unit test fails on any unpinned one.

## Documentation

| Document | Contents |
|---|---|
| [docs/README.md](docs/README.md) | Index of all project documentation. |
| [Design spec](docs/superpowers/specs/2026-11-15-parakh-design.md) | Goals, architecture, components, testing, CI, milestones, edge-case register, decisions. |
| [M1 runbook](docs/runbooks/run-m1.md) | Running the agent and the scenario, reading the report, troubleshooting, the run log. |
| [M2 runbook](docs/runbooks/run-m2.md) | The five presets, batch runs, the comparison page, what the M2 runs showed, Groq requests per run, troubleshooting, the run log. |
| [M3a runbook](docs/runbooks/run-m3a.md) | The Hinglish pack, the judge, resume, measured Groq use, what the M3a runs showed, judge calibration, the run log. |
| [M3b runbook](docs/runbooks/run-m3b.md) | The Kannada-English and Tamil-English packs, agent profiles, what the runs showed, the judge spot check, real recordings against synthetic runs, local STT speed, the run log. |
| [Real recordings runbook](docs/runbooks/record-real.md) | Recording your own voice, naming and checking the files, running with `--real`, and what stays on the machine. |
| [Calibrate analysis](docs/research/2026-11-15-calibrate-analysis.md) | Task 1: what Calibrate covers and lacks, the free-model run, and the verdict. |
| [`pipecat.evals` note](docs/research/2026-11-16-pipecat-evals-note.md) | What Pipecat's eval harness does and needs, and decision D14. |
| [Knowledge graph](docs/kg/README.md) | `graph.yaml` plus generated Mermaid views of the pipeline, governance and milestones. |

## Constraints

- **Free tiers only.** Groq and Gemini free tiers; OpenRouter `:free` models only for the Calibrate comparison. Any step that asks for a card is out of scope.
- **Synthetic data only to hosted APIs.** Some free tiers may train on inputs. Scenarios, caller scripts and patient records are synthetic. Real recordings (a person reading synthetic scripts) stay on the local machine under `data/real/`, which is gitignored.
- **No secrets in git.** `.env` is gitignored, gitleaks runs in pre-commit and CI, and GitHub push protection is on. Agent URLs are stripped of credentials, query and fragment wherever Parakh stores or prints them.
- **CPU only.** Local models run on CPU and never at the same time: every process that loads faster-whisper or Indic Parler-TTS holds one lock file, `.cache/locks/heavy-model.lock`.
- **No emoji** in any tracked file, enforced by `tools/no_emoji.py`.

## Relationship to Calibrate

[Calibrate](https://github.com/ARTPARK-SAHAI-ORG/calibrate) (ARTPARK-SAHAI) is a Pipecat-based evaluation framework for text and voice agents. Task 1 reviewed its source and ran one of its text simulations on free models. It covers persona simulation, interruptions and mean latency. It does not cover telephone-channel degradation, script-tolerant code-mixed scoring for external agents, deterministic task success, latency distributions, or a voice path that runs on free tiers. Parakh is therefore a standalone tool that stays protocol-compatible with Calibrate ([analysis](docs/research/2026-11-15-calibrate-analysis.md)). This is a clean-room relationship: Calibrate is licensed CC-BY-SA-4.0, and no Calibrate code is copied into this repository. `tools/calibrate_eval/` contains only MIT code that imports a separately installed copy of `calibrate-agent` inside WSL, for the comparison run.

## Relationship to `pipecat.evals`

Pipecat 1.16 added `pipecat.evals`: scripted and simulated scenarios, a cached TTS user, an LLM judge, a suite runner, 40 ms paced user audio and `within_ms` latency budgets. It needs the bot to run Pipecat's eval transport and `EvalSerializer`, and it has no telephone degradation, no script-tolerant WER and no latency distributions. Parakh keeps its own call driver, which tests unmodified agents that serve Pipecat's standard protobuf serializer (decision D14). The two are complementary: `pipecat.evals` for behavioural checks, Parakh for the audio channel and Hinglish recognition ([note](docs/research/2026-11-16-pipecat-evals-note.md)).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) first: it has the Calibrate clean-room rule, the hard constraints and the test-first workflow.

## Licence

MIT. See [LICENSE](LICENSE).

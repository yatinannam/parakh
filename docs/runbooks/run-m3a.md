# M3a run: the Hinglish scenario pack and the LLM judge

This runbook covers four things:
- Running the 14-scenario Hinglish pack against the clinic test agent.
- Rating every call with the advisory LLM judge.
- Resuming a batch that stopped.
- Reading the agent's measured Groq use.

Start with [`run-m1.md`](run-m1.md) for the agent, the key check and the single-run report, and with [`run-m2.md`](run-m2.md) for presets and the comparison page.

Only synthetic data leaves the laptop:
- edge-tts receives the scenario text.
- Groq receives the synthesised audio and the agent's text. Groq runs both the agent's STT and LLM and the judge.
- The judge payload holds the scenario goal, the scripted lines, the agent's transcript of them, the agent's replies, barge-in results and the run status. It never holds paths, URLs, agent info or warnings (`CLAUDE.md`).

## The scenario pack

All 14 scenarios in `scenarios/hinglish/` share the same setup:
- They book at Parakh Clinic with the same frozen clock, `2026-11-19T10:00:00+05:30`. The clock matches `agents/clinic_agent/config.yaml`, so "kal" is 2026-11-20 and "parso" is 2026-11-21.
- Every scenario has a `goal`, which the judge reads.
- Limits are `{ max_turns: 12, response_timeout_s: 15, call_timeout_s: 180 }`.

| Scenario | Caller voice, rate | What it tests |
|---|---|---|
| `clinic-book-hinglish-01` | hi-IN-SwaraNeural | Follow-up with Dr. Rao (M1 baseline, turns frozen) |
| `clinic-bargein-hinglish-01` | hi-IN-MadhurNeural | Interrupts the agent after 1200 ms (M2, turns frozen) |
| `clinic-book-iyer-hinglish-01` | hi-IN-MadhurNeural | Dr. Iyer (paediatrician) for a daughter, parso shaam 4 baje |
| `clinic-out-of-hours-hinglish-01` | hi-IN-SwaraNeural | Asks for 15:00, outside Dr. Rao's hours, then takes 11:30 |
| `clinic-slots-query-hinglish-01` | hi-IN-MadhurNeural | Asks which morning slots are free, picks 09:30 |
| `clinic-correction-hinglish-01` | hi-IN-SwaraNeural | Corrects the last digit of the phone number |
| `clinic-double-digits-hinglish-01` | hi-IN-MadhurNeural | Phone number with "double" and "triple" |
| `clinic-hindi-numbers-hinglish-01` | hi-IN-SwaraNeural | Phone number in Hindi number words, "bees November", "gyarah baje" |
| `clinic-english-heavy-hinglish-01` | en-IN-PrabhatNeural | Mostly English with Hindi fillers |
| `clinic-devanagari-hinglish-01` | hi-IN-SwaraNeural | Script and reference in Devanagari |
| `clinic-bargein-correction-hinglish-01` | hi-IN-MadhurNeural | Interrupts the read-back after 1500 ms to correct the time |
| `clinic-fast-caller-hinglish-01` | hi-IN-MadhurNeural, +25% | Fast speech |
| `clinic-slow-caller-hinglish-01` | hi-IN-SwaraNeural, -20% | Slow speech with fillers ("umm", "haan toh") |
| `clinic-unknown-doctor-hinglish-01` | en-IN-NeerjaNeural | Asks for Dr. Sharma (not at the clinic), then takes Dr. Rao |

## 1. Check the keys and the budget

```
uv run python -m tools.check_keys
uv run parakh budget scenarios/hinglish --preset clean
```

`check_keys` reports the Groq key and, optionally, `GEMINI_API_KEY` ([`api-keys.md`](api-keys.md)). It never prints a key.

For the pack under one preset, the estimate is:
- 159 STT and 173 LLM requests;
- 155,700 agent LLM tokens, at the measured 900 tokens per request;
- 14 judge calls.

That fits Groq's free daily limits. Two presets in one day do not fit the agent model's 200,000 tokens per day: split them across days with `--resume` (section 4).

## 2. Start the agent

```
uv run --group agent python -m agents.clinic_agent --port 8765
```

Since M3a the agent resets its VAD and STT state on every hang-up and every new call (EC-84), and it reports LLM token usage in its RTVI metrics.

The log line `TTSSettings: the following fields are NOT_GIVEN` is harmless.

## 3. Run the pack

```
uv run parakh run scenarios/hinglish --agent ws://127.0.0.1:8765 --preset clean
```

Each run prints its summary as it finishes, including the judge line, for example `judge: ok, mean 3.8 (groq openai/gpt-oss-120b)`.

A full pack batch takes about 20 to 25 minutes. On this laptop, a command that long can be moved to the background and killed when memory runs low (EC-87). The M3a runs therefore used three smaller batches, joined into one page afterwards:

```
uv run parakh compare <run dir> <run dir> ... --out runs/m3a-pack
```

## 4. Resume a batch

```
uv run parakh run scenarios/hinglish --agent ws://127.0.0.1:8765 --preset clean --resume runs/<batch_id>
```

Resume works like this:
- A (scenario, preset) pair that already has a `completed` report in that batch is skipped, with `skipped (completed): <scenario> / <preset>`.
- Every other pair runs again.
- The comparison shows the newest report per pair.

Use resume after a run ends `rate_limited` (the agent reported a Groq 429), after Ctrl+C, or after the laptop slept mid-call. In M3a it re-ran the one call the laptop interrupted (run log).

## 5. The judge

The judge is advisory. It never changes a run's status or the exit code.

**Models.** The judge runs Groq `openai/gpt-oss-120b`, which has its own free per-model limits apart from the agent's `openai/gpt-oss-20b`. Gemini `gemini-flash-lite-latest` is the fallback, used only if `GEMINI_API_KEY` is set. Both are configured in `src/parakh/judge/judge.yaml`.

**Scores.** Each run gets five scores from 1 to 5: understanding, language match, interruption handling (null without a barge-in), task progress and politeness. Each run also gets a short rationale and flags: `wrong_details`, `no_confirmation`, `repeated_question` and so on.

**Statuses.**
- `ok`: the judge returned valid scores.
- `skipped`: nothing to judge, or no key.
- `judge_error`: invalid JSON 4 times, a provider error, or an internal error.
- `rate_limited`: every provider tried was rate-limited.

**Cache.** Results are cached in `.cache/judge/`, keyed by provider, model, prompt version and payload, so judging the same report again is free.

**Re-judging.** To re-judge existing runs after a rubric change, or after a run whose judge ended `rate_limited`, run:

```
uv run parakh judge runs/<batch>/<run> ... [--force]
```

Pass `--no-judge` to `parakh run` to skip the judge.

## Measured Groq use

| Item | M3a measurement |
|---|---|
| Agent LLM, clean pack (15 runs: the 14 completed and the interrupted `7926bbeb`, which made 1 request) | 109 requests, 88,430 tokens, 811 tokens per request (from the agent's RTVI usage metrics, `metrics.agent_llm_requests` and `agent_llm_tokens`) |
| Agent LLM requests per completed run | 6 to 9 (estimate: 3 per turn plus the greeting, 13 for a 4-turn scenario) |
| Agent log, all 21 runs of the day | 168 STT and 173 LLM requests |
| Judge, all 21 runs | 20 judged (21,319 tokens, about 1,070 per call, 1 attempt each, no fallback); 1 skipped (`phone_noisy`, nothing to judge) |
| HTTP 429 or 402 | none |

The estimate's planning guess of 1500 tokens per request was replaced with the measured figure, rounded up to 900 (`LLM_TOKENS_PER_REQUEST`).

## What the M3a runs showed

All 14 scenarios completed under `clean`. One call was interrupted when the laptop slept and was re-run with `--resume`.

**Loose WER**
- Low: 0 to 21 %, mean 6.3 % after rescoring with the final normaliser.
- Strict WER is about 100 %, because Groq Whisper with language `hi` writes Hinglish in Devanagari. The exceptions are the Devanagari scenario (9.5 %) and the English-heavy one (42.9 %).

**The agent rarely finishes a booking correctly.** The judge's task progress was 1 or 2 on 12 of the 14 calls. Only the Devanagari scenario reached 5. The failures repeat:
- **Half-hour times.** Whisper writes साढ़े as साधे. The agent's LLM then reads "साधे 11" as 11:00 instead of 11:30, which happened in `out-of-hours` and `unknown-doctor`. It also read "साधे दास" as 5:30 in `double-digits`, and "shaam chaar baje" as 14:00 in `book-iyer`.
- **Phone numbers.** Whisper splits, drops or repeats digits, as in `9035-9035-9035. 778-899`, `987654321` and `9886-7888 554-433`. The agent then asks again for a 10-digit number until the call ends.
- **Reading back.** The agent books without reading the details back, flagged `no_confirmation` in 12 of 14 calls.

**Talking over the agent.** The agent's TTS splits a reply at "डॉ." (the Hindi "Dr."), because the full stop reads as a sentence end. Synthesising the next sentence takes over 800 ms, so the scripted caller's end-of-turn rule (800 ms of quiet, EC-36) fires mid-reply, and the caller speaks over the rest of the sentence (EC-88). It shows in the reports as agent text that runs on into the next turn.

**Under `phone`**
- Recognition held for the Hindi-voice scenarios: 6.9 to 9.5 %.
- The English-heavy caller (en-IN-PrabhatNeural) collapsed to 80 %. With language `hi`, Whisper renders band-limited English as Devanagari phonetics ("मैं नमबर इस ने जरो थी फवे").

**Reset check (EC-84).** `phone_noisy` and then `phone_lossy` ran back to back. The `phone_lossy` call's first turn held no babble fragment, its first speech detection came 361 ms after the caller started, and it had no false barge-in. In M2 batch `cb4a98c6`, the agent's VAD fired 13 ms after accepting the call. `phone_noisy` still never gets past the greeting: the agent's VAD takes babble for speech (EC-25).

## Normaliser feedback from the runs

Word-level alignment of every live turn found five spelling or script variants:
- अच्छ for acha;
- अयर for Iyer;
- `Dr.` for doctor;
- बाए and बइए for bye;
- the filler अम for "umm".

They are now in the golden file, as pairs that must match.

Fillers (`um`, `uh`, `hm`, and Devanagari अम, उम, हम्म) are dropped on both sides. The Devanagari ones are dropped before transliteration, so हम्म never becomes हम (we).

The slow-caller scenario's references had dropped the spoken words "haan toh" together with the fillers. They now keep them, and that call's loose WER falls from 48.0 % to 9.7 %.

Whisper's तू and थी for English "two" and "three" stay a known gap, because both are common Hindi words.

## Judge calibration (EC-52)

The table compares the judge's scores with the controller's own rubric scores on 10 calls. Five of them have the agent replying in Devanagari.

| Run | Scenario | Judge (U, L, I, T, P) | Controller (U, L, I, T, P) | Within 1 point |
|---|---|---|---|---|
| `97a0feae` | book-iyer | 3, 5, -, 2, 5 | 3, 4, -, 2, 4 | yes |
| `b15341e3` | bargein | 2, 4, 2, 2, 5 | 2, 3, 3, 2, 4 | yes |
| `f34b1caf` | bargein-correction | 2, 3, 5, 1, 3 | 2, 3, 4, 1, 4 | yes |
| `c0ca4538` | devanagari | 5, 4, -, 5, 5 | 4, 5, -, 5, 5 | yes |
| `baf7f5e1` | double-digits | 2, 4, -, 1, 5 | 2, 5, -, 1, 4 | yes |
| `539970e6` | english-heavy | 2, 4, -, 1, 3 | 2, 5, -, 1, 4 | yes |
| `5f0a2846` | hindi-numbers | 3, 5, -, 2, 5 | 3, 5, -, 2, 5 | yes |
| `59732a4c` | out-of-hours | 3, 5, -, 2, 4 | 3, 5, -, 2, 5 | yes |
| `418f1075` | unknown-doctor | 3, 5, -, 3, 5 | 3, 5, -, 2, 5 | yes |
| `74412c31` | slots-query | 2, 5, -, 1, 3 | 2, 5, -, 1, 4 | yes |

Key: U understanding, L language match, I interruption handling, T task progress, P politeness.

The judge agreed within 1 point on all 10 calls, and never lowered language match for a Hinglish or Devanagari reply in the caller's register. Its one 3 for language match was a call where the agent answered a Hinglish caller in English. The rubric stays `judge-v1`.

One wording issue: for a barge-in that landed after the agent had already finished, the judge read "agent finished first" as a slow reaction, and gave interruption handling 2. Yatin confirms this table later.

## Troubleshooting

- **A run ends `rate_limited`.** The agent reported a Groq 429. Stop for the day and resume the batch after the limit resets (section 4).
- **The judge shows `judge_error`.** Read the reason in `report.html`: provider and cause, with keys scrubbed. Then re-judge with `parakh judge <run dir>`.
- **The judge shows `skipped (no judge API key)`.** `GROQ_API_KEY` is missing from `.env` or the environment.
- **The Gemini key is missing.** That is fine: Gemini is only the fallback.
- **A warning says `could not read .env`.** The file is not UTF-8, often because PowerShell 5.1 `>` wrote it as UTF-16. Re-save it as UTF-8.
- **The agent's token limit runs out.** The agent model allows 200,000 tokens per day and the pack uses about 156,000 per preset. Run one preset per day and resume.
- **A call shows `timing_unreliable` with a jitter maximum of minutes.** The laptop slept or the process was suspended mid-call. Resume the batch to re-run it.

## Run log

**2026-11-23, Parakh `aba4001` to `701c40d`**, agent `openai/gpt-oss-20b`, judge `openai/gpt-oss-120b`, all runs `clean` unless noted:
- `97a0feae`: `clinic-book-iyer-hinglish-01`, the measuring run.
- `7b007b6a`: batch A.
  - Bargein-correction, bargein, correction and devanagari completed.
  - Book: run `7926bbeb` stopped at `call_timeout` with `timing_unreliable`. The process paused for about 39 minutes mid-call; the agent log is silent from 11:58 to 12:37.
  - Book was re-run as `8ccd59f7` with `--resume runs/7b007b6a`, which skipped the 4 completed runs.
- `f13d24bd`: batch B, double-digits, english-heavy, fast-caller and hindi-numbers, all completed.
- `d4ebdac0`: batch C, out-of-hours, slots-query, slow-caller and unknown-doctor, all completed.
- `ce97e9c8`: `clinic-book-hinglish-01` under `phone_noisy` (`turn_timeout`, judge skipped) and then `phone_lossy` (completed): the reset check.
- `438aebff`: devanagari, english-heavy, hindi-numbers and unknown-doctor under `phone`, all completed.
- `runs/m3a-pack/compare.html`: all of the above on one page, without the interrupted run.

Loose WER is per run, rescored with the final normaliser and references. "As run" is the figure printed at the time.

| Scenario | Preset | Status | Turns | Loose WER (as run) | Strict WER | p50 / p95 ms | Judge mean | Task progress |
|---|---|---|---|---|---|---|---|---|
| bargein | clean | completed | 4/4 | 0.0 % | 103.3 % | 5375 / 5984 | 3.0 | 2 |
| bargein-correction | clean | completed | 4/4 | 16.1 % | 106.5 % | 3789 / 4730 | 2.8 | 1 |
| book | clean | completed | 4/4 | 3.3 % | 100.0 % | 4057 / 5103 | 3.2 | 2 |
| book-iyer | clean | completed | 4/4 | 0.0 % (6.7 %) | 120.0 % | 3783 / 4907 | 3.8 | 2 |
| correction | clean | completed | 4/4 | 21.2 % | 100.0 % | 3168 / 3591 | 3.0 | 1 |
| devanagari | clean | completed | 3/3 | 0.0 % | 9.5 % | 4818 / 5933 | 4.8 | 5 |
| double-digits | clean | completed | 3/3 | 9.1 % | 100.0 % | 6077 / 6224 | 3.0 | 1 |
| english-heavy | clean | completed | 4/4 | 2.9 % (5.7 %) | 42.9 % | 3123 / 5629 | 2.5 | 1 |
| fast-caller | clean | completed | 3/3 | 4.8 % (14.3 %) | 123.8 % | 4338 / 5714 | 3.2 | 1 |
| hindi-numbers | clean | completed | 4/4 | 3.7 % | 100.0 % | 3245 / 5389 | 3.8 | 2 |
| out-of-hours | clean | completed | 4/4 | 0.0 % (3.4 %) | 100.0 % | 3119 / 4440 | 3.5 | 2 |
| slots-query | clean | completed | 4/4 | 6.9 % | 106.9 % | 3462 / 4112 | 2.8 | 1 |
| slow-caller | clean | completed | 4/4 | 9.7 % (48.0 %) | 144.0 % | 3093 / 4708 | 2.0 | 1 |
| unknown-doctor | clean | completed | 4/4 | 10.3 % (13.8 %) | 117.2 % | 4016 / 5864 | 4.0 | 3 |
| devanagari | phone | completed | 3/3 | 9.5 % | 19.0 % | 4277 / 4857 | 4.2 | 5 |
| english-heavy | phone | completed | 4/4 | 80.0 % | 100.0 % | 3132 / 4005 | 3.2 | 2 |
| hindi-numbers | phone | completed | 4/4 | 7.4 % | 100.0 % | 2969 / 5666 | 3.5 | 2 |
| unknown-doctor | phone | completed | 4/4 | 6.9 % (10.3 %) | 113.8 % | 3663 / 5808 | 3.8 | 2 |
| book | phone_lossy | completed | 4/4 | 13.3 % | 93.3 % | 3222 / 3741 | 3.2 | 2 |
| book | phone_noisy | turn_timeout | 0/4 | n/a | n/a | n/a | skipped | n/a |

Strict WER can exceed 100 % because insertions count. The barge-in runs: `bargein` had `agent_finished_first`, and `bargein-correction` stopped after 331 ms via the interruption frame.

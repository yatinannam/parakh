# M3b run: Kannada-English and Tamil-English, real recordings and Parler

This runbook covers:
- Running the Kannada-English and Tamil-English packs against a clinic agent with the matching language profile.
- Running your real recordings through a local-STT agent (pending: see section 6).
- The Indic Parler-TTS benchmark (pending: see section 7).
- What the first Kannada and Tamil runs showed, and the fixes they led to.

Start with [`run-m1.md`](run-m1.md) for the agent, the key check and the single-run report, with [`run-m2.md`](run-m2.md) for presets and the comparison page, and with [`run-m3a.md`](run-m3a.md) for the judge, `--resume` and batches.

Only synthetic data leaves the laptop:
- edge-tts receives the scenario text.
- Groq receives the synthesised audio and the agent's text, for the agent's STT and LLM and for the judge.
- Real recordings never leave the laptop. The rules are in [`record-real.md`](record-real.md).

## The scenario packs

The packs are `scenarios/kannada_en/` (language `kn-en`) and `scenarios/tamil_en/` (language `ta-en`). Each has six scenarios, with the same clinic, clock and goals as the Hinglish pack.

| Scenario, `clinic-<name>-kannada-01` or `-tamil-01` | Caller voice | What it tests |
|---|---|---|
| `book` | kn-IN-GaganNeural, ta-IN-ValluvarNeural | Book Doctor Rao for tomorrow at 10:00 |
| `book-iyer` | same | Book Doctor Iyer for a son, the day after tomorrow at 16:00 |
| `bargein` | same | Interrupt the read-back to correct the time |
| `numbers` | same | The phone number in Kannada or Tamil number words |
| `script` | same | The caller's lines in Kannada or Tamil script |
| `english-heavy` | en-IN-PrabhatNeural | Mostly English, with Kannada or Tamil fillers |

## 1. Check the keys and the budget

```powershell
uv run python -m tools.check_keys
uv run parakh budget scenarios/kannada_en scenarios/tamil_en
```

The estimate for one pack under `clean` is 72 STT calls, 78 LLM calls and 70,200 agent tokens, plus 6 judge calls. The measured use was lower (see "Measured Groq use"). Both packs fit in one day under the agent model's 200,000 tokens.

## 2. Start an agent with the pack's profile

One agent process serves one language (D18). Its profile sets the STT language hint and the TTS voice:

| Profile | STT language | Agent voice | Replies in |
|---|---|---|---|
| `hi` (default) | `hi` | hi-IN-SwaraNeural | Devanagari or Latin script |
| `kn` | `kn` | kn-IN-SapnaNeural | Kannada or Latin script |
| `ta` | `ta` | ta-IN-PallaviNeural | Tamil or Latin script |

```powershell
uv run --group agent python -m agents.clinic_agent --profile kn
```

Wait for `pipeline is now ready` in its log. A `TTSSettings: the following fields are NOT_GIVEN` error at start-up is a harmless Pipecat 1.16.0 warning.

If the scenario language does not match the agent's profile, the run proceeds and the report and CLI show `agent language hi does not match scenario language kn-en`. Stop the agent and start it with the right profile.

`--stt local` swaps Groq Whisper for faster-whisper `small` (int8, CPU). It holds the heavy-model lock, and real recordings need it (section 6).

## 3. Run the packs

Run each pack in two batches of three, so no command runs long enough to be moved to the background (EC-87). Copy the scenario files into two folders, then:

```powershell
uv run parakh run <folder-1> --agent ws://127.0.0.1:8765 --preset clean
uv run parakh run <folder-2> --agent ws://127.0.0.1:8765 --preset clean
```

Check free memory before each batch. Stop the agent between packs and start it again with the other profile. Join the runs on one page with `parakh compare <run dirs> --out <dir>`. `--out` takes a directory and writes `compare.html` into it.

## 4. Measured Groq use

| Item | M3b measurement, 14 clean runs (12 pack runs and 2 re-runs) |
|---|---|
| Agent LLM | 104 requests, 90,923 tokens, 874 tokens per request |
| Agent LLM per pack | Kannada 44 requests and 36,707 tokens; Tamil 47 requests and 43,119 tokens (estimate: 78 and 70,200) |
| Agent STT (Groq Whisper requests in the agent logs) | Kannada pack 35, Tamil pack 58, re-runs 4 and 9 (estimate: 72 per pack) |
| Judge | 14 judged, 15,155 tokens, about 1,080 per call, 1 attempt each, no fallback |
| Checks of the agent fix (section 5) | 15 LLM requests on the agent model, 2 STT requests |
| HTTP 429 or 402 | none |

The agent's VAD split the Tamil caller's turns into more pieces than the Kannada caller's, so the Tamil pack made more STT requests for the same number of turns.

## 5. What the Kannada and Tamil runs showed

Loose WER is shown as run and after `parakh rescore` with the normaliser rules the runs led to (`b3bfce0`). Strict WER does not depend on those rules. "Excluded" lists the turns (1-based) that Whisper wrote in Urdu or Arabic script; EC-41 leaves them out of loose WER.

| Run | Scenario | Status | Strict WER % | Loose WER % as run | Loose WER % rescored | Excluded | Latency p50 / p95 ms | Judge mean | Judge L |
|---|---|---|---|---|---|---|---|---|---|
| `724ccec2/15b24641` | kn book | completed | 105.0 | 75.0 | 70.0 | - | 4026 / 5923 | 2.0 | 3 |
| `724ccec2/0a47e1e3` | kn book-iyer | completed | 126.3 | 73.7 | 68.4 | - | 4073 / 6039 | 2.5 | 3 |
| `724ccec2/e20b7ccd` | kn bargein | completed | 77.8 | 53.8 | 46.2 | - | 4145 / 5794 | 2.2 | 1 |
| `114c1a47/7cb6b5d2` | kn numbers | turn_timeout | 133.3 | 81.8 | 72.7 | 3, 4 | 3456 / 3514 | 2.2 | 3 |
| `cfb51c6c` | kn numbers, re-run | completed | 144.4 | 100.0 | 90.9 | 3, 4 | 3777 / 5908 | 1.8 | 2 |
| `114c1a47/6d8a2ac3` | kn script | completed | 116.7 | 50.0 | 38.9 | - | 3311 / 3775 | 3.5 | 3 |
| `114c1a47/3b0fd821` | kn english-heavy | completed | 43.3 | 13.8 | 13.8 | - | 5140 / 5868 | 3.2 | 4 |
| `fa1030bb/e670e0ec` | ta book | completed | 122.2 | 42.9 | 35.7 | 4 | 4434 / 5466 | 2.0 | 2 |
| `fa1030bb/583671ad` | ta book-iyer | completed | 94.4 | 44.4 | 44.4 | - | 5712 / 7322 | 2.8 | 4 |
| `fa1030bb/6e9e310e` | ta bargein | completed | 103.8 | 25.0 | 25.0 | 3, 4 | 6012 / 6336 | 3.2 | 4 |
| `6413aef3/11b2aaf2` | ta numbers | turn_timeout | 133.3 | 100.0 | 78.6 | 4 | 4411 / 5876 | 1.8 | 2 |
| `77ff1322` | ta numbers, re-run | completed | 133.3 | 88.9 | 72.2 | - | 3641 / 5737 | 2.5 | 3 |
| `6413aef3/8f20373e` | ta script | completed | 105.6 | 64.3 | 57.1 | 4 | 6080 / 7209 | 2.0 | 2 |
| `6413aef3/a4dd4f81` | ta english-heavy | completed | 43.8 | 22.2 | 22.2 | 1, 4 | 4162 / 6920 | 2.8 | 4 |

Judge L is the judge's language match. Task success comes with M4.

**Recognition is the bottleneck.** Over the six pack runs, the mean loose WER is 51.7 % for Kannada (58.0 % as run) and 43.8 % for Tamil (49.8 % as run). The Hinglish pack's mean was 6.3 % in M3a. Word alignment shows that most errors are words Whisper misheard, not spellings the normaliser missed:
- Kannada: "Nail Dhrarav Jyotaj appointment BQ" for "naale Dr. Rao jotege appointment beku"; "Allah Allah, hat again Allah" for "illa illa, hattu gante alla"; Kannada-script strings that are not words, such as "ನಾಲದನ ನಾನನ ದಾಲದ", for the time turns.
- Tamil: "and" for "en" (my) in 4 calls; வணக்கம் for "Hello"; ராக் for Rao; சிரி (laugh) for seri.
- Only the English-heavy callers score low WER: 13.8 % and 22.2 %.

**The Tamil figures leave out more turns.** Whisper wrote Urdu or Arabic script in 7 of the 24 Tamil turns and in 2 of the 24 Kannada turns, mostly in the closing turn ("Seri, thank you, bye" and similar). EC-41 excludes such turns from loose WER and lists them in `metrics.script_unsupported_turns`, so the Tamil mean covers 17 of 24 turns. Compare the packs only together with the excluded count. Whether kn-en and ta-en should count these turns as errors, or get a Perso-Arabic romaniser, is a spec decision for the backlog.

**The language hint does not fix the script.** A cached synthetic clip of "Seri, thank you, bye." went to Groq `whisper-large-v3-turbo` with `language=ta`. The whole clip came back as `سیری, thank you, bye.`, and its first 0.6 s as `سیری`. Pipecat's `GroqSTTService` does send the hint.

**EC-92: script drift silenced the agent.** Both `numbers` calls ended `turn_timeout`, in the same way:
1. Whisper wrote the caller's goodbye in Urdu script, and in the Tamil call partly in Devanagari (`बाइ`).
2. The agent's LLM replied in that script: Arabic in the Kannada call, Hindi in the Tamil call ("धन्यवाद, आपकी बुकिंग पुष्टि हो गई है.").
3. The kn-IN and ta-IN voices cannot read those scripts. edge-tts returned `No audio was received`, so the caller's last turn got no agent audio.

The fix (`4d03df2`) adds a prompt rule. It names the scripts the profile's voice reads, and tells the LLM to treat any other script as a transcription error. The fix was checked three ways:
- Replay: the two call endings (the agent's own transcripts, without the tool messages) went to `openai/gpt-oss-20b`. With the old prompt, 3 of 6 replies were in a script the voice cannot read (2 Arabic, 1 Devanagari). With the new prompt, none of 9 were, and 7 of the 9 had text. Three replies in the first round were empty, because the check capped output at 400 tokens and the model spent them on reasoning; the three Tamil re-checks used a 2,000-token cap.
- Live: both `numbers` scenarios completed.
- The Kannada re-run got Arabic-script transcripts again for turns 3 and 4. The agent replied in English and Kannada.

**The agent still rarely books correctly**, as in M3a. The judge's task progress was 1 on 12 of the 14 calls. The agent mostly answered in English. It also invented details:
- In the Tamil script call, it told the caller the booking was confirmed, with the number 9876543210, before the caller gave a number.
- In the first Tamil numbers call, it booked Doctor Iyer for 2026-11-19 at 14:30 with a misheard number. It read the number back but booked before the caller answered.

## Normaliser feedback from the runs

The 14 runs were aligned word by word against their references. Only spellings of the word that was said became pairs. A transcript of a different word is a recognition error, not a pair.

New rules (`b3bfce0`), each pinned by observed `must_match` pairs:
- kn-en: `BQ` (key `bk`) reads beku. `erdu` and ಎರ್ಡು, the spoken form, read 2.
- ta-en: காலையில், காலையிலா and காலையல read kaalaila. பூஜம் reads 0.

Further observed pairs that already matched were pinned: 14 Kannada and 13 Tamil. The commit message of `b3bfce0` gives 17 and 14 by mistake: 17 and 18 are the totals of observed pairs, including the 3 and 5 pairs for the new rules.

New known gaps:
- Kannada (3): `jyotaj` for jotege; ರಾವಹತ್ತಿರ, two words joined; English "to" for two in a phone number.
- Tamil (10): the dental த for the retroflex ட in கித்தா, டாக்தர and ஏத்து, which R6 keeps apart; நான்தரி for nandri; பத்த for pathu; `No.` for number; பாய் for bye; two joined words; and வேணாம் (do not want), which matches venum (want) through the consonant skeleton. The last one was found while checking the observed வேணம்.

The golden files now hold 150 Kannada pairs (13 known gaps) and 157 Tamil pairs (24 known gaps). The Hinglish golden tokens are unchanged. Rescoring lowered loose WER by 0 to 21 points, and no run rose.

## Judge spot check

The controller read 8 judged calls, chosen for low language-match scores.

| Run | Scenario | Agent replies | Judge L | Controller's view |
|---|---|---|---|---|
| `e20b7ccd` | kn bargein | English | 1 | Too low. The caller used English words, so English is "understandable but awkward" (3). The rationale also calls the caller's speech "Kannada/Hindi". |
| `cfb51c6c` | kn numbers, re-run | English, one Kannada reply | 2 | Low; 3 by the rubric. |
| `6d8a2ac3` | kn script | English | 3 | Fair. |
| `15b24641` | kn book | English, one Kannada reply | 3 | Fair. |
| `11b2aaf2` | ta numbers | Tamil script, formal | 2, `language_mismatch` | Lowered for a reply in the caller's own language. Formal Tamil to a colloquial caller is worth at most one point off (4). |
| `8f20373e` | ta script | English | 2 | Defensible: the caller spoke only Tamil, with English loanwords. |
| `e670e0ec` | ta book | English, one formal Tamil reply | 2 | A point low (3). |
| `a4dd4f81` | ta english-heavy | English | 4 | Fair. |

So the judge lowered language match for a Tamil reply in the caller's language once. Twice it scored English replies to callers who used English words below the rubric's 3. The cause is the rubric: `judge-v1` exempts only Hinglish mixing and script changes. **Flag for `judge-v2`:** extend that sentence to Kannada-English and Tamil-English, and to the Kannada and Tamil scripts. Yatin confirms later.

## 6. Real recordings (pending)

Status: not run yet. It waits for two things from Yatin:
- Clips for the four Hinglish scenarios in [`record-real.md`](record-real.md): `clinic-book`, `clinic-book-iyer`, `clinic-hindi-numbers` and `clinic-correction`.
- His OK that the agent's Groq LLM receives the agent's transcript of his voice. The audio itself never leaves the laptop (D10).

M3b stays open until these runs are done. The procedure:
1. Check each scenario's clips: `uv run parakh recordings status scenarios/hinglish/<file>`. It exits 2 while a turn is missing or silent.
2. Close Chrome if free memory is under about 3 GB: faster-whisper `small` loads in the agent process.
3. Start the agent with local STT: `uv run --group agent python -m agents.clinic_agent --profile hi --stt local`. It takes the heavy-model lock, so no Parler process may run at the same time.
4. Run each scenario under `clean` and `phone`: `uv run parakh run scenarios/hinglish/<file> --agent ws://127.0.0.1:8765 --real --preset clean --preset phone`.
5. Expect completed runs with `real_audio: true` and the judge skipped (D20). The agent log must show local STT and no Groq STT request.

The results go here, next to the same scenarios' synthetic runs from M3a.

## 7. Indic Parler-TTS benchmark (pending)

Status: not run yet. It needs `HF_TOKEN` in `.env`:
1. Accept the model terms on `https://huggingface.co/ai4bharat/indic-parler-tts` while logged in. Approval is automatic, and no card is asked.
2. Create a read token and add it to `.env` as `HF_TOKEN`.
3. Check it with `uv run python -m tools.check_keys`.

The run, the thresholds and the ruling are in the M3b plan, Task 8. The verdict and the research note link go here.

## Troubleshooting

- **A Kannada or Tamil call ends `turn_timeout` with `No audio was received` in the warnings.** The agent replied in a script its voice cannot read (EC-92). The agent log's `Generating TTS [...]` line shows the text. `4d03df2` fixed the known case; report any new one.
- **Loose WER looks low, but many turns are excluded.** Whisper wrote those turns in Urdu or Arabic script. Read `metrics.script_unsupported_turns`, or the "Urdu-script turns" row in `report.html`, before comparing runs.
- **The run warns `agent language hi does not match scenario language kn-en`.** Restart the agent with `--profile kn` (or `ta`).
- **`TTSSettings: the following fields are NOT_GIVEN` at agent start.** A harmless Pipecat 1.16.0 warning.
- **Free memory is low.** On 2026-11-25 it fell to 1.3 GB during the Tamil runs, with Chrome holding 4.8 GB. The Groq-STT agent ran fine. Close Chrome before `--stt local` or a Parler run.
- **Printing a report from Git Bash fails with `UnicodeEncodeError`.** Set `PYTHONIOENCODING=utf-8` first.

## Run log

**2026-11-25, Parakh `19d1030`**, agent `openai/gpt-oss-20b`, judge `openai/gpt-oss-120b`, all runs `clean`:
- Kannada agent (`--profile kn`), from 07:54 IST:
  - `724ccec2`: book-iyer, book and bargein, all completed.
  - `114c1a47`: english-heavy and script completed; numbers ended `turn_timeout` (EC-92).
- Tamil agent (`--profile ta`), from 18:24 IST:
  - `fa1030bb`: bargein, book-iyer and book, all completed.
  - `6413aef3`: english-heavy and script completed; numbers ended `turn_timeout` (EC-92). Free memory was 1.3 GB before this batch.
- Re-runs with the agent fix from the working tree. It was committed afterwards as `4d03df2`, so the reports record `19d1030`:
  - `77ff1322`: Tamil numbers, completed.
  - `cfb51c6c`: Kannada numbers, completed.
- All 14 runs were rescored after `b3bfce0`.
- `runs/m3b-kn/compare.html` and `runs/m3b-ta/compare.html`: each pack with its re-run, rescored.

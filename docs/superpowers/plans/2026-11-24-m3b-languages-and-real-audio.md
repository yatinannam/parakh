# M3b Indic Layer, Part 2: Kannada and Tamil, Real Recordings, Parler and the Heavy-Model Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parakh scores Kannada-English and Tamil-English calls, runs a small set of Yatin's real recordings through a local-STT agent without the audio leaving the laptop, benchmarks Indic Parler-TTS on this CPU and adopts it as an offline engine if it passes, and never loads Parler and Whisper together (spec section 10, M3b). Before that, it closes the four M3a carry-overs: judge token limits, the real-data rule for the judge, the README note, and `parakh rescore`.

**Architecture:**
- **Normaliser.** It becomes language-aware: `normalize(text, language)`. Each script gets its own romaniser (Devanagari and Kannada through indic-transliteration; Tamil through Parakh's own table, because indic-transliteration's Tamil output is unusable). Each language gets its own number words and variants. The Hinglish behaviour stays exactly as it is.
- **Agent.** The clinic agent gains language profiles (STT language hint and TTS voice) and a local faster-whisper STT mode.
- **Real recordings.** A recorded turn replaces the TTS clip. The driver refuses to send a recorded frame unless the agent is on loopback and reports local STT.
- **Parler.** Parler and its torch stack live in a separate uv project, `tools/parler_bench/`, outside Parakh's lock and CI. Parakh reaches it only through a subprocess held under the heavy-model lock.

**Tech Stack:** Python 3.11, uv, pydantic v2, Typer, indic-transliteration, jiwer, hypothesis, httpx, edge-tts (`kn-IN`, `ta-IN` voices), pipecat-ai 1.16.0 with the `whisper` extra (faster-whisper on CPU, int8), psutil. In `tools/parler_bench/` only: torch (CPU), transformers and parler-tts.

**Spec:** `docs/superpowers/specs/2026-11-15-parakh-design.md`. The sections are:
- 3, and decisions D9 and D10;
- 6.2 (TTS and Parler), 6.5 (agent), 6.7 (normaliser and judge), 6.8, 6.9, 6.10, 7 (repo layout), 10 (the M3b row), 13;
- the rows of 11: EC-04, EC-13, EC-15, EC-40 to EC-44, EC-60, EC-63, EC-88 and EC-91.

M3a carry-overs: `docs/reviews/2026-11-24-m3a-review.md`, "Fix at the start of M3b".

## Global Constraints

- **Free only, no card.** The Parler model `ai4bharat/indic-parler-tts` (Apache-2.0) is gated with automatic approval, so a free Hugging Face account accepts its terms and a read token goes in `.env` as `HF_TOKEN`. The faster-whisper model `Systran/faster-whisper-small` (MIT) is not gated. Stop on HTTP 402 or 429, or on any card or payment prompt.
- **Real recordings never leave the laptop (D10, EC-60).** Recorded audio is never sent to edge-tts, Groq, Gemini or Hugging Face.
  - A real run requires an agent URL whose host is loopback (`127.0.0.1`, `localhost` or `::1`).
  - It also requires an agent whose reported `stt_model` starts with `local:`. Until the agent's info arrives and passes both checks, the driver sends only silence.
  - The judge is skipped for real runs.
  - `data/real/` stays gitignored.
- **Synthetic data only to remote APIs** for everything else: scenario text, babble text, Parler benchmark text, and the agent's transcripts of synthetic audio.
- **Keys.** Never read, print or paste `.env`. Check keys with `uv run python -m tools.check_keys`, which gains `HF_TOKEN` (optional).
- **Heavy dependencies stay out of Parakh's lock.** torch, transformers and parler-tts appear only in `tools/parler_bench/pyproject.toml` and its own `uv.lock`. Its torch comes from the CPU index. CI never installs them. faster-whisper comes only through the agent group (`pipecat-ai[websocket,silero,groq,whisper]==1.16.0`). No model weights are committed.
- **Heavy-model lock (EC-04).** One lock file, `.cache/locks/heavy-model.lock`, guards every process that loads Indic Parler-TTS or faster-whisper. A second holder fails fast, with a message naming the first.
- **Hinglish behaviour is frozen.** `normalize(text)` with no language, and `normalize(text, "hi-en")`, give exactly the M3a tokens: the existing golden file and property tests pass unchanged.
- **Carried from M3a:**
  - `pipecat-ai==1.16.0`.
  - The judge is advisory.
  - Exit codes are unchanged, plus a new status `real_data_refused` (exit 2).
  - `pathlib` everywhere, and paths with spaces in tests.
  - `filterwarnings = ["error"]`.
  - Hypothesis settings: `derandomize=True, database=None, max_examples=200, deadline=None`.
  - No source file above about 350 lines.
  - Coverage 85 % or more on `parakh.score`, `parakh.judge`, `parakh.budget`, `parakh.caller` and `parakh.degrade`.
  - No emoji. Conventional Commits. Push to `main` after each task.
- **Foreground only.** Never use run_in_background. Run the suite in the four foreground chunks, each under 3 minutes:
  1. `uv run pytest -q -p no:cacheprovider tests/unit --ignore=tests/unit/degrade --ignore=tests/unit/agent`
  2. `... tests/unit/degrade tests/unit/agent`
  3. `... tests/integration/test_driver.py`
  4. `... tests/integration/test_cli_run.py tests/integration/test_agent_reconnect.py`

  Clear `__pycache__` before the last run. Keep file writes and tool outputs moderate in size.

**Planning rulings:**
1. **One agent process per language.** The agent takes `--profile hi|kn|ta` (STT language and TTS voice), and a run of the Kannada pack targets a Kannada-profile agent. Parakh warns on a mismatch and does not switch the agent per call. This needs no protocol change. Recorded as D18.
2. **Tamil romanisation is Parakh's own code.** `indic-transliteration` turns எனக்கு into `èனghghu` and leaves ன unconverted. Kannada uses indic-transliteration to ITRANS, with accents folded to ASCII. The Devanagari final-schwa rule applies to Devanagari words only, because Kannada and Tamil words end in vowels. Recorded as D19.
3. **Number tables are chosen by scenario language:** `hi-en` and `hi` use Hindi and English, `kn-en` uses Kannada and English, `ta-en` uses Tamil and English, `en` uses English. A word is never read as a number in a language it does not belong to.
4. **Real runs skip the judge.** D10 lets the agent's LLM see the transcript, but a real recording can carry unscripted speech, such as a room voice, so Parakh sends none of it to its own judge. Recorded as D20.
5. **Recordings live at `data/real/<scenario_id>/turn-<NN>.<ext>`.** `NN` is the 1-based turn number, two digits. Any ffmpeg-readable format is accepted, so Windows Voice Recorder's `.m4a` works. Yatin records with any tool. Parakh adds no microphone dependency.
6. **Parler is adopted only if the benchmark passes all three thresholds on this laptop.** My call for spec 10's "fast enough":
   - real-time factor of 10 or less (synthesis wall time over audio duration, after the first warm-up sentence);
   - peak resident memory of 6 GB or less;
   - intelligibility: loose WER of 25 % or less when Groq Whisper transcribes the clips, in each of Hindi, Kannada and Tamil.

   If it fails, Task 9 is skipped with a recorded ruling, and Parler stays on the backlog. Recorded as D21.
7. **EC-88 gets an agent fix.** The clinic agent's prompt tells the LLM to write "Doctor" in full, never "Dr." or "डॉ.". M3a results stay as they were recorded.

## Review Focus

1. **A real run against an agent that is not provably local.** Cases: the agent URL is not loopback; the agent reports `stt_model` without the `local:` prefix; the agent sends no agent info within 5 s. In every case no recorded audio frame is sent. The run ends `real_data_refused` (exit 2) with a reason, and the report holds no transcript. Tests: Task 6 `test_real_run_refuses_remote_url`, `test_real_run_refuses_remote_stt`, `test_real_run_refuses_without_agent_info`.
2. **A recording that is missing, silent or odd.** Cases: a `.m4a` at 48 kHz stereo, a silent file, a file for a turn that does not exist, a missing turn. Odd formats decode to 16 kHz mono and play. Silent or missing turns fail before the call, naming the file, with exit 2. A stray file is listed as unused. Tests: Task 6 `test_recordings_decode_any_format`, `test_missing_or_silent_recording_fails_before_call`, `test_status_lists_unused_files`.
3. **Mixed-script transcripts in Kannada and Tamil runs.** Cases: Kannada or Tamil script with English words in Latin, Kannada (೦-೯) or Tamil (௦-௯) numerals, and Tamil ழ, ற and ன. Numerals become digits, mixed text normalises token by token, and every token is ASCII. Tests: Task 4 `test_native_numerals`, `test_tamil_letters_romanise`, `test_property_ascii_tokens_kn_ta`.
4. **A Kannada scenario run against a Hindi-profile agent.** The run proceeds, and the report and CLI show the warning `agent language hi does not match scenario language kn-en`. Tests: Task 2 `test_language_mismatch_warns`.
5. **The heavy-model lock left by a crashed process.** A stale lock (its PID is gone) is taken over. A live holder gives `HeavyModelBusy` naming its owner and PID. Releasing never deletes another process's lock. Tests: Task 5 `test_stale_lock_taken_over`, `test_live_holder_blocks`, `test_release_keeps_foreign_lock`.

---

### Task 1: M3a carry-overs: judge token limits, `parakh rescore`, README note

**Files:**
- Modify:
  - `src/parakh/judge/judge.yaml`, `src/parakh/judge/providers.py`, `src/parakh/judge/runner.py`;
  - `src/parakh/budget/quota.py`, `src/parakh/budget/estimate.py`;
  - `src/parakh/cli_report.py`;
  - `README.md`.
- Create: `src/parakh/report/rescore.py`
- Test: `tests/unit/judge/test_runner.py`, `tests/unit/test_quota.py`, `tests/unit/test_budget.py`, `tests/unit/test_rescore.py` (new), `tests/unit/test_cli.py`

**Interfaces:**
- `ProviderConfig` gains `tpm: int | None` and `tpd: int | None`. In `judge.yaml`, Groq gets `tpm: 8000, tpd: 200000`, and Gemini gets `null` for both.
- `TokenBucket.acquire(self, sleep=..., cost: float = 1.0)`. `cost` may exceed 1. A cost above the capacity waits until the bucket is full, then spends it all.
- `DailyCounter.take(self, amount: int = 1)`. A second counter per provider counts tokens: its file is `<provider>__<model>__tokens__<day>.json`.
- `JudgeRunner`, per attempt:
  1. Before sending, it estimates `ceil(len(system + user) / 3) + 600` tokens and spends that from a per-provider TPM `TokenBucket`, when `tpm` is set.
  2. After a reply, it adds the reply's real `tokens` (or the estimate, when the reply has none) to the daily token counter.
  3. When the daily token counter would pass `tpd`, the provider ends with `QuotaExhausted`, reason `daily token limit reached`.
- `estimate`: `JUDGE_TOKENS_PER_CALL = 1100`, measured in M3a (21,319 tokens over 20 calls, rounded up). The estimate gains `judge_tokens`, and it adds a note when judge tokens exceed the judge model's `tpd`. `parakh budget` prints `judge tokens: N`.
- `rescore_report(report: Report, scenario: Scenario) -> Report` in `parakh.report.rescore`:
  - It recomputes each turn's `reference`, `strict_wer` and `loose_wer`, and the metrics `strict_wer`, `loose_wer`, `loose_cer`, `wer_reason` and `script_unsupported_turns`.
  - It uses the report's stored transcripts and the scenario's current references.
  - It changes nothing else: latency, judge, status and the rest stay as they are.
- CLI `parakh rescore RUN_DIR... [--scenarios DIR]`. The default DIR is `scenarios/`, searched recursively by `id`.
  - For each run it rewrites `report.json` and `report.html` and prints `<run_dir>: loose WER <old> -> <new>`.
  - A missing scenario id or an unreadable report prints a message and exits 2.
- README, under the judge: "The judge sends the scenario goal, the scripted lines, the agent's transcript of them and the agent's replies to Groq (or Gemini). With an agent other than the synthetic clinic agent, check that its replies carry no real data, or pass `--no-judge`."

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/judge/test_runner.py
async def test_tpm_paces_large_calls(tmp_path):   # tpm 3000, payload ~2400 estimated tokens: 2nd call sleeps
async def test_daily_token_limit_ends_provider(tmp_path):   # tpd 1500, first reply tokens 1200: 2nd judge rate_limited
                                                            # at groq ("daily token limit reached"), falls to gemini
# tests/unit/test_quota.py
async def test_bucket_cost_above_one():           # per_minute 10: acquire(cost=6) twice -> second waits 12 s
def test_counter_take_amount(tmp_path):           # per_day 10: take(7) ok, take(4) raises QuotaExhausted
# tests/unit/test_budget.py
def test_estimate_counts_judge_tokens():          # 1 scenario, 1 preset: judge_tokens == 1100
# tests/unit/test_rescore.py
def test_rescore_uses_current_reference(tmp_path):  # report with ref "a b", scenario ref "a b c": loose_wer rises,
                                                    # latency and judge untouched
def test_rescore_marks_urdu_turns():
# tests/unit/test_cli.py
def test_rescore_command_prints_old_and_new(tmp_path):
def test_rescore_unknown_scenario_exits_2(tmp_path):
```

- [ ] **Step 2: Run** chunk 1. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** the four chunks, `uv run pyright` and `uv run ruff check`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: judge token limits, parakh rescore, and the judge data note`. Push.

---

### Task 2: Agent language profiles and the Doctor rule (EC-88, EC-91)

**Files:**
- Modify: `agents/clinic_agent/config.yaml`, `agents/clinic_agent/config.py`, `agents/clinic_agent/__main__.py`, `agents/clinic_agent/bot.py`, `agents/clinic_agent/prompt.py`, `src/parakh/report/build.py` (or `report/metrics.py`)
- Test: `tests/unit/agent/test_config.py`, `tests/unit/agent/test_prompt.py`, `tests/unit/agent/test_bot.py`, `tests/unit/test_report.py`

**Interfaces:**
- `config.yaml` keeps every M3a key, and gains:

  ```yaml
  profiles:
    hi: { stt_language: hi, tts_voice: hi-IN-SwaraNeural }
    kn: { stt_language: kn, tts_voice: kn-IN-SapnaNeural }
    ta: { stt_language: ta, tts_voice: ta-IN-PallaviNeural }
  default_profile: hi
  ```

- `load_config(path=DEFAULT_PATH, profile: str | None = None) -> AgentConfig`.
  - The chosen profile's values fill `stt_language` and `tts_voice`.
  - An unknown profile raises `ValueError`, naming the valid profiles.
- `python -m agents.clinic_agent --profile kn` selects the profile. `agent_info` gains `language` (the profile key) and keeps `stt_model`.
- `system_prompt` adds the sentence: "Always write the word Doctor in full, in every language and script; never abbreviate it as Dr. or डॉ."
- Parakh side, in `build_report`: if `agent_info["language"]` exists and differs from the first part of `scenario.language` (`hi-en` gives `hi`), it adds the warning `agent language <x> does not match scenario language <y>`. The CLI summary prints the warnings that start with `agent language`.

- [ ] **Step 1: Write the failing tests:**
  - `test_profiles_fill_language_and_voice`
  - `test_unknown_profile_raises`
  - `test_prompt_spells_doctor_in_full`
  - `test_agent_info_has_language`
  - `test_language_mismatch_warns` (an `agent_info` with language `hi`, a `kn-en` scenario: the warning is present)
  - `test_language_match_no_warning`
- [ ] **Step 2: Run** chunks 1 and 2. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the four chunks, pyright and ruff. Expected: all pass.
- [ ] **Step 5: Commit** `feat(agent): language profiles and Doctor in full; warn on an agent language mismatch`. Push.

---

### Task 3: Kannada-English and Tamil-English scenario packs

**Files:**
- Create: 6 files in `scenarios/kannada_en/` and 6 in `scenarios/tamil_en/`, named in the tables
- Modify: `tests/unit/test_scenario_pack.py` (parametrise over the three packs)
- Test: `tests/unit/test_scenario_pack.py`

**Interfaces:**
- **Fields.** Every file has:
  - `schema_version: 1`, `domain: clinic`, `clock: "2026-11-19T10:00:00+05:30"`;
  - `agent_speaks_first: true`;
  - a `goal`;
  - `limits: { max_turns: 12, response_timeout_s: 15, call_timeout_s: 180 }`.

  The language is `kn-en` or `ta-en`, and ids end in `-kannada-01` or `-tamil-01`.
- **Dates.** "Naale" (Kannada) and "naalaikku" (Tamil) mean 2026-11-20. "Naadiddu" and "naalai marunaal" mean 2026-11-21. The clinic's doctors, hours and slots are as in M3a.
- **Text rules.** The M3a rules hold:
  - Turn 1 states the intent and the doctor.
  - The last turn confirms and says goodbye.
  - Phone numbers are distinct across all 26 scenarios.
  - `ref` uses digits, no fillers and `doctor`.
  - `en-IN` voices get Roman text only.

  The caller's voice differs from the agent profile's voice (Sapna for Kannada, Pallavi for Tamil).

| `kannada_en/` id | Caller voice | What it tests |
|---|---|---|
| `clinic-book-kannada-01` | kn-IN-GaganNeural | Roman Kannada-English, Dr. Rao naale hattu gante (10:00), phone in English digits |
| `clinic-book-iyer-kannada-01` | kn-IN-GaganNeural | Dr. Iyer for a son, naadiddu sanje naalku gante (16:00) |
| `clinic-numbers-kannada-01` | kn-IN-GaganNeural | Phone in Kannada number words, time hannondu gante (11:00) |
| `clinic-script-kannada-01` | kn-IN-GaganNeural | `say` and `ref` in Kannada script, `ref` with digits |
| `clinic-english-heavy-kannada-01` | en-IN-PrabhatNeural | Mostly English with Kannada fillers (swalpa, aytu, sari) |
| `clinic-bargein-kannada-01` | kn-IN-GaganNeural | Interrupts the read-back (`after_agent_ms: 1500`) to correct the time |

| `tamil_en/` id | Caller voice | What it tests |
|---|---|---|
| `clinic-book-tamil-01` | ta-IN-ValluvarNeural | Roman Tamil-English, Dr. Rao naalaikku kaalaila pathu manikku (10:00), phone in English digits |
| `clinic-book-iyer-tamil-01` | ta-IN-ValluvarNeural | Dr. Iyer for a son, naalai marunaal saayangaalam naalu manikku (16:00) |
| `clinic-numbers-tamil-01` | ta-IN-ValluvarNeural | Phone in Tamil number words, time padhinonnu manikku (11:00) |
| `clinic-script-tamil-01` | ta-IN-ValluvarNeural | `say` and `ref` in Tamil script, `ref` with digits |
| `clinic-english-heavy-tamil-01` | en-IN-PrabhatNeural | Mostly English with Tamil fillers (konjam, seri, paravaayilla) |
| `clinic-bargein-tamil-01` | ta-IN-ValluvarNeural | Interrupts the read-back (`after_agent_ms: 1500`) to correct the time |

- [ ] **Step 1: Write the failing tests.** Parametrise the M3a pack tests over `hinglish`, `kannada_en` and `tamil_en`, and add:
  - `test_kn_ta_packs_have_six_each`
  - `test_language_matches_directory`
  - `test_caller_voice_differs_from_agent_profile_voice`
  - `test_phone_numbers_distinct_across_packs`
  - `test_ref_digits_match_goal_phone` (closes the M3a minor: every 10-digit token in a `ref` equals the phone number in the `goal`)
- [ ] **Step 2: Run** `uv run pytest -q -p no:cacheprovider tests/unit/test_scenario_pack.py`. Expected: FAIL.
- [ ] **Step 3: Write the 12 scenarios.** Run `uv run parakh tts build scenarios/kannada_en scenarios/tamil_en`; edge-tts gets the synthetic text only. Expected: every clip builds and none is silent. Record each clip's duration against its word count in the report.
- [ ] **Step 4: Run** the four chunks. Expected: all pass. Run `uv run parakh budget scenarios/kannada_en scenarios/tamil_en` and record the result.
- [ ] **Step 5: Commit** `feat(scenario): add Kannada-English and Tamil-English clinic packs`. Push.

---

### Task 4: Language-aware normaliser for Kannada and Tamil

**Files:**
- Create:
  - `src/parakh/score/scripts.py` (per-script romanisers);
  - `src/parakh/score/tamil.py` (the Tamil romaniser);
  - `tests/golden/normalizer_pairs_kn.yaml`, `tests/golden/normalizer_pairs_ta.yaml`;
  - `tests/unit/test_normalize_kn_ta.py`.
- Modify:
  - `src/parakh/score/normalize.py`, `src/parakh/score/numbers.py`, `src/parakh/score/wer.py`;
  - `src/parakh/report/build.py`, `src/parakh/report/diff.py`, `src/parakh/report/rescore.py`.

**Interfaces:**
- `normalize(text: str, language: str = "hi-en") -> Normalized`. The language is one of `hi-en`, `hi`, `en`, `kn-en`, `ta-en`.
  - `loose_wer`, `loose_cer` and `conversation_wer` gain `language: str = "hi-en"`.
  - Every caller passes the scenario or report language: `build_report`, `diff.py` and `rescore_report`.
  - `strict_tokens` is unchanged.
- **Script ranges.** Devanagari keeps its rules, including the final-schwa rule. Kannada is U+0C80 to U+0CFF; Tamil is U+0B80 to U+0BFF. Numerals ೦ to ೯ and ௦ to ௯ give ASCII digits in every language.
- **Kannada** goes to ITRANS, then is folded to ASCII (NFD, combining marks removed: `è` becomes `e`, `ò` becomes `o`). Anusvara follows the Devanagari rule: `n`, or `m` before p, b or m. The final-schwa rule does not apply.
- **Tamil (`tamil.py`)** has `romanize_tamil(word: str) -> str`, a table of the 12 vowels, 18 consonants, 5 grantha letters and ஃ, with these contextual rules:
  - A stop is voiced after a nasal: ம்ப is mb, ந்த is nd, ங்க is ng, ஞ்ச is nj.
  - A stop is unvoiced when doubled and at word start.
  - A single stop between vowels softens: க is g, ச is s, ட is d, த is dh, ப is b.
  - ற்ற is tr, ன்ற is ndr, ழ is zh, ள is l, ன and ண are n.

  These are the common Tamil pronunciation rules. Pin each with a test pair, for example எனக்கு gives enakku, ரொம்ப gives romba, நன்றி gives nandri, வணக்கம் gives vanakkam, பழம் gives pazham.
- **Loose key by language.**
  - `ta-en` adds, on every token, b to p, d to t, g to k, dh to t, th to t, zh to l, sh to s, and ch to s. Tamil script does not mark voicing, so Roman spellings differ there.
  - `kn-en` adds nothing beyond the shared rules.
  - The Hinglish `VARIANTS` apply only to `hi-en` and `hi`. Kannada and Tamil get their own small variant tables.
- **Number words (`numbers.py`)** are keyed by loose key, per language:
  - Kannada 0 to 100: sonne, ondu, eradu, mooru, naalku, aidu, aaru, elu, entu, ombattu, hattu ... ippattu, nooru.
  - Tamil 0 to 100: poojyam, onnu or ondru, rendu or irandu, moonu or moondru, naalu or naangu, anju or ainthu, aaru, ezhu, ettu, onbadhu, pathu ... irubadhu, nooru.
  - Both in Roman and native script. English number words are included for both, and "double" and "triple" apply.
  - A table collision is an import error, as in M3a.
- **Golden files**, in the M3a format (the third element is a group tag, plus `known_gaps`). Each holds at least 80 pairs:

  | Group | Minimum |
  |---|---|
  | `script` (native script against Roman) | 30 |
  | `loanword` | 15 |
  | `variant` | 10 |
  | `number` | 15 |
  | `no_match` | 10 |

  Pairs come from the Task 3 scenario vocabulary. Mark them `# textbook`; Task 10 adds observed ones.

- [ ] **Step 1: Write the failing tests.** These go in `tests/unit/test_normalize_kn_ta.py`:
  - `test_golden_kn` and `test_golden_ta` (match and no-match, parametrised), plus `test_known_gaps_kn_ta` (strict xfail);
  - `test_native_numerals`: "ಫೋನ್ ೯೮೪೫" (kn-en) gives `["fon", "9845"]`, and the same holds for Tamil numerals;
  - `test_tamil_letters_romanise`: the five pinned words above;
  - `test_tamil_voicing_rules`: one pair per rule;
  - `test_kannada_no_schwa_drop`: ಇಲ್ಲ gives `ila` (double collapsed), not `il`;
  - `test_numbers_by_language`: "ondu" is `1` in kn-en and stays `ondu` in hi-en; "rendu" is `2` only in ta-en;
  - `test_property_ascii_tokens_kn_ta`: Hypothesis over the Kannada and Tamil blocks, Latin, digits and punctuation; tokens match `^[a-z0-9]+$`, normalising is idempotent, and each text matches itself;
  - `test_hinglish_unchanged`: for every M3a golden pair, `normalize(x)` equals `normalize(x, "hi-en")`, and both equal the M3a tokens.
- [ ] **Step 2: Run** `uv run pytest -q -p no:cacheprovider tests/unit/test_normalize_kn_ta.py tests/unit/test_normalize.py`. Expected: the new tests FAIL, and the M3a tests pass.
- [ ] **Step 3: Implement.** Keep `normalize.py` under about 300 lines by moving the script code to `scripts.py` and `tamil.py`.
- [ ] **Step 4: Run** the four chunks, pyright, ruff and the coverage command. Expected: all pass, and `parakh.score` coverage is 85 % or more.
- [ ] **Step 5: Commit** `feat(score): normalise Kannada and Tamil, with per-language numbers and golden sets`. Push.

---

### Task 5: Heavy-model lock and local STT in the agent (EC-04, D10)

**Files:**
- Create: `src/parakh/heavy.py`
- Modify:
  - `agents/clinic_agent/reset.py` (the reset as a mixin for both STT services);
  - `agents/clinic_agent/bot.py`, `agents/clinic_agent/__main__.py`, `agents/clinic_agent/config.yaml`;
  - `pyproject.toml` (agent group `pipecat-ai[websocket,silero,groq,whisper]==1.16.0`), `uv.lock`;
  - `src/parakh/cli.py` or `src/parakh/cli_report.py` (the `heavy` command);
  - `tools/check_keys.py`.
- Test: `tests/unit/test_heavy.py` (new), `tests/unit/agent/test_reset.py`, `tests/unit/agent/test_bot.py`, `tests/unit/agent/test_main.py`, `tests/unit/test_check_keys.py`

**Interfaces:**
- **The lock.** `parakh.heavy` has:
  - `LOCK_PATH = Path(".cache/locks/heavy-model.lock")`;
  - `class HeavyModelBusy(RuntimeError)`;
  - `@contextmanager def heavy_model_lock(owner: str, path: Path = LOCK_PATH) -> Iterator[None]`.

  How it works:
  - It creates the file exclusively (`os.open` with `O_CREAT | O_EXCL`) and writes `{"pid", "owner", "started"}` as JSON.
  - If the file exists and its PID is alive (`psutil.pid_exists`), it raises `HeavyModelBusy("<owner> (pid <n>) holds the heavy-model lock since <started>")`.
  - If the PID is gone, or the file is unreadable, it replaces the lock.
  - On exit it deletes the file only if it still holds its own PID.
- **Running a command under the lock.** `def run_locked(owner: str, argv: Sequence[str]) -> int` runs a subprocess under the lock and returns its exit code. The CLI is `parakh heavy run OWNER -- CMD...`, and `HeavyModelBusy` gives exit 2.
- **Agent local STT.** `--stt groq|local`, default `groq`.
  - With `local`, the agent first takes `heavy_model_lock("clinic-agent local STT")` for its lifetime. It then uses a `ClinicLocalSTT(WhisperSTTService)` with the same per-call reset as `ClinicSTT`, through a shared mixin: model `small`, `device="cpu"`, `compute_type="int8"`, and the profile's language.
  - `agent_info.stt_model` becomes `local:faster-whisper-small`.
  - With `local`, the agent does not need a Groq STT model in `verify_models`. It still needs the LLM.
- **Tests.** They must not download the model: they check service construction and settings only. Read the installed `pipecat/services/whisper/stt.py` to confirm where the model loads.
- **Keys.** `tools/check_keys.py` reports `HF_TOKEN` as set or not set (optional), never its value.

- [ ] **Step 1: Write the failing tests:**
  - `test_lock_acquire_and_release`
  - `test_live_holder_blocks` (the holder is the test's own PID, which is alive)
  - `test_stale_lock_taken_over` (a PID that does not exist)
  - `test_release_keeps_foreign_lock`
  - `test_unreadable_lock_replaced`
  - `test_run_locked_returns_exit_code`
  - `test_heavy_run_busy_exits_2`
  - `test_local_stt_selected` (`stt_model` is `local:faster-whisper-small`, with the language from the profile)
  - `test_local_stt_takes_heavy_lock`
  - `test_local_stt_skips_groq_stt_check`
  - `test_reset_mixin_on_both_services`
  - `test_hf_token_optional`
- [ ] **Step 2: Run** chunks 1 and 2. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv sync --all-groups`, and confirm that `faster_whisper` imports.
- [ ] **Step 4: Run** the four chunks, pyright and ruff. Expected: all pass.
- [ ] **Step 5: Commit** `feat: heavy-model lock and a local faster-whisper STT mode for the clinic agent`. Push.

---

### Task 6: Real recordings in Parakh (D10, EC-13, EC-60)

**Files:**
- Create: `src/parakh/tts/recordings.py`, `src/parakh/caller/realdata.py`, `src/parakh/batch.py`
- Modify:
  - `src/parakh/run.py` (moves `preflight`, `run_batch`, `_batch_reports` and `_write_comparison` to `batch.py`);
  - `src/parakh/caller/driver.py` (a hook of a few lines into `realdata.py`);
  - `src/parakh/report/model.py`, `src/parakh/report/build.py`, `src/parakh/report/templates/report.html.j2`;
  - `src/parakh/judge/runner.py`;
  - `src/parakh/cli.py`, `src/parakh/cli_report.py`;
  - `docs/runbooks/` (a new `record-real.md`).
- Test: `tests/unit/test_recordings.py` (new), `tests/unit/test_realdata.py` (new), `tests/integration/test_cli_run.py`, `tests/unit/test_run.py`, `tests/unit/judge/test_runner.py`

**Interfaces:**
- **Recordings.** `parakh.tts.recordings` has:
  - `REAL_ROOT = Path("data/real")`;
  - `def recording_paths(scenario: Scenario, root: Path = REAL_ROOT) -> list[Path | None]`, one per turn, from `turn-<NN>.*`;
  - `def load_recorded_clips(scenario, root=REAL_ROOT) -> list[CallerClip]`, which decodes with ffmpeg to 16 kHz mono, trims and sets `speech_end_ms`, the same way TTS clips are prepared, caching the decoded WAV next to the original as `.turn-<NN>.16k.wav`. It raises `RecordingError` naming the file for a missing, undecodable or silent turn.
  - `def recording_status(scenario, root=REAL_ROOT) -> RecordingStatus`, which reports each turn's say text, its expected file name and whether it was found, and lists unused files.
- **Real runs.** `run_scenario(..., real: bool = False)`. With `real=True`:
  - The clips come from `load_recorded_clips`. No edge-tts call is made for caller turns; babble for a noise preset still uses its synthetic text.
  - A new `check_local_agent_url(url: str) -> None` in `parakh.transport.ws` runs after `check_agent_url`. It raises `ValueError("real recordings need an agent on this machine (127.0.0.1, localhost or ::1), got <redacted url>")` unless the host is loopback.
  - The report gets `real_audio: True` (a new `Report.real_audio: bool = False` field), and the HTML shows the banner "Real recording: audio stays on this machine".
  - The judge returns `skipped`, reason `real recording (D20)`, before any request.
- **Driver gate.** `parakh.caller.realdata` has `class RealDataGate`. The driver consults it before every caller frame that holds recorded audio, and sends silence until the gate opens.
  - The gate opens when an `agent_info` event arrives with `stt_model` starting `local:`.
  - It refuses when `stt_model` lacks the prefix, or when no `agent_info` arrives within `REAL_INFO_TIMEOUT_S = 5.0` of connecting.
  - A refusal ends the call with status `real_data_refused` and a warning naming the reason.
  - `driver.py` must stay at or under 350 lines: keep the hook to a few lines.
- **Run-module split.** `run.py` stays under 350 lines because `preflight`, `run_batch`, `_batch_reports` and `_write_comparison` move to `parakh.batch`.
  - `parakh.run` re-exports them.
  - `batch.py` calls `run.run_scenario` through the module attribute, so existing tests that patch `parakh.run.run_scenario` keep working.
- **CLI.**
  - `parakh run ... --real` passes `real=True`, and preflight loads the recordings first.
  - `parakh recordings status SCENARIO...` prints one line per turn, `turn 01: found|MISSING  data/real/<id>/turn-01.*  "<say>"`, and lists unused files. It exits 0 when everything is found, and 2 otherwise.
- **Runbook `docs/runbooks/record-real.md`.** What to read, how to name files, how to check them with `recordings status`, and how to run with `--stt local` and `--real`. It also states that the audio never leaves the laptop and that `data/real/` is gitignored.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_recordings.py (ffmpeg-made fixtures in a dir with a space)
def test_recordings_decode_any_format(tmp_path):   # 48 kHz stereo .m4a (or .wav if m4a encoder missing): 16 kHz mono clip
def test_missing_or_silent_recording_fails_before_call(tmp_path):   # RecordingError names the file
def test_status_lists_unused_files(tmp_path):      # turn-09.wav for a 4-turn scenario: listed unused
# tests/unit/test_realdata.py
def test_gate_opens_on_local_stt():
def test_real_run_refuses_remote_stt():            # stt_model "whisper-large-v3-turbo": refuse, reason names it
def test_real_run_refuses_without_agent_info():    # fake clock past 5 s: refuse
# tests/unit/test_run.py
async def test_real_run_refuses_remote_url(tmp_path):   # ws://10.0.0.5:8765 with real=True: ValueError, nothing written
async def test_real_run_skips_judge(tmp_path):
# tests/integration/test_cli_run.py
async def test_real_run_sends_no_audio_to_remote_stt_agent(...):
    # fake agent sends agent_info stt_model "whisper-large-v3-turbo": status real_data_refused, exit 2,
    # behaviour.received holds only silent frames (no frame above -45 dBFS)
async def test_real_run_completes_with_local_stt_agent(...):   # agent_info stt_model "local:x": completed
```

- [ ] **Step 2: Run** chunks 1 and 4. Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above. The fake agent gains an `agent_info` override if it lacks one.
- [ ] **Step 4: Run** the four chunks, pyright and ruff. Run `wc -l src/parakh/run.py src/parakh/batch.py src/parakh/caller/driver.py`. Expected: all pass, and every file is at or under 350 lines.
- [ ] **Step 5: Commit** `feat: real recordings with a local-only gate, recordings status, and the run module split`. Push.

---

### Task 7: The Parler benchmark tool (isolated environment)

**Files:**
- Create:
  - `tools/parler_bench/pyproject.toml`, `tools/parler_bench/uv.lock`, `tools/parler_bench/README.md`;
  - `tools/parler_bench/parler_bench/__init__.py`, `__main__.py` and `metrics.py` (no torch import);
  - `tools/parler_bench/sentences.yaml`;
  - `tools/whisper_check.py` (main env).
- Modify: `pyproject.toml` (pyright `exclude` gains `tools/parler_bench`), `.gitignore` (`tools/parler_bench/.venv/`, `tools/parler_bench/out/`)
- Test: `tests/unit/test_parler_metrics.py` (new; imports `tools.parler_bench.parler_bench.metrics` only), `tests/unit/test_whisper_check.py` (new)

**Interfaces:**
- **Project.** `tools/parler_bench/pyproject.toml` is its own uv project, Python 3.11. Its dependencies are:
  - `parler-tts @ git+https://github.com/huggingface/parler-tts.git@<commit>`, pinned to the full SHA of the current default branch;
  - `torch` from an explicit CPU index (`https://download.pytorch.org/whl/cpu`, through `[tool.uv.sources]` and `[[tool.uv.index]]` with `explicit = true`);
  - `transformers` at whatever parler-tts requires;
  - `soundfile` and `psutil`.

  Run `uv lock --project tools/parler_bench` and commit the lock.
- **The benchmark.** `uv run --project tools/parler_bench python -m parler_bench --out tools/parler_bench/out` loads `ai4bharat/indic-parler-tts` with `HF_TOKEN` from `.env`, which is read by the tool and never printed. It synthesises `sentences.yaml`: 2 Hindi, 2 Kannada, 2 Tamil and 1 English sentence, synthetic clinic lines, each with a speaker description naming a recommended speaker for its language from the model card. It writes one WAV per sentence plus `bench.json`:
  - per sentence: language, seconds of audio, seconds of synthesis, RTF;
  - the warm-up time;
  - peak RSS in MB from psutil;
  - torch, parler-tts and model revisions.

  The first sentence is a warm-up and is excluded from the RTF.
- **Metrics.** `metrics.py` has `rtf(synth_s, audio_s) -> float`, `summarise(rows) -> dict` (mean and max RTF, peak RSS) and `passes(summary, wer_by_lang) -> tuple[bool, list[str]]`. The thresholds are RTF 10 or less, RSS 6000 MB or less, and loose WER 25 % or less per language (planning ruling 6). The second item lists the reasons for a fail.
- **Whisper check.** `tools/whisper_check.py OUT_DIR` runs in the main env. For each WAV with its text and language from `bench.json`, it calls Groq Whisper (`whisper-large-v3-turbo`, with the language hint). It goes through `remote_call("groq", real=False)` and `send_with_backoff`, and the key comes from `.env`. It computes loose WER with `normalize(text, language)`, writes `wer.json` and prints the pass or fail verdict with `passes`.

- [ ] **Step 1: Write the failing tests.**
  - For `metrics`: `test_rtf`, `test_summarise_excludes_warmup`, and `test_passes_thresholds`, which covers a fail on each threshold with its reason.
  - For the Whisper check, with `httpx.MockTransport` and no network or key: `test_whisper_check_scores_by_language` and `test_whisper_check_refuses_without_key`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Do not run the benchmark, which needs the token and a 3.75 GB download: the controller runs it in Task 8. Verify that `uv lock --project tools/parler_bench` resolves and that the main `uv sync --locked --all-groups` is unchanged.
- [ ] **Step 4: Run** the four chunks, pyright and ruff. Expected: all pass, and the main lock does not contain torch.
- [ ] **Step 5: Commit** `feat(tools): an isolated Indic Parler-TTS benchmark and a Groq Whisper intelligibility check`. Push.

---

### Task 8: Run the Parler benchmark and decide (controller-run)

The controller runs this task. It needs Yatin's Hugging Face token and a 3.75 GB download. Stop on any payment prompt.

**Files:**
- Create: `docs/research/2026-11-2x-parler-benchmark.md` (the date of the run)

- [ ] **Step 1: Human step.**
  - Yatin accepts the model terms on `https://huggingface.co/ai4bharat/indic-parler-tts` while logged in. Approval is automatic, and no card is asked.
  - He creates a read token and adds it to `.env` as `HF_TOKEN`.
  - The controller checks it with `uv run python -m tools.check_keys`.
- [ ] **Step 2: Preflight.**
  - No agent with `--stt local` is running.
  - Free memory is at least 7 GB; close Chrome if needed.
  - Run `uv sync --project tools/parler_bench` (it downloads torch CPU).
- [ ] **Step 3: Run.** Run the benchmark under the lock: `uv run parakh heavy run parler-bench -- uv run --project tools/parler_bench python -m parler_bench --out tools/parler_bench/out`. Then run `uv run python -m tools.whisper_check tools/parler_bench/out`, which makes 7 Groq STT requests on synthetic audio.
- [ ] **Step 4: Write the research note.**
  - Hardware and free memory.
  - Each sentence's RTF.
  - Peak RSS.
  - Each language's WER.
  - Listening notes on 3 clips.
  - The verdict against the three thresholds.
  - What adoption would cost: build time for the three packs, disk, and memory.

  Commit `docs(research): benchmark Indic Parler-TTS on the laptop CPU`.
- [ ] **Step 5: Rule.** If the benchmark passes, Task 9 runs. If it fails, record `Ruling: Parler not adopted — <failed thresholds>`, add the spec backlog line "Indic Parler-TTS as an offline engine on faster hardware (benchmark: <link>)", skip Task 9, and go to Task 10.

---

### Task 9: Parler as an offline TTS engine (only if Task 8 passed)

**Files:**
- Create: `src/parakh/tts/parler.py`, `tools/parler_bench/parler_bench/synth.py`
- Modify: `src/parakh/scenario/model.py` (`CallerVoice.engine`), `src/parakh/tts/cache.py`, `src/parakh/cli.py` (`tts build --engine`), `src/parakh/run.py` or `batch.py` (engine per scenario)
- Test: `tests/unit/test_parler_engine.py` (new), `tests/unit/test_tts.py`, `tests/unit/test_scenario.py`

**Interfaces:**
- `CallerVoice.engine: Literal["edge-tts", "parler"] = "edge-tts"`. For `parler`, `voice` is a speaker name from the model card, such as `Rohit`.
- `class ParlerEngine` implements `TTSEngine`, with `name = "parler"` and `version` set to the tool's pinned parler-tts commit plus the model revision.
  - `synthesize` batches the scenario's turns. It runs the tool's `synth` entry point (`uv run --project tools/parler_bench python -m parler_bench.synth --in <json> --out <dir>`) under `heavy_model_lock("parler tts build")`.
  - It returns WAV bytes, which the cache decodes like MP3.
  - The text is synthetic and the model runs locally, so `remote_call` is not needed.
- The cache key already includes the engine name and version, so Parler and edge-tts clips never collide.
- `parakh tts build PATHS --engine parler` builds only scenarios whose `caller.engine` is `parler`. `parakh run` uses the cache and never starts Parler mid-batch: a missing Parler clip is a preflight error that says to run `tts build` first.

- [ ] **Step 1: Write the failing tests.** Replace the subprocess with a fake that writes a sine WAV: `test_parler_engine_runs_under_lock`, `test_parler_cache_key_differs`, `test_run_requires_prebuilt_parler_clips`, `test_engine_field_defaults_to_edge`.
- [ ] **Step 2: Run** chunk 1. Expected: FAIL.
- [ ] **Step 3: Implement.** Add one Parler variant of `clinic-book-hinglish-01` as `scenarios/hinglish/clinic-book-parler-hinglish-01.yaml`. It is the D9 sample whose audio may be published.
- [ ] **Step 4: Run** the four chunks, pyright and ruff. Expected: all pass.
- [ ] **Step 5: Commit** `feat(tts): Indic Parler-TTS as an offline engine`. Push.

---

### Task 10: Live runs, real recordings and the M3b runbook (controller-run)

The controller runs this task. The rules:
- Never print the keys.
- Stop on 402, 429 or `rate_limited`.
- Check free memory before every batch.
- Run batches in the foreground, in groups of at most 5 scenarios.
- Keep only the agent in the background.

**Files:**
- Create: `docs/runbooks/run-m3b.md`
- Modify: `tests/golden/normalizer_pairs_kn.yaml`, `tests/golden/normalizer_pairs_ta.yaml` (observed pairs), and `src/parakh/score/*` only for rules that the observed pairs require

- [ ] **Step 1: Kannada.**
  - Run `uv run parakh budget scenarios/kannada_en scenarios/tamil_en`.
  - Start `uv run --group agent python -m agents.clinic_agent --profile kn`.
  - Run `uv run parakh run scenarios/kannada_en --agent ws://127.0.0.1:8765` in two batches.
  - Stop the agent.
- [ ] **Step 2: Tamil.** Do the same with `--profile ta` and `scenarios/tamil_en`.
- [ ] **Step 3: Real recordings.**
  - Yatin records at least 4 Hinglish scenarios: `clinic-book`, `clinic-book-iyer`, `clinic-hindi-numbers` and `clinic-correction`, following `docs/runbooks/record-real.md`. The controller checks them with `uv run parakh recordings status scenarios/hinglish/<file>`.
  - Start `uv run --group agent python -m agents.clinic_agent --profile hi --stt local`. It holds the heavy-model lock.
  - Run each with `uv run parakh run <scenario> --agent ws://127.0.0.1:8765 --real`, under `clean` and `phone`.
  - Expected: completed runs with `real_audio: true` and the judge skipped. The agent log shows local STT and no Groq STT request.
  - If the clips are not ready, record "real set pending Yatin's recordings" and continue. The milestone then stays open until they are run.
- [ ] **Step 4: Parler.** If Task 9 ran, run `uv run parakh tts build scenarios/hinglish/clinic-book-parler-hinglish-01.yaml --engine parler` while no local-STT agent runs, then one run against the Hindi agent.
- [ ] **Step 5: Normaliser feedback.** Align the live Kannada and Tamil turns word by word, as in M3a. Add observed spelling and script variants as `must_match` (mark them `# observed`) or as `known_gaps`. Change a rule only when all golden files still pass. Rescore the M3b runs with `parakh rescore`. Commit `test(score): add golden pairs observed in the M3b runs`.
- [ ] **Step 6: Judge spot check.** Read 4 Kannada and 4 Tamil judged calls. Record whether the judge lowered language match for Kannada-English or Tamil-English replies in the caller's register; if it did, flag it in the runbook for a `judge-v2` rubric. Yatin confirms later.
- [ ] **Step 7: Write `docs/runbooks/run-m3b.md`.**
  - The kn and ta packs.
  - The agent profiles and `--stt local`.
  - The real-recording procedure, linked to `record-real.md`.
  - Measured Groq requests and tokens.
  - A results table per run (status, loose and strict WER as run and rescored, latency, judge mean).
  - The real-run results, compared with the same scenarios' synthetic runs.
  - The Parler verdict.
  - Troubleshooting.
  - The run log.

  Commit `docs(runbooks): add the M3b runbook and log the runs`. Push.

---

### Task 11: Spec, register, README, docs index and knowledge graph

**Files:**
- Modify: `docs/superpowers/specs/2026-11-15-parakh-design.md`, `README.md`, `docs/README.md`, `docs/kg/graph.yaml`, `docs/kg/README.md` (generated), `docs/runbooks/api-keys.md` (`HF_TOKEN`)

- [ ] **Step 1: Spec.** Update the "Updated:" line, then the sections below.
  - **6.2:** recordings as a clip source; Parler as built, or as benchmarked and not adopted.
  - **6.5:** agent profiles, `--stt local`, Doctor in full.
  - **6.7:** the language-aware normaliser (per-script romanisers, Tamil rules, per-language numbers and loose keys, golden files), and the judge's token limits.
  - **6.8:** judge tokens.
  - **6.9:** `real_audio`, the mismatch warning.
  - **6.10:** `rescore`, `recordings status`, `run --real`, `heavy run`.
  - **7:** `tools/parler_bench`, `data/real`.
  - **10:** M3b met (or partly met, with what remains), with the numbers from `run-m3b.md`.
  - **11:**
    - Update EC-04, EC-13, EC-15, EC-40 to EC-44, EC-60, EC-63, EC-88 and EC-91.
    - Add new rows from EC-92 for what Task 10 found.
  - **12:** D18 to D21, from the planning rulings.
  - **13:** update the backlog.
- [ ] **Step 2: README.** Cover the languages, real recordings and their local-only guarantee, Parler, the judge data note, and the status.
- [ ] **Step 3: Docs index and knowledge graph.**
  - Index: the M3b plan, `run-m3b.md`, `record-real.md` and the Parler research note.
  - Knowledge graph: nodes `heavy_lock`, `recordings`, `parler_bench` and, if adopted, `parler_engine`. Update `normalizer`, `test_agent` and `m3`. Use the existing ids.
  - Run `uv run python -m tools.kg_render`.
- [ ] **Step 4: Run** the docs tests and `kg_render --check`. Expected: pass.
- [ ] **Step 5: Commit** `docs: record M3b in the spec, README and knowledge graph`. Push, and check CI.

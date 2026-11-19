# M2 Degradation and Interruptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `parakh run <scenario|dir> --agent ws://... --preset all` drives the clinic agent through all five degradation presets, scores barge-in stop latency on turns that interrupt the agent, and writes a comparison page across presets (spec section 10, M2), after first closing the 15 "fix at the start of M2" findings of the M1 review.

**Architecture:** A new pure numpy/scipy package `parakh.degrade` holds the stages (peak normalisation, noise at an SNR, clipping, 300-3400 Hz band-pass, 8 kHz, G.711 mu-law, packet loss), seeded per scenario, preset and turn, and the five presets as packaged YAML config. Before the call, `parakh.caller.line` renders every caller turn and a looping line "bed" (the noise heard between turns) through the preset, at the agent's rate, so the real-time driver only streams prepared 20 ms frames. The turn machine gains scheduled barge-ins; the playback clock gains reply onsets and a flush on the agent's interruption frame; `parakh.score.bargein` scores stop latency and false barge-ins from `events.jsonl` after the call; `parakh.report.compare` turns a batch of reports into `compare.html`.

**Tech Stack:** Python 3.11, uv, numpy, scipy (`signal.butter`, `sosfiltfilt`, `resample_poly`), pydantic v2, Typer, Jinja2, edge-tts (caller and babble voices), ffmpeg (decode, and the mu-law cross-check in tests), pipecat-ai 1.16.0, loguru (to silence Pipecat's import banner), pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-11-15-parakh-design.md` (sections 6.3, 6.4, 6.7, 6.8, 6.9, 6.10, 8, 10, and the M2 rows of 11: EC-22 to EC-26, EC-37, EC-64). Findings to fix first: `docs/reviews/2026-11-17-m1-review.md`, section "Fix at the start of M2".

## Global Constraints

- Free only, no card. Synthetic data only to remote APIs: scenario text and babble text are synthetic, so edge-tts and Groq receive only synthetic content. Stop on HTTP 402 or 429, or on any card or payment prompt.
- No Calibrate code (CC-BY-SA). No code copied from Pipecat, ffmpeg or any G.711 reference implementation; write the mu-law codec from the G.711 algorithm and cross-check it against ffmpeg in tests.
- No `audioop` (deprecated, removed in Python 3.13). The degrader uses numpy and scipy only.
- Noise sources in the repository are synthetic (white, pink, brown) or babble built from Parakh's own TTS clips of synthetic text (EC-64). No noise dataset files are committed or downloaded.
- Deterministic: the same scenario id, preset and turn index give the same bytes (spec 6.3, EC-26). Seeds come from sha256, never from `hash()` (salted per process) or the clock.
- `pipecat-ai==1.16.0` exactly. Core Parakh imports Pipecat only through `parakh.transport.codec`.
- Caller audio is generated at 16 kHz mono int16 and sent in 20 ms frames at the agent's rate. Supported rates, for `--agent-rate` and for agent audio: `SUPPORTED_RATES = (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000)`.
- Thresholds carried from M1: "agent speaking" above -45 dBFS (EC-27), 800 ms end-of-turn silence (EC-36), 1000 ms caller-first silence (EC-35), timing unreliable above 30 ms p99 jitter (EC-02). New in M2: reply onset gap and stop gap 200 ms, `did_not_yield` after 2000 ms (spec 6.4, EC-37), false barge-in grace 500 ms after a caller turn ends.
- Presets (spec 6.3): `clean`; `phone` = band-pass 300-3400 Hz, 8 kHz, mu-law; `phone_noisy` = phone + babble at 10 dB SNR; `phone_lossy` = phone + 3 % packet loss; `bad_line` = phone + pink noise at 5 dB SNR + 5 % loss in bursts (mean 3 frames) + hard clip at -10 dBFS. Comparison order is the order above.
- Exit codes: 0 completed; 1 `agent_hung_up_early`; 2 every other status, `timing_unreliable`, `interrupted` (Ctrl+C), and errors before a call starts. A batch exits with the highest code of its runs. Barge-in results do not change the exit code (thresholds arrive in M4, D12).
- `pathlib` everywhere; every test that touches paths uses a directory whose name contains a space (EC-07). Run ids and batch ids are 8 hex characters (`secrets.token_hex(4)`).
- Unit and integration tests need no network and no keys. Tests that need ffmpeg run in CI; they are not skipped. pytest runs with `filterwarnings = ["error"]`; clear `__pycache__` before the final gate of a task.
- Line budget: no source file above about 350 lines (`driver.py` is split in Task 1).
- Coverage target 85 % on `parakh.degrade`, `parakh.score` and `parakh.caller` (spec 8); report it in the task report (`uv run pytest --cov=parakh.degrade --cov=parakh.score --cov=parakh.caller -q`).
- No emoji anywhere. Conventional Commits. Commit and push to `main` after each task.
- Ruling carried from planning: `phone_lossy` is phone plus loss, without noise, so each preset adds one factor and the comparison can attribute a change to it. `bad_line` uses pink noise as the spec's "street-like" noise.
- Ruling carried from planning: SNR is set and measured at the mixing point, on 16 kHz audio, before the telephone stage. Band-limiting removes some noise energy below 300 Hz, so the SNR the agent hears can be higher; the report states where SNR is measured.
- Ruling carried from planning: the noise level is set once per call from the speech-active RMS of all of the call's clips together, so the line has one steady noise floor during turns and between them, as a real line does. Each turn's measured SNR is reported.
- Ruling carried from planning: one repeatable `--preset` option (plus `all`) on `run` and `budget`, instead of the spec's `--presets`; spec 6.10 is updated in Task 12.
- Ruling carried from planning: the spec's optional user-supplied noise files (6.3) and user-defined presets go to the backlog. M2 ships the five packaged presets and synthetic or own-TTS noise only; Task 12 notes it in the spec.

## Review Focus

1. An agent at a rate other than 16000 Hz (8000 or 24000) with a phone preset: every sent frame is exactly `rate / 50` samples, each turn has the same number of frames as its clean clip, and the speech-end frame index is unchanged. Tests: Task 7 `test_line_frames_at_agent_rate`, Task 2 `test_8khz_wire_call`.
2. A noise preset against an agent whose VAD reacts to the noise bed: the call still runs, the agent's triggers outside caller turns become false barge-ins, and they are not mistaken for barge-in stops. Tests: Task 9 `test_false_barge_in_outside_turns`, Task 7 `test_noise_preset_call_completes`.
3. A barge-in turn where the agent's reply ends before `after_agent_ms`: the turn plays as a normal turn and the report says `agent_finished_first`, with no stop latency. Tests: Task 8 `test_barge_in_missed_short_reply`, Task 9 `test_agent_finished_first`.
4. A batch where one run fails (agent unreachable) or the user presses Ctrl+C: the remaining runs still run (or, on Ctrl+C, stop), the comparison page is written for every run that has a report, the failed run shows its status, and the exit code is 2. Tests: Task 10 `test_batch_continues_after_failed_run`, `test_batch_interrupt_writes_compare_for_finished_runs`.
5. A silent or near-silent turn under a noise preset (EC-24): that turn gets `snr_db: null` and the call runs; a scenario whose clips are all silent fails before the call with a message, exit 2. Tests: Task 7 `test_silent_turn_gets_null_snr`, `test_all_silent_noise_preset_raises`; Task 6 `test_degrade_silent_clip_with_noise_exits_2`.

---

### Task 1: Receive path hardening and the driver split

M1 review items: T4 RecursionError, T9 agent rate and stereo, T9 receive loop yield, T9 driver size, T14 `PIPECAT_VERSION`, T15 transcript twins, Final Pipecat banner.

**Files:**
- Create: `src/parakh/caller/events.py`
- Modify: `src/parakh/caller/driver.py`, `src/parakh/transport/codec.py`, `src/parakh/audio.py`, `agents/clinic_agent/bot.py`, `pyproject.toml`, `uv.lock`
- Test: `tests/unit/test_events.py` (new), `tests/unit/test_codec.py`, `tests/unit/test_driver.py`, `tests/unit/test_cli.py`, `tests/unit/agent/test_bot.py` (or the existing agent test module that covers `bot.py`)

**Interfaces:**
- Produces: `parakh.audio.SUPPORTED_RATES: tuple[int, ...] = (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000)`.
- Produces in `parakh.caller.events`: `agent_pcm(audio: AgentAudio) -> PCM` (moved from the driver: rate must be in `SUPPORTED_RATES`, channels 0 or 1 are mono, 2 is downmixed by averaging each sample pair with rounding, any other count or an odd byte count or a stereo frame with an odd sample count is a `ProtocolError`); `agent_error_text(msg: RtviMessage) -> str` (moved from `_agent_error`, same text); `@dataclass(frozen=True) class Mapped: kind: str | None; fields: dict[str, Any]; warning: str | None = None; agent_info: dict[str, Any] | None = None; bot_stopped: bool = False; interruption: bool = False`; `map_event(event: AgentEvent, repeats: RtviRepeats) -> Mapped` for every event except `AgentAudio`.
- `map_event` keeps the M1 event kinds and fields exactly (`bot_output`, `caller_transcript`, `agent_interruption`, `rtvi_repeat`, `agent_info`, `bot_started`, `bot_stopped`, `agent_metrics`, `rtvi_unknown`; an RTVI `error` gives `kind=None` and a `warning`) and adds `user_started` for RTVI `user-started-speaking` and `user_stopped` for `user-stopped-speaking` (Task 9 consumes `user_started`).
- `RtviRepeats.is_repeat(event: RtviMessage | AgentTranscription) -> bool`: a protobuf `TranscriptionFrame` (final, its own `timestamp`) is one more transcript source. A transcript is a twin only of the message just before it, from a different source or type, with equal (text, final, timestamp); once a twin is found, the pair is consumed, so the next message can never be a twin of either.
- The driver's receive loop yields to the event loop (`await asyncio.sleep(0)`) after each received event.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_codec.py
def test_deeply_nested_json_is_protocol_error():
    # frame.message.data = "[" * 100_000: decode_frame raises ProtocolError, not RecursionError
def test_repeated_haan_without_timestamps_is_kept():
    # user-input "haan", user-transcription "haan", user-input "haan", user-transcription "haan",
    # all final, no timestamp: is_repeat gives [False, True, False, True]
def test_protobuf_transcription_twin_of_rtvi_is_repeat():
    # AgentTranscription("haan", "u", "2026-11-19T10:00:01") then user-input with the same
    # text, final True and timestamp: second is a repeat

# tests/unit/test_events.py
def test_stereo_is_downmixed():          # [100, 300, -50, -150] stereo -> [200, -100]
@pytest.mark.parametrize("rate", [0, 16001, 96000])
def test_unsupported_agent_rate_is_protocol_error(rate):   # match "sample rate"
def test_odd_stereo_samples_is_protocol_error():
def test_map_event_kinds():              # one case per kind above, including user_started,
                                         # user_stopped, error -> kind None + warning text
                                         # "agent error (fatal): ..." with a URL redacted

# tests/unit/test_driver.py
async def test_receive_yields_between_messages():
    # a fake connection whose recv() returns 200 AgentText events without suspending, then
    # None; a concurrent task counts its own loop iterations (await asyncio.sleep(0) each);
    # after the receive loop ends the counter is at least 100

# tests/unit/test_cli.py
def test_importing_cli_prints_no_pipecat_banner():
    # subprocess [sys.executable, "-c", "import parakh.cli"]: "Pipecat" not in stdout + stderr

# agent test module
def test_pipecat_version_reads_package_metadata():
    assert bot.PIPECAT_VERSION == importlib.metadata.version("pipecat-ai") == "1.16.0"
```

Move `test_malformed_agent_audio_is_protocol_error` and `test_unset_channel_count_is_mono` from `test_driver.py` to `test_events.py` against `events.agent_pcm`; the 2-channel case now downmixes, so replace it with a 3-channel case.

- [ ] **Step 2: Run** `uv run pytest tests/unit -q`. Expected: the new tests FAIL (missing module `parakh.caller.events`, RecursionError, banner present, hardcoded version).
- [ ] **Step 3: Implement.** Add `loguru>=0.7` to the main dependencies (already locked through Pipecat) and call `logger.disable("pipecat")` in `codec.py` before `from pipecat.frames.protobufs import frames_pb2`; never in `parakh/__init__.py`, because the clinic agent imports `parakh` and needs Pipecat's logs. Catch `RecursionError` in `_parse_message` and raise `ProtocolError`. Move the mapping into `events.py`; the driver's `_on_event` applies a `Mapped` (record the event, warn, store agent info, set the bot-stopped hold) in a few lines. `bot.PIPECAT_VERSION = importlib.metadata.version("pipecat-ai")`.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright && uv run ruff check`. Expected: all pass; `wc -l src/parakh/caller/driver.py` is below 350.
- [ ] **Step 5: Commit** `refactor(caller): move agent event mapping to caller/events.py and harden the receive path`. Push.

---

### Task 2: Audio timeline fixes: recorder, playback clock, bot-stopped hold

M1 review items: T7 per-frame resampling, T9 speech-end frame pin, T9 8 kHz wire test, T9 bot-stopped hold, Final caller frames not logged, Final `loud_end` drift with burst replies plus streamed silence.

**Files:**
- Modify: `src/parakh/caller/recorder.py`, `src/parakh/caller/clock.py`, `src/parakh/caller/driver.py`, `tests/integration/fake_agent.py`
- Test: `tests/unit/test_recorder.py`, `tests/unit/test_clock.py`, `tests/unit/test_driver.py`, `tests/integration/test_driver.py`

**Interfaces:**
- `PlaybackClock.on_audio(arrival_ns, n_samples, sample_rate, *, loud) -> int | None`: a silent frame that arrives while earlier audio is still queued (`playback_end_ns > arrival_ns`) is not placed and returns `None`, so streamed silence never pushes later speech back; every other frame is placed as in M1 and returns its playback start.
- `PlaybackClock.flush(now_ns: int) -> int`: drops queued audio: `playback_end_ns` and `loud_end_ns` become at most `now_ns`; returns the nanoseconds of audio dropped (0 if none).
- `Recorder.caller_lead(n_samples: int) -> None` (silence before the first sent frame, no event); `Recorder.caller_frame(t_ns, pcm, sample_rate, *, turn: int | None, frame: int | None, lost: bool = False)` logs a `caller_frame` event `{turn, frame, lost}` (spec 6.4: every frame in and out is logged); all caller frames of a call share one rate (`ValueError` otherwise) and the track is resampled to the WAV rate once, in `close()`.
- `Recorder.agent_frame(t_ns, pcm, sample_rate, playback_start_ms: float | None)`: the `agent_audio` event gains `play_ms` (playback start in ms since t0, `null` when the frame was not placed). In `close()`, consecutive placed frames with the same rate whose sample offsets touch (within 1 sample) are joined and each run is resampled once, so per-frame filtering no longer clicks.
- `Recorder.agent_flush(t_ns: int) -> None`: cuts every placed agent frame at that playback time, so `agent.wav` holds what the caller heard.
- Driver: an `AgentInterruption` flushes the clock and the recorder and logs `agent_interruption` with `flushed_ms`. A bot-stopped hold is discarded when a caller turn's last frame is sent, so only a bot-stopped that arrives after the caller finished can end the next reply.
- Fake agent: `FakeBehaviour.received: list[tuple[int, int]]` records `(sample_rate, n_samples)` of every caller frame it receives.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_clock.py
def test_silence_does_not_queue_behind_backlog():
    # loud 100 ms burst at t=0 (playback end 100 ms); silent 20 ms frame arriving at 10 ms:
    # on_audio returns None and playback_end_ns stays at 100 ms
def test_flush_drops_queued_audio():
    # 500 ms burst at t=0; flush(200 ms) returns 300 ms; speaking(201 ms) is False

# tests/unit/test_recorder.py
def test_agent_runs_resampled_once():
    # 50 contiguous 24 kHz frames of a 440 Hz sine into a 16 kHz track equal
    # resample(whole_sine, 24000, 16000) within 1 LSB (per-frame resampling differs by far more)
def test_agent_flush_cuts_track():
    # a 1000 ms loud frame placed at 0, agent_flush at 400 ms: agent.wav samples after 400 ms are 0
def test_caller_frames_logged_and_resampled_once():
    # 10 frames at 8000 Hz: 10 caller_frame events with turn/frame/lost; caller.wav at 16000 Hz
    # equals resample(concat, 8000, 16000)
def test_agent_audio_event_has_play_ms():   # placed frame: play_ms == playback_start_ms; None stays null

# tests/unit/test_driver.py
def test_bot_stopped_hold_discarded_at_caller_turn_end():
    # bot-stopped arrives while the caller's clip plays; after the clip's last frame is sent and a
    # new burst reply arrives, the reply does not end before end_of_turn_silence_ms of quiet
def test_bot_stopped_hold_not_passed_in_wait_agent_or_caller_speaking():
    # a held bot-stopped is passed to machine.step only on the first step in AGENT_SPEAKING;
    # steps in WAIT_AGENT and CALLER_SPEAKING get bot_stopped=False

# tests/integration/test_driver.py
async def test_speech_end_logged_on_its_frame():
    # clip: 400 ms tone + 200 ms silence (speech_end_ms 400, so frame 20): the caller_speech_end
    # event has the same t_ms as the caller_frame event with turn 0 and frame 20
async def test_8khz_wire_call():
    # run_call(..., agent_rate=8000) with FakeBehaviour(out_rate=8000): every entry of
    # behaviour.received is (8000, 160); latency within TOL_MS of reply_delay_ms; caller.wav is 16 kHz
async def test_streamed_silence_with_burst_replies_keeps_latency():
    # FakeBehaviour(stream_silence=True, burst=True), 3 turns: every turn's latency within
    # TOL_MS of reply_delay_ms (M1 drifted later each turn)
```

- [ ] **Step 2: Run** `uv run pytest tests/unit tests/integration -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above. The driver passes the lead with `caller_lead` at the agent rate.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright`. Expected: all pass (the M1 timeline tests too; update any M1 assertion that counted every event kind, now that `caller_frame` exists).
- [ ] **Step 5: Commit** `fix(caller): resample tracks once, log caller frames, flush on interruption, keep silence from queueing`. Push.

---

### Task 3: Run robustness: Ctrl+C, git sha, agent rate

M1 review items: T13 interrupted branch, T13 `_git_sha`, T9 `--agent-rate` validation.

**Files:**
- Modify: `src/parakh/run.py`, `src/parakh/cli.py`
- Test: `tests/unit/test_run.py`, `tests/unit/test_cli.py`

**Interfaces:**
- `run_scenario(..., on_start: Callable[[Path], None] | None = None)`: called once with the run directory just before the call starts. The CLI prints `run dir: <path>` from it, at the start of the run.
- On `KeyboardInterrupt` or `asyncio.CancelledError`, `run_scenario` writes a partial report built from the events recorded so far (status `interrupted`, turns, transcripts and latency as far as they got, warning `interrupted by the user`), then re-raises. A failure while writing it is swallowed, so the interrupt is never masked.
- `run_scenario` raises `ValueError` for an `agent_rate` not in `SUPPORTED_RATES`, before anything is written.
- `_git_sha()` returns `None` unless `_REPO_ROOT / ".git"` exists and `parakh` was imported from `_REPO_ROOT / "src"`; `git` runs with `timeout=5`, and `subprocess.TimeoutExpired` gives `None`.
- CLI `run`: Ctrl+C prints `interrupted` and exits 2 (Click's default "Aborted!" exit 1 would read as a failed task).

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_run.py
async def test_interrupt_writes_partial_report(tmp_path, monkeypatch):
    # fake run_call writes call_start, caller_turn_start(0), caller_speech_end(0), a loud
    # agent_audio and a final caller_transcript to events.jsonl, then raises KeyboardInterrupt:
    # KeyboardInterrupt propagates; report.json has status "interrupted", turns[0].transcript set,
    # turns[0].latency_ms not None, and the warning "interrupted by the user"
async def test_interrupt_survives_report_write_error(tmp_path, monkeypatch):
    # _write raises OSError: KeyboardInterrupt still propagates
def test_git_sha_none_outside_repo(tmp_path, monkeypatch):     # _REPO_ROOT -> tmp dir without .git
def test_git_sha_none_on_timeout(monkeypatch):                  # subprocess.run raises TimeoutExpired
async def test_unsupported_agent_rate_rejected(tmp_path):       # agent_rate=16001 -> ValueError, runs dir empty

# tests/unit/test_cli.py
def test_run_prints_run_dir_at_start_and_exits_2_on_interrupt(monkeypatch):
    # fake run_scenario calls on_start(path) then raises KeyboardInterrupt:
    # exit code 2; output has "run dir:" before "interrupted"
def test_run_rejects_unsupported_agent_rate():                  # --agent-rate 12345 -> exit 2
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_run.py tests/unit/test_cli.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Build the partial report through the same `_build_report` path as a finished call, with a stand-in for the missing `CallResult` (status `interrupted`, empty jitter, the last `agent_info` event, the recorded `warning` events).
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `fix(run): write a partial report on Ctrl+C, bound git, validate the agent rate`. Push.

---

### Task 4: Mu-law codec and telephone filters

**Files:**
- Create: `src/parakh/degrade/__init__.py`, `src/parakh/degrade/mulaw.py`, `src/parakh/degrade/filters.py`
- Test: `tests/unit/degrade/test_mulaw.py`, `tests/unit/degrade/test_filters.py` (with an empty `tests/unit/degrade/__init__.py` if the test layout needs it)

**Interfaces:**
- `F64 = npt.NDArray[np.float64]` (in `filters.py`, re-exported by the package).
- `mulaw_encode(pcm: PCM) -> npt.NDArray[np.uint8]` and `mulaw_decode(codes: npt.NDArray[np.uint8]) -> PCM`: G.711 mu-law on the 14-bit sample (`>> 2`), bias 33, clip 8159, segment search, bits inverted. `mulaw_saturated(pcm: PCM) -> int`: samples whose 14-bit magnitude exceeds the clip value, so the codec flattens them (EC-22).
- `TELEPHONE_RATE = 8000`, `BAND_HZ = (300.0, 3400.0)`, `PEAK_DBFS = -3.0`.
- `band_limit(x: F64, rate: int) -> F64`: Butterworth band-pass on `BAND_HZ` as second-order sections, applied with `sosfiltfilt` (zero phase, so speech-end timing does not move). Start at order 6; if the sweep tests below fail, raise the order, not the thresholds.
- `resample_f(x: F64, src: int, dst: int) -> F64`: `resample_poly` with the reduced ratio, float in and out, output length exactly `round(len(x) * dst / src)`.
- `peak_normalise(x: F64, target_dbfs: float = PEAK_DBFS) -> F64`: an all-zero input comes back unchanged.
- `hard_clip(x: F64, level_dbfs: float) -> tuple[F64, int]` and `to_int16(x: F64) -> tuple[PCM, int]` (round, clip to int16; both return the count of clipped samples).
- `telephone(x: F64, rate: int) -> tuple[F64, int]`: `band_limit`, `resample_f` to 8000, `to_int16`, mu-law encode and decode; returns the 8 kHz signal and the clipped plus saturated sample count.

- [ ] **Step 1: Write the failing tests.**

```python
# test_mulaw.py
def test_encode_matches_ffmpeg_for_every_value():
    # all 65536 int16 values (np.arange(-32768, 32768)): our codes equal
    # `ffmpeg -f s16le -ar 8000 -ac 1 -i pipe:0 -f mulaw pipe:1`, byte for byte
def test_decode_matches_ffmpeg_for_every_code():
    # all 256 codes: equal `ffmpeg -f mulaw -ar 8000 -ac 1 -i pipe:0 -f s16le pipe:1`
def test_round_trip_sqnr():
    # 1 s 1 kHz sine at 8 kHz: SQNR >= 35 dB at -3 dBFS, >= 33 dB at -30 dBFS
    # (G.711 theory gives about 38 dB near full load; a lower value is a codec bug, not a bound to relax)
def test_saturation_counted():   # full-scale square wave: every sample; -3 dBFS sine: 0

# test_filters.py
def test_band_limit_passes_voice_band():   # 1 kHz sine: loss < 1 dB; 100 Hz: >= 20 dB; 6 kHz: >= 40 dB
def test_band_limit_keeps_timing():        # 200 ms zeros + 400 ms 1 kHz tone: speech_end_ms within +-10 ms
def test_telephone_suppresses_aliasing():  # EC-23: 5.0-7.5 kHz sweep at 16 kHz: telephone() RMS >= 50 dB below input
def test_telephone_output_has_no_energy_above_4khz():
    # 100 Hz-7.9 kHz log sweep at -6 dBFS, telephone() then resample_f to 16000: FFT power at
    # >= 4000 Hz is >= 40 dB below total power (spec 8 sine-sweep test)
def test_resample_f_length():              # 16000 -> 8000 -> 24000 lengths exact for 16 001 samples
def test_peak_normalise():                 # peak becomes 32768 * 10 ** (-3 / 20) within 1; zeros unchanged
def test_hard_clip_counts():
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/degrade -q`. Expected: FAIL (`ModuleNotFoundError: parakh.degrade`).
- [ ] **Step 3: Implement** the functions above.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(degrade): add G.711 mu-law codec and telephone band filters`. Push.

---

### Task 5: Noise, packet loss, seeds, presets and the degrade chain

**Files:**
- Create: `src/parakh/degrade/noise.py`, `src/parakh/degrade/loss.py`, `src/parakh/degrade/seeds.py`, `src/parakh/degrade/presets.py`, `src/parakh/degrade/presets.yaml`, `src/parakh/degrade/chain.py`
- Modify: `pyproject.toml` (ship `presets.yaml` in the wheel, as M1 did for the report template)
- Test: `tests/unit/degrade/test_noise.py`, `test_loss.py`, `test_presets.py`, `test_chain.py`

**Interfaces:**
- `DegradeError(ValueError)` in `parakh.degrade`.
- `noise.py`: `white(n: int, rng) -> F64`, `pink(n, rng) -> F64` (1/f power), `brown(n, rng) -> F64` (1/f^2 power), each at unit RMS; `speech_active_rms(clips: Sequence[F64], rate: int) -> float` (RMS over the 10 ms windows above -45 dBFS of all clips together; `DegradeError` "no speech above -45 dBFS; SNR is undefined" when there are none, EC-24); `noise_scale(clips: Sequence[F64], noise: F64, rate: int, snr_db: float) -> float` (`DegradeError` for noise with zero RMS); `measured_snr_db(speech: F64, added_noise: F64, rate: int) -> float | None` (`None` for a clip with no speech-active window); `noise_slice(track: F64, n: int, rng) -> F64` (n samples from a random start, wrapping around).
- `loss.py`: `loss_mask(n_frames: int, rate: float, mean_burst_frames: float | None, rng) -> npt.NDArray[np.bool_]` (independent losses when `mean_burst_frames` is None; otherwise a two-state Gilbert model with r = 1 / mean_burst_frames and p = rate * r / (1 - rate)); `apply_loss(x: F64, frame_len: int, mask, conceal: Literal["zero", "repeat"]) -> F64`.
- `seeds.py`: `call_seed(scenario_id: str, preset: str) -> int` (first 8 bytes of sha256 of `f"{scenario_id}\x00{preset}"`, big-endian, masked to 63 bits); `part_rng(call_seed: int, part: str) -> np.random.Generator` (seeded from sha256 of `f"{call_seed}:{part}"`). Parts used: `"noise"` (the noise track), `"bed"` (the line between turns), `"turn-<i>"`.
- `presets.py`: pydantic models, all `extra="forbid"`: `NoiseSpec(kind: Literal["white", "pink", "brown", "babble"], snr_db: float)`, `LossSpec(rate: float (0 < rate <= 0.5), mean_burst_frames: float | None (> 1), conceal: Literal["zero", "repeat"] = "zero")`, `Preset(name: str, telephone: bool = False, noise: NoiseSpec | None = None, loss: LossSpec | None = None, clip_dbfs: float | None (< 0))`, `Talker(voice: str, text: str, rate: str = "+0%")`. `PRESET_ORDER: tuple[str, ...]` (file order); `load_presets() -> dict[str, Preset]`; `get_preset(name: str) -> Preset` (`ValueError` "unknown preset 'x'; available: clean, phone, ..."); `load_talkers() -> list[Talker]`.
- `presets.yaml`: the five presets with exactly the Global Constraints values, and `babble.talkers`: six talkers, voices `hi-IN-SwaraNeural`, `hi-IN-MadhurNeural`, `en-IN-NeerjaNeural`, `en-IN-PrabhatNeural`, and the first two again at rate `"+10%"`. Each text is a synthetic Hinglish or Indian English sentence of 15 to 25 words, unrelated to clinics (trains, weather, cricket, groceries, a bank queue, a school bus), with no real names, numbers or places.
- `chain.py`: `FRAME_MS = 20`; `@dataclass(frozen=True) class DegradeStats: snr_db: float | None; frames: int; lost_frames: int; clipped_samples: int`; `@dataclass(frozen=True) class Degraded: pcm: PCM; lost: list[bool]; stats: DegradeStats | None`; `degrade(pcm: PCM, rate: int, preset: Preset, *, out_rate: int, noise: F64 | None, rng: np.random.Generator) -> Degraded`. `noise` is already scaled and as long as `pcm`. Stage order, in float64:
  1. `clean`: resample to `out_rate` only; `lost` all False; `stats` None.
  2. Otherwise: `peak_normalise` (-3 dBFS), add `noise`, `hard_clip` when `clip_dbfs` is set, then `telephone` when `telephone` is true (8 kHz), packet loss on 20 ms frames of the current rate with `loss_mask(..., rng)`, `resample_f` to `out_rate`, `to_int16`.
  3. Output length is exactly the input duration at `out_rate`; `lost` has one entry per 20 ms frame (`ceil`); `stats.snr_db` is `measured_snr_db` of the normalised speech against `noise` (None without noise); `clipped_samples` sums every clipping stage.

- [ ] **Step 1: Write the failing tests.**

```python
# test_noise.py
@pytest.mark.parametrize(("kind", "slope_db"), [("pink", -3.0), ("brown", -6.0)])
def test_noise_slope_per_octave(kind, slope_db):   # Welch PSD 250-4000 Hz: mean slope within +-1 dB/octave
def test_noise_unit_rms():                          # white, pink, brown: RMS 1.0 within 1e-9
@pytest.mark.parametrize("snr_db", [5.0, 10.0, 20.0])
def test_snr_within_half_db(snr_db):
    # speech = 0.5 s 300 Hz tone, 0.3 s zeros, 0.7 s tone (peak-normalised); pink noise scaled by
    # noise_scale: measured_snr_db within +-0.5 dB of the target (spec 8)
def test_snr_scale_rejects_silence():               # zeros -> DegradeError matching "no speech"
def test_snr_scale_rejects_silent_noise():

# test_loss.py
@pytest.mark.parametrize(("rate", "burst"), [(0.03, None), (0.05, 3.0)])
def test_loss_rate_within_one_percent(rate, burst):  # 100 000 frames: mean within +-0.01 (spec 8)
def test_mean_burst_length():                        # rate 0.05, burst 3.0: mean loss-run length 3.0 +- 0.3
def test_conceal_zero_and_repeat():

# test_presets.py
def test_five_presets_in_order():   # PRESET_ORDER == ("clean", "phone", "phone_noisy", "phone_lossy", "bad_line")
def test_preset_values():           # each field equals the Global Constraints values
def test_unknown_preset_lists_available():
def test_six_talkers():
def test_presets_yaml_ships_in_wheel():   # same approach as the M1 template-in-wheel test

# test_chain.py
def test_clean_is_resample_only():              # out_rate 16000: output equals input
def test_same_seed_same_bytes():                # bad_line, same part_rng twice: identical bytes;
                                                # another part gives different bytes (EC-26)
@pytest.mark.parametrize("out_rate", [8000, 16000, 24000])
def test_phone_keeps_length_and_timing(out_rate):   # frames == ceil(duration / 20 ms);
                                                    # speech_end_ms within +-20 ms
def test_lost_frames_are_zero_at_8khz():        # phone_lossy, out_rate 8000, conceal zero: lost frames all 0
def test_bad_line_counts_clipping():            # clipped_samples > 0
def test_call_seed_is_stable():                 # pin the value call_seed("clinic-book-hinglish-01", "phone")
                                                # returns, so a change to the seed scheme fails a test
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/degrade -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the modules above. Pink and brown noise: shape white noise in the frequency domain (`rfft`, divide by `sqrt(f)` or `f`, zero the DC bin, `irfft`), then scale to unit RMS.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright` and the coverage command from Global Constraints. Expected: all pass; `parakh.degrade` coverage at least 85 %.
- [ ] **Step 5: Commit** `feat(degrade): add noise, packet loss, seeds, the five presets and the degrade chain`. Push.

---

### Task 6: Babble noise and `parakh degrade`

**Files:**
- Create: `src/parakh/degrade/babble.py`, `src/parakh/degrade/track.py`
- Modify: `src/parakh/cli.py`
- Test: `tests/unit/degrade/test_babble.py`, `tests/unit/test_cli.py`

**Interfaces:**
- `NOISE_TRACK_S = 30.0`.
- `babble.py`: `async build_babble(cache: TTSCache, engine: TTSEngine, seconds: float, rng) -> F64`: synthesises each talker from `load_talkers()` through `cache.get` (cached like caller clips), loops each clip to `seconds` from a random start, sums them, and scales to unit RMS (16 kHz).
- `track.py`: `async noise_track(preset: Preset, seed: int, cache: TTSCache, engine: TTSEngine) -> F64 | None`: `None` without noise; otherwise `NOISE_TRACK_S` seconds at 16 kHz from `part_rng(seed, "noise")`, generated (white, pink, brown) or built (babble).
- CLI: `parakh degrade CLIP --preset NAME [--out PATH] [--rate 16000] [--seed 0] [--cache-dir .cache/tts]`. Reads a 16-bit mono WAV at any supported rate (resampled to 16 kHz), builds the noise track with `call seed = --seed`, scales the noise to this clip alone, degrades with `part_rng(seed, "turn-0")`, writes `--out` (default `<stem>.<preset>.wav` beside the input) at `--rate`, and prints `wrote <path>` then `snr <x> dB, lost frames <a>/<b>, clipped samples <c>` (`snr n/a` without noise). Unknown preset, unreadable or non-mono WAV, an unsupported `--rate`, a silent clip under a noise preset, and ffmpeg missing (babble) print a message and exit 2.

- [ ] **Step 1: Write the failing tests.**

```python
# test_babble.py (FakeEngine from tests/fakes.py, cache in "dir with space")
async def test_babble_is_deterministic_and_unit_rms():
    # two builds with equal rngs are identical; RMS 1.0 within 1e-6; engine.calls is 6 after the
    # first build and still 6 after the second (cached)
async def test_noise_track_kinds():   # clean preset -> None; bad_line (pink) -> 30 s at 16 kHz without
                                      # touching the engine; phone_noisy -> babble

# test_cli.py
def test_degrade_writes_wav(tmp_path):              # phone: output exists, 16 kHz, duration equal to input within 20 ms
def test_degrade_rate_option(tmp_path):              # --rate 8000: output at 8000 Hz
def test_degrade_unknown_preset_exits_2(tmp_path):
def test_degrade_silent_clip_with_noise_exits_2(tmp_path):   # bad_line on zeros: message names the SNR problem
def test_degrade_babble_uses_engine(tmp_path, monkeypatch):  # phone_noisy with cli.make_engine -> FakeEngine
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/degrade tests/unit/test_cli.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(degrade): add own-TTS babble and the parakh degrade command`. Push.

---

### Task 7: Caller line: presets in the call

**Files:**
- Create: `src/parakh/caller/line.py`
- Modify: `src/parakh/caller/driver.py`, `src/parakh/run.py`, `src/parakh/report/model.py`, `src/parakh/report/templates/report.html.j2`, `tests/integration/fake_agent.py`
- Test: `tests/unit/test_line.py` (new), `tests/integration/test_driver.py`, `tests/integration/test_cli_run.py`, `tests/unit/test_report.py`

**Interfaces:**
- Consumes: Tasks 4 to 6 (`get_preset`, `degrade`, `noise_track`, `noise_scale`, `noise_slice`, `call_seed`, `part_rng`, `DegradeError`).
- Produces in `parakh.caller.line`: `BED_S = 10.0`; `@dataclass(frozen=True) class LineTurn: frames: list[PCM]; lost: list[bool]; speech_end_frame: int; stats: DegradeStats | None`; `@dataclass(frozen=True) class CallerLine: preset: str; seed: int | None; rate: int; turns: list[LineTurn]; bed: list[PCM]; bed_lost: list[bool]`; `async build_line(scenario: Scenario, clips: list[CallerClip], preset: str, agent_rate: int, *, cache: TTSCache, engine: TTSEngine) -> CallerLine`.
- `build_line`: `clean` gives the M1 frames (clip resampled to the agent rate, split in 20 ms frames) and a bed of one silent frame, `seed=None`. Any other preset: `seed = call_seed(scenario.id, preset)`; noise scaled once from all peak-normalised clips; turn i degraded with `part_rng(seed, f"turn-{i}")` and a noise slice drawn from that same rng; the bed is `BED_S` seconds of silence degraded with `part_rng(seed, "bed")` (noise, clipping, telephone and loss, no speech). `speech_end_frame = min(len(frames) - 1, speech_end_ms // 20)`, as in M1.
- `run_call(url, scenario, line: CallerLine, run_dir, *, end_of_turn_silence_ms=800)`: the agent rate is `line.rate` (the `agent_rate` parameter and `_load_clip` go). Between turns the driver streams `line.bed` in a loop instead of silence; every `caller_frame` event carries the frame's `lost` flag, and a bed frame is logged with `turn: null` and `frame` = its index in `line.bed`.
- `run_scenario`: `preset` checked with `get_preset` (replaces `PRESETS`); builds the line before the call; a `DegradeError` is raised before anything is written (CLI exit 2). Report: `seed = line.seed`; new model `TurnDegradation(_Strict)` with `snr_db: float | None; frames: int; lost_frames: int; clipped_samples: int`; `TurnReport.degradation: TurnDegradation | None = None` (a default, so M1 reports still load under `schema_version` 1). The HTML header shows preset and seed; each turn shows `line: SNR x dB (at mixing), lost a/b frames, clipped c samples` when present.
- Fake agent: `FakeBehaviour.vad_dbfs: float = SPEECH_DBFS` (its own speech threshold, so a test can make it ignore a noise bed).

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_line.py (clips are tone WAVs in "dir with space"; babble via FakeEngine)
async def test_clean_line_matches_m1_frames():      # frames == split_frames(resample(clip, 16000, 16000));
                                                    # bed is one zero frame; seed None; stats None
@pytest.mark.parametrize("rate", [8000, 16000, 24000])
async def test_line_frames_at_agent_rate(rate):     # phone: every frame len == rate // 50; frame count and
                                                    # speech_end_frame equal those of the clean line
async def test_line_is_deterministic():             # bad_line twice: identical frame and bed bytes
async def test_noisy_bed_is_not_silent():           # phone_noisy: dbfs(concat(bed)) > -60
async def test_silent_turn_gets_null_snr():         # clips [tone, zeros, tone] under bad_line: turn 1
                                                    # stats.snr_db is None; turns 0 and 2 are not
async def test_all_silent_noise_preset_raises():    # all zeros under bad_line: DegradeError

# tests/integration/test_driver.py
async def test_phone_preset_latency():              # phone line, FakeBehaviour(reply_delay_ms=500):
                                                    # latency within TOL_MS of 500
async def test_noise_preset_call_completes():
    # phone_noisy line (FakeEngine babble is a steady tone bed); FakeBehaviour(vad_dbfs=<midpoint
    # between dbfs of the concatenated bed and the quietest clip frame before speech end, both
    # measured from the line>), so the fake hears speech and not the bed: completed
async def test_lossy_preset_logs_lost_frames():
    # phone_lossy line: completed; every caller_frame's lost flag equals the line's flag for that
    # (turn, frame), or bed_lost[frame] for a bed frame

# tests/integration/test_cli_run.py
async def test_run_with_preset_records_seed_and_degradation():
    # run_scenario(..., preset="phone_lossy", engine=FakeEngine()): report.seed is an int;
    # each reached turn has degradation with frames > 0; report.html shows "phone_lossy"
async def test_unknown_preset_exits_2():            # update the M1 test to the new message
```

- [ ] **Step 2: Run** `uv run pytest -q`. Expected: the new tests FAIL; M1 driver tests that pass clips to `run_call` fail until updated to build a clean line (one helper in `tests/integration/test_driver.py`).
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(caller): stream preset-degraded caller turns and a noise bed`. Push.

---

### Task 8: Barge-in in the call

**Files:**
- Modify: `src/parakh/caller/clock.py`, `src/parakh/caller/turns.py`, `src/parakh/caller/driver.py`, `src/parakh/scenario/model.py`, `tests/integration/fake_agent.py`
- Test: `tests/unit/test_clock.py`, `tests/unit/test_turns.py`, `tests/unit/test_scenario.py`, `tests/integration/test_driver.py`

**Interfaces:**
- `PlaybackClock.onset_ns: int | None`: playback start of the first loud frame of the current loud run; a loud frame starts a new run when its playback start is more than `ONSET_GAP_NS = 200 ms` after `loud_end_ns` (or when there is no earlier loud frame). A flush does not change it.
- `TurnMachine(..., barge_in_ms: Sequence[float | None] = ())`: entry i is turn i's `barge_in.after_agent_ms` (missing entries are None). `step(..., agent_onset_ms: float | None = None)`.
  - On every entry into `AGENT_SPEAKING` the machine records the reply onset: `agent_onset_ms`, or `now_ms` when that is None. It keeps that value until it leaves the state, so pauses inside one reply do not restart the count.
  - In `AGENT_SPEAKING`, when the next turn has a barge-in, a turn remains, the agent is speaking and `now_ms >= reply_onset + after_agent_ms`, the machine starts that turn: `Action("start_turn", i, barge_in=True)`.
  - When a turn with a barge-in starts because the reply ended first, the action has `barge_in=False`. Turns without one have `barge_in=None`. `Action.barge_in: bool | None = None`.
- Driver: passes `clock.onset_ns` (as ms) every step; on `barge_in=True` logs `barge_in {turn, after_agent_ms, agent_onset_ms}` at the send time of the turn's first frame; on `barge_in=False` logs `barge_in_missed {turn, after_agent_ms}`.
- Scenario: a `barge_in` on the first turn of a caller-first scenario (`agent_speaks_first: false`) is a `ScenarioError` ("barge_in on the first turn needs agent_speaks_first: true").
- Fake agent: `FakeBehaviour.yield_after_ms: int | None = None` (while speaking, stop that long after the first loud caller frame; None never yields), `send_interruption: bool = False` (send a protobuf `interruption` frame when yielding), `user_started: bool = False` (send RTVI `user-started-speaking` at each caller onset). Yielding stops a paced reply's remaining frames; a burst reply has already been sent, so only the interruption frame (and the driver's flush) cuts it.

- [ ] **Step 1: Write the failing tests.**

```python
# test_clock.py
def test_onset_kept_across_short_gap():     # loud 0-500 ms, loud again at 600 ms: onset stays 0
def test_onset_resets_after_200ms_gap():    # loud 0-500 ms, loud again at 800 ms: onset 800 ms

# test_turns.py
def test_barge_in_fires_after_onset():      # onset 1000, after 1200: none at 2199, start_turn(barge_in=True) at 2200
def test_barge_in_counts_from_reply_onset():  # a clock onset moving to 1800 inside the reply does not delay it
def test_barge_in_missed_when_reply_ends_first():   # reply ends at 1500 (+800 ms silence): start_turn(barge_in=False)
def test_barge_in_on_greeting():            # turn 0 with a barge-in fires during the greeting
def test_turn_without_barge_in_has_none():

# test_scenario.py
def test_barge_in_on_first_turn_needs_agent_first(tmp_path):

# tests/integration/test_driver.py (scenario: turn 1 has barge_in after_agent_ms 1200; reply_ms 3000)
async def test_barge_in_agent_yields_with_interruption():
    # FakeBehaviour(burst=False, yield_after_ms=300, send_interruption=True): barge_in event for
    # turn 1 with t_ms - agent_onset_ms within 1200 +- TOL_MS; an agent_interruption after it; completed
async def test_barge_in_burst_reply_is_flushed():
    # burst=True, yield_after_ms=300, send_interruption=True: agent.wav is silent (below -45 dBFS)
    # from the interruption's t_ms + 40 ms until the next reply
async def test_barge_in_agent_never_yields():   # yield_after_ms=None: completed; loud agent audio continues
                                                # for more than 2 s after the barge_in event
async def test_barge_in_missed_short_reply():   # reply_ms=600: barge_in_missed for turn 1; completed
```

- [ ] **Step 2: Run** `uv run pytest tests/unit tests/integration -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright`. Expected: all pass; `driver.py` still below 350 lines.
- [ ] **Step 5: Commit** `feat(caller): add scheduled barge-in turns and reply onsets`. Push.

---

### Task 9: Barge-in scoring and the report

**Files:**
- Create: `src/parakh/score/bargein.py`
- Modify: `src/parakh/score/latency.py`, `src/parakh/run.py`, `src/parakh/report/model.py`, `src/parakh/report/templates/report.html.j2`
- Test: `tests/unit/test_bargein.py` (new), `tests/unit/test_latency.py`, `tests/unit/test_report.py`, `tests/integration/test_cli_run.py`

**Interfaces:**
- `STOP_GAP_MS = 200.0`, `DID_NOT_YIELD_MS = 2000.0`, `FALSE_BARGE_IN_GRACE_MS = 500.0`.
- `@dataclass(frozen=True) class StopLatency: turn: int; after_agent_ms: float; onset_ms: float | None; stop_latency_ms: float | None; result: Literal["yielded", "did_not_yield", "agent_finished_first"]; via: Literal["interruption", "audio"] | None`.
- `stop_latencies(events: list[dict[str, Any]], threshold_dbfs: float = SPEECH_DBFS) -> list[StopLatency]`, one per `barge_in` and `barge_in_missed` event (the latter is `agent_finished_first`, all times None). For a `barge_in` at onset `o` (its `t_ms`):
  1. Audio stop `a`: walk the loud placed agent frames (`dbfs` above the threshold, `play_ms` not null) that end after `o`, in `play_ms` order, starting from `end = o`. A frame starting at least `STOP_GAP_MS` after `end` is a gap and ends the walk; otherwise `end = max(end, play_ms + duration_ms)`. `a = end`.
  2. Interruption `i`: the `t_ms` of the first `agent_interruption` at or after `o`, if any.
  3. `stop = min(a, i) - o`, `via` the smaller one ("interruption" on a tie). Above `DID_NOT_YIELD_MS`: `did_not_yield`, `stop_latency_ms=None`. Otherwise `yielded`.
- `false_barge_ins(events, grace_ms: float = FALSE_BARGE_IN_GRACE_MS) -> list[float]`: candidates are the `user_started` events when the agent sent any, else the `agent_interruption` events; a candidate is false when no caller turn covers it, from `caller_turn_start` to `caller_turn_end + grace_ms` (EC-25). Returns their `t_ms`.
- `response_latencies(events, threshold_dbfs=SPEECH_DBFS, stops: Sequence[StopLatency] = ())`: a `did_not_yield` turn gets `latency_ms=None`, reason `"agent did not yield"`; a `yielded` turn's reply is searched from `max(speech_end, onset + stop_latency_ms)`; every other turn as in M1.
- Report: `BargeInReport(_Strict)` with the `StopLatency` fields except `turn`; `TurnReport.barge_in: BargeInReport | None = None`; `Metrics.stop_latency: LatencyStatsModel | None = None` (over `yielded` stops; None when the scenario has no barge-in), `Metrics.did_not_yield: int = 0`, `Metrics.false_barge_in_ms: list[float] = []`. HTML: metric rows "Barge-in stop latency p50 / p95 / max", "Did not yield", "False barge-ins"; per turn "barge-in after N ms: stopped in X ms (interruption|audio)", "did not yield within 2 s", or "agent finished first".

- [ ] **Step 1: Write the failing tests** (synthetic event lists built with a small helper in the test module).

```python
# tests/unit/test_bargein.py (onset at 5000 ms unless stated)
def test_stop_by_interruption():           # loud audio continues; agent_interruption at 5340 -> 340, via interruption
def test_stop_by_audio_gap():              # loud frames until 5340, next at 5700 -> 340, via audio
def test_first_of_interruption_and_gap():  # gap at 5300, interruption at 5450 -> 300, via audio
def test_short_gap_does_not_end_stop():    # 150 ms gap at 5200, audio until 5600, then 300 ms gap -> 600
def test_did_not_yield_after_2s():         # loud audio until 7100 without a gap -> did_not_yield, None
def test_agent_finished_first():           # barge_in_missed -> agent_finished_first, all None
def test_silent_and_unplaced_frames_ignored():   # frames at -60 dBFS or play_ms null never extend the stop
def test_false_barge_in_outside_turns():   # user_started inside a turn, 300 ms after its end, 900 ms after: [900 ms one]
def test_false_barge_in_falls_back_to_interruptions():   # no user_started events: agent_interruption used

# tests/unit/test_latency.py
def test_barge_turn_latency_skips_old_reply():   # old reply audio arrives until onset + 340 > speech end:
                                                 # latency measured from the new reply
def test_did_not_yield_turn_has_no_latency():

# tests/unit/test_report.py
def test_report_includes_barge_in():        # _build_report with barge-in events: turn barge_in, metrics.stop_latency,
                                            # did_not_yield and false_barge_in_ms filled; HTML shows the rows

# tests/integration/test_cli_run.py
async def test_barge_in_run_scores_stop_latency():
    # fake agent burst=False, yield_after_ms=300, send_interruption=True: report turn 1 barge_in result
    # "yielded", via "interruption", stop_latency_ms within 300 +- 2 * TOL_MS
```

- [ ] **Step 2: Run** `uv run pytest -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above; `run._build_report` computes stops once and passes them to `response_latencies`.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright` and the coverage command. Expected: all pass; `parakh.score` coverage at least 85 %.
- [ ] **Step 5: Commit** `feat(score): score barge-in stop latency and false barge-ins`. Push.

---

### Task 10: Batch runs, the comparison page and budget presets

**Files:**
- Create: `src/parakh/report/compare.py`, `src/parakh/report/templates/compare.html.j2`
- Modify: `src/parakh/run.py`, `src/parakh/cli.py`, `src/parakh/budget/estimate.py`
- Test: `tests/unit/test_compare.py` (new), `tests/unit/test_run.py`, `tests/unit/test_cli.py`, `tests/unit/test_budget.py`

**Interfaces:**
- `expand_presets(names: Sequence[str]) -> list[str]`: `all` expands to `PRESET_ORDER`; duplicates dropped, order kept; unknown names raise `ValueError` (in `parakh.degrade.presets`).
- `run_batch(scenario_paths: list[Path], agent_url: str, presets: list[str], *, runs_dir: Path, agent_rate: int, engine: TTSEngine | None, cache_dir: Path, on_start: Callable[[Path], None] | None = None) -> tuple[list[tuple[Report, Path]], Path | None]`: for each scenario (file order), each preset in turn, back to back (EC-77). One (scenario, preset) pair runs exactly like M1 (`runs/<run_id>/`, no comparison). More than one: every run goes in `runs/<batch_id>/<run_id>/` and `runs/<batch_id>/compare.html` plus `compare.json` are written after every finished run, so a stopped batch keeps its page. A run that ends in any status does not stop the batch; Ctrl+C stops it after writing the comparison, then re-raises.
- `compare.py`: `CompareRow(_Strict)` with `scenario_id`, `scenario_title`, `preset`, `run_id`, `report_href` (relative to the comparison directory, forward slashes), `status`, `loose_wer`, `strict_wer`, `latency_p50_ms`, `latency_p95_ms`, `stop_p50_ms`, `did_not_yield`, `false_barge_ins`; `Comparison(_Strict)` with `schema_version: Literal[1] = 1`, `created_at`, `rows`; `build_comparison(runs: list[tuple[Report, Path]], out_dir: Path) -> Comparison` (rows sorted by scenario id, then `PRESET_ORDER`, unknown presets last); `write_comparison(comparison: Comparison, out_dir: Path) -> Path` (writes `compare.json` and `compare.html`, returns the HTML path).
- `compare.html.j2`: self-contained like `report.html` (inline CSS, the same light and dark colour tokens, autoescape), one table per scenario with a column per preset, and two inline SVG bar charts per scenario: loose WER by preset and latency p50 by preset, in preset order, each bar labelled. Each cell links to its run's `report.html`.
- CLI: `run` takes a scenario file or a directory and a repeatable `--preset` (default `clean`, `all` allowed), prints `run dir: <path>` per run and `comparison: <path>` at the end, and exits with the highest exit code of its runs. New command `parakh compare RUN_DIR... [--out DIR]` (default: the parent of the first run directory) builds the page from existing `report.json` files; an unreadable one prints a message and exits 2.
- Budget: `estimate(scenarios, clip_seconds=None, presets: int = 1)`; observed request rates from the M1 runs replace the 1-per-turn guess: `STT_PER_TURN = 3`, `LLM_PER_TURN = 3`, plus one LLM request for a greeting; everything multiplies by `presets`. `parakh budget PATHS --preset ...` (repeatable, `all` allowed) prints `presets: <n>` and notes that noise presets can add STT requests when the agent's VAD reacts to noise.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_compare.py (Report fixtures built in the test; dirs with spaces)
def test_rows_ordered_by_scenario_then_preset():
def test_report_links_are_relative():          # href == "a1b2c3d4/report.html"
def test_compare_html_escapes_titles():        # scenario title "<script>": escaped in compare.html
def test_compare_json_round_trips():
def test_failed_run_shows_status():            # agent_unreachable row: status shown, metrics "n/a"

# tests/unit/test_run.py (run_scenario monkeypatched to record calls and return fixture reports)
async def test_batch_runs_presets_back_to_back():   # 2 scenarios x [clean, phone]: order s1/clean, s1/phone, s2/clean, s2/phone;
                                                    # run dirs inside one batch dir; compare.html exists
async def test_single_run_has_no_batch_dir():
async def test_batch_continues_after_failed_run():  # second run agent_unreachable: third still runs; 3 rows
async def test_batch_interrupt_writes_compare_for_finished_runs():   # KeyboardInterrupt on run 2:
                                                    # compare.html has run 1 (and run 2's partial report); re-raised

# tests/unit/test_cli.py
def test_preset_all_expands():
def test_batch_exit_code_is_highest():           # codes 0, 2, 1 -> exit 2
def test_compare_command(tmp_path):              # two run dirs with report.json -> compare.html in --out
def test_compare_command_bad_report_exits_2(tmp_path):

# tests/unit/test_budget.py
def test_budget_counts_observed_rates():         # 4 turns, agent first: STT 12, LLM 13
def test_budget_multiplies_presets():            # same scenario, presets=5: STT 60, LLM 65
```

- [ ] **Step 2: Run** `uv run pytest -q`. Expected: the new tests FAIL; update the M1 budget tests to the new rates.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** `uv run pytest -q && uv run pyright`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(report): add batch runs across presets and the comparison page`. Push.

---

### Task 11: Barge-in scenario and the real runs (controller-run)

The controller runs this task in its own session, not an implementer subagent: it starts the clinic agent with the Groq key from `.env` and must stop on HTTP 402 or 429 or any payment prompt. Never print or paste the key.

**Files:**
- Create: `scenarios/hinglish/clinic-bargein-hinglish-01.yaml`, `docs/runbooks/run-m2.md`
- Test: `tests/unit/test_scenario.py`

- [ ] **Step 1: Write the scenario.** Same clinic, clock and limits as `clinic-book-hinglish-01`; caller voice `hi-IN-MadhurNeural`; four turns. Turn 1 interrupts the agent's reply after 1200 ms:

```yaml
turns:
  - say: "Hello, mujhe Dr. Rao ke saath appointment chahiye."
    ref: "hello mujhe doctor rao ke saath appointment chahiye"
  - say: "Sorry, ek minute, mujhe kal subah ka slot chahiye, saadhe das baje."
    barge_in: { after_agent_ms: 1200 }
  - say: "Haan, mera number hai nine eight four five, zero one two, three four five."
    ref: "haan mera number hai 9845012345"
  - say: "Theek hai, thank you, bye."
```

Test: `test_bargein_scenario_loads` (turn 1 has `barge_in.after_agent_ms == 1200`; the other turns have none). Commit `feat(scenario): add a Hinglish barge-in scenario`.

- [ ] **Step 2: Budget check.** `uv run parakh budget scenarios/hinglish --preset all`. Expected: within limits (2 scenarios x 5 presets).
- [ ] **Step 3: Real batch 1.** Start the agent (`docs/runbooks/run-m1.md`), then `uv run parakh run scenarios/hinglish/clinic-book-hinglish-01.yaml --agent ws://127.0.0.1:8765 --preset all`. Expected: five run directories in one batch directory and a `compare.html`. Statuses other than `completed` under noise presets are findings, not failures (EC-25): record them.
- [ ] **Step 4: Real batch 2.** `uv run parakh run scenarios/hinglish/clinic-bargein-hinglish-01.yaml --agent ws://127.0.0.1:8765 --preset clean --preset phone_noisy`. Expected: turn 2's report shows a barge-in result (yielded with a stop latency, did not yield, or agent finished first).
- [ ] **Step 5: Write `docs/runbooks/run-m2.md`:** presets and what each adds; batch and `compare` commands; reading `compare.html` and the barge-in lines; the Groq budget with the observed STT and LLM counts per preset; troubleshooting (the agent never answers under babble because its VAD hears the bed as speech; a 429 mid-batch: stop, wait, rerun the missing presets); and a run log with the batch ids, a table of the comparison numbers, and one quoted barge-in turn. Commit `docs(runbooks): add the M2 run runbook and log the first preset batches`. Push.

---

### Task 12: Spec, register, README and knowledge graph

**Files:**
- Modify: `docs/superpowers/specs/2026-11-15-parakh-design.md`, `README.md`, `docs/README.md`, `docs/kg/graph.yaml`, `docs/kg/README.md` (generated)

- [ ] **Step 1: Spec.** Update line "Updated:". 6.3: the stage order, the bed, the per-call noise level, where SNR is measured, the preset values, the six babble talkers, seeds via sha256 parts. 6.4: silent frames do not queue behind a backlog, the flush on an interruption frame, reply onsets with the 200 ms gap, `caller_frame` events with the `lost` flag, the bot-stopped hold discarded at a caller turn's end. 6.7: the stop-latency algorithm, the barge-in turn latency rule, false barge-ins. 6.8: observed request rates and presets in the estimate. 6.9: the comparison page and batch layout. 6.10: `degrade`, `compare`, repeatable `--preset` with `all`, batch exit code, Ctrl+C exit 2. 10: M2 met, with the batch ids and headline numbers from `run-m2.md`. 11: EC-22 to EC-26, EC-37 and EC-64 rows say how M2 handles them; EC-27 notes the silence rule; EC-78 notes the protobuf twin and pair consumption; new rows for anything Task 11 found (number them from EC-83).
- [ ] **Step 2: README.** Presets table, barge-in, the comparison page, the `degrade` and `compare` commands, the M2 results, status line. Technical and professional, no emoji.
- [ ] **Step 3: Docs index and knowledge graph.** `docs/README.md` gains the M2 plan and runbook. `graph.yaml`: update `degrader`, `call_driver`, `score_latency`, `report`, `transport_codec` and `m2` (complete, with the headline numbers); add `caller_line` (path `src/parakh/caller/line.py`), `score_bargein` (`src/parakh/score/bargein.py`), `report_compare` (`src/parakh/report/compare.py`), `doc_plan_m2`, `doc_runbook_m2`, with their edges. Run `uv run python -m tools.kg_render`.
- [ ] **Step 4: Run** `uv run pytest -q` (the KG sync and no-emoji tests included). Expected: all pass.
- [ ] **Step 5: Commit** `docs: record M2 in the spec, README and knowledge graph`. Push and check CI is green on Ubuntu and Windows.

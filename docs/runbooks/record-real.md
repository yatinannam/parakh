# Real recordings: your own voice against the agent

Until now every caller turn was synthesised by edge-tts. This runbook lets you read the same scripted lines yourself and play your recordings to the clinic agent. Real speech is messier than synthetic speech, so the results are a better test of the agent's transcription.

Your recordings are personal data. Parakh therefore treats a real run differently from every other run (see "What stays on this laptop" below).

## 1. Which scenarios to record

Record these four. Each has four turns, so you record four short clips per scenario.

| Scenario id | Why |
|---|---|
| `clinic-book-hinglish-01` | The baseline booking, with an English-style phone number |
| `clinic-book-iyer-hinglish-01` | The doctor's name "Iyer" |
| `clinic-hindi-numbers-hinglish-01` | Numbers in Hindi words ("bees November", "nau aath saat...") |
| `clinic-correction-hinglish-01` | The caller corrects the last digit |

The lines are in `scenarios/hinglish/<id>.yaml`, under `turns` as `say:`. Read them from the file, or print them with the status command in step 3.

## 2. Record and name the files

Use any recorder: Windows Voice Recorder, your phone, Audacity. Any format ffmpeg reads works, including `.m4a`, `.mp3`, `.wav` and `.ogg`. Parakh converts each file to 16 kHz mono itself, and trims leading and trailing silence. Parakh adds no microphone code.

Save one file per turn, with these exact names, in `data/real/<scenario id>/`:

```
data/real/clinic-book-hinglish-01/turn-01.m4a
data/real/clinic-book-hinglish-01/turn-02.m4a
data/real/clinic-book-hinglish-01/turn-03.m4a
data/real/clinic-book-hinglish-01/turn-04.m4a
```

- The number is the turn number, starting at 01. The extension can be anything.
- Keep one file per turn. Two files for the same turn (`turn-02.wav` and `turn-02.m4a`) stop the run, and the message names both.
- Files starting with a dot are ignored. Parakh keeps its own converted copies there, as `.turn-01.16k.wav`. You can delete them. Parakh makes them again when it needs them.

How to read a line:
- Read it as you would say it to a receptionist, at your normal pace. Do not read it like a script and do not slow down for the numbers.
- Say the words as written. The score compares the agent's transcript with the line.
- Record a quiet room. Speak from about a hand's length away. The recording must have clear speech: a silent or very quiet file (nothing above -45 dBFS) stops the run before the call, and the message names the file.
- Start talking within a second of pressing record and stop soon after the last word. Trimming removes the extra silence anyway.
- If you slip, record that turn again.

## 3. Check the recordings

```
uv run parakh recordings status scenarios/hinglish/clinic-book-hinglish-01.yaml
```

It prints one line per turn:

```
turn 01: found  data/real/clinic-book-hinglish-01/turn-01.*  "Hello, mujhe Dr. Rao ke saath follow-up appointment chahiye."
turn 02: MISSING  data/real/clinic-book-hinglish-01/turn-02.*  "..."
unused: data/real/clinic-book-hinglish-01/turn-09.wav
```

- It exits 0 when every turn is found, and 2 when any is missing.
- `unused:` lists files that match no turn, such as a stray `turn-09.m4a` or a file with another name. They are never played.
- Give it several scenarios, or a folder, to check them in one go.

## 4. Start the agent with local speech recognition

A real run only plays your voice to an agent that transcribes on this laptop. Start the clinic agent with its local STT:

```
uv run --group agent python -m agents.clinic_agent --profile hi --stt local --port 8765
```

- `--profile hi` is the Hindi profile, which matches the four scenarios.
- `--stt local` runs faster-whisper small on the CPU, and reports `stt_model` as `local:...` in its first message. The first start downloads the model once, then it works offline.
- The agent still sends text to Groq for its replies (its LLM): the transcript of what you said goes to Groq. The audio does not. See "What stays on this laptop".
- It holds the heavy-model lock, so do not run it together with Parler or another Whisper job.

## 5. Run with `--real`

```
uv run parakh run scenarios/hinglish/clinic-book-hinglish-01.yaml --agent ws://127.0.0.1:8765 --real
```

Run the four scenarios one by one. Presets work as usual (`--preset phone`, and so on): the degradation is applied to your recording, and any noise babble is still synthetic.

- The report is marked "Real recording: audio stays on this machine".
- The judge is skipped, with the reason `real recording (D20)`.
- WER and latency are scored as always.

## What stays on this laptop

- **The agent must be on this machine.** `--real` accepts only an agent URL whose host is `127.0.0.1`, `localhost` or `::1`. Any other URL stops the run before anything is written. Parakh also refuses to follow a redirect, and after connecting it checks that the other end of the socket is a loopback address. If the peer is anywhere else, the run ends `real_data_refused` and no audio has been sent.
- **Never use `--real` through a forwarded port.** An `ssh -L` tunnel or any port forward makes a remote agent look like `127.0.0.1`. Parakh cannot see past it. Run the agent on this laptop only.
- **The agent must prove its speech recognition is local.** Parakh plays your recording only after the agent's first message reports an `stt_model` that starts with `local:`. Until then, and always when the agent reports another model or sends no message within 5 seconds, Parakh sends silence instead. The run then ends with status `real_data_refused`, exit code 2 and a warning such as `real data refused: agent stt_model 'whisper-large-v3-turbo' is not local`.
- **The transcript of your recording goes to Groq.** The audio never leaves the laptop, but the agent's local speech recognition turns it into text, and the agent's Groq LLM receives that text to write its replies. This is by design (D10). It includes anything else the microphone heard, such as another person talking. Record in a quiet room with no other voices, and say only the scripted line.
- **No synthesis.** The recordings never go to edge-tts. Only the scripted text of the noise babble (synthetic) can.
- **No judge.** Parakh adds nothing further: it sends none of the recording, its transcript or the agent's replies to the Groq or Gemini judge. The judge is skipped.
- **No upload and no commit.** `data/real/` is in `.gitignore`. The run directory under `runs/` holds `caller.wav`, which is your voice, and is gitignored too. Do not copy it into the repository or share it.

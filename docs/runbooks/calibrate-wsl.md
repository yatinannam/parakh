# Calibrate text simulation in WSL (Task 1 run)

Runs Calibrate's text simulation once, on free OpenRouter models, to complete Task 1. Calibrate is CC-BY-SA-4.0: it is installed only inside WSL, outside this repo, and none of its code is copied here (spec D2, EC-61).

Why WSL: Calibrate depends on `simpleaudio`, which has no prebuilt Windows wheel for Python 3.11 (EC-01).

Why a wrapper: `calibrate-agent simulations --type text -m <model>` sets only the agent's model. The simulated user stays on `openai/gpt-4.1` and the judge fallback on `openai/gpt-5.4-mini`, both paid, with no flag for either. `tools/calibrate_eval/run_text_sim.py`:

- refuses any model id that does not end in `:free`;
- forces that model onto the agent, the simulated user and the judge fallback, and stops if the installed `run_simulation` signature has drifted;
- removes `ENABLE_TRACING`, because Calibrate treats any non-empty value, including `false`, as on.

Budget: 8 OpenRouter requests per run in practice (4 agent, 3 user, 1 judge); at most about 13 with 6 turns. The free cap without purchased credits is about 50 requests per day and 20 per minute.

## Steps

All commands run in a WSL Ubuntu terminal (`wsl -d Ubuntu`). `REPO` is this repo seen from WSL:

```
REPO=/mnt/c/Users/ninja/OneDrive/Documents/Yatin/Projects/parakh
```

### 1. System packages (needs your sudo password)

```
sudo apt update && sudo apt install -y python3-venv python3-dev build-essential libasound2-dev
```

### 2. OpenRouter key (no card)

1. Sign up at <https://openrouter.ai>. Do not add credits or a card.
2. Create a key under **Keys**, named `parakh-calibrate-eval`.
3. Store it only in WSL:

```
mkdir -p ~/calibrate-eval
printf 'OPENROUTER_API_KEY=%s\n' 'PASTE_KEY_HERE' > ~/calibrate-eval/.env
chmod 600 ~/calibrate-eval/.env
```

### 3. Install Calibrate in its own environment

```
cd ~/calibrate-eval
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install calibrate-agent==0.0.81
grep -n "bot_model=args.model" .venv/lib/python3.12/site-packages/calibrate_agent/llm/run_simulation.py
```

The `grep` must print the line. That confirms the installed version still sets only the agent's model, which is what the wrapper assumes. If `simpleaudio` fails to build, record the error below, then install with `--no-deps` and add the other dependencies by hand.

### 4. Pick a free model

```
curl -s https://openrouter.ai/api/v1/models \
  | python3 -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin)['data'] if m['id'].endswith(':free')]"
```

Prefer an instruction-tuned model of 70B parameters or more. Record the id below.

### 5. Run

```
cd ~/calibrate-eval
set -a; . ./.env; set +a
.venv/bin/python "$REPO/tools/calibrate_eval/run_text_sim.py" \
  --model MODEL_ID_HERE \
  --config "$REPO/tools/calibrate_eval/text_sim_config.json" \
  --out ~/calibrate-eval/out-1
```

On HTTP 402 or 429, copy the exact error line below and stop. Never buy credits.

Results land in `~/calibrate-eval/out-1`: `metrics.json`, `results.csv`, and per simulation `transcript.json`, `evaluation_results.csv` and `logs`. Per-request TTFB is only in `logs` (DEBUG lines).

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `timeout setting the pipeline up (a processor blocked while connecting?)` on the first run after install | Pipecat counts its import warm-up against a 20 s setup timeout; a cold first import is slower | Run again; the second run sets up in under a second |
| Transcript holds only an `end_call` tool call | The agent prompt does not say how the call opens and ends | Keep the opening and closing rules in the config's `system_prompt` |
| `Connection refused` to `localhost:4318` | `ENABLE_TRACING` is set to a non-empty value | Use the wrapper, which removes it; `unset ENABLE_TRACING` if running the CLI directly |
| `Idle timeout detected` near the end | A free-tier reply took over a minute | Harmless for one run; the judge still scores the transcript |
| `RuntimeError: run_simulation has no parameter(s) ...` | Installed `calibrate-agent` is not 0.0.81 | Reinstall `calibrate-agent==0.0.81` |

## Run log

| Date | calibrate-agent | Model | Requests | Result |
|---|---|---|---|---|
| 2026-11-16 | 0.0.81 | probe only | 1 | HTTP 200 |
| 2026-11-16 | 0.0.81 | `nvidia/nemotron-3-ultra-550b-a55b:free` | 0 | Pipecat setup timeout (cold start) |
| 2026-11-16 | 0.0.81 | `nvidia/nemotron-3-ultra-550b-a55b:free` | 2 | Agent ended the call at once; prompt fixed |
| 2026-11-16 | 0.0.81 | `nvidia/nemotron-3-ultra-550b-a55b:free` | 8 | Pass (`booked_correctly` = 1), 99 s |
| 2026-11-16 | 0.0.81 | `nvidia/nemotron-3-ultra-550b-a55b:free` | 8 | Pass after tracing fix, 416 s (free-tier latency) |

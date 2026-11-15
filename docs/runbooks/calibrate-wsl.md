# Calibrate text simulation in WSL (Task 1 run)

Runs Calibrate's text simulation once, on free OpenRouter models, to complete Task 1. Calibrate is CC-BY-SA-4.0: it is installed only inside WSL, outside this repo, and none of its code is copied here (spec D2, EC-61).

Why WSL: Calibrate depends on `simpleaudio`, which has no prebuilt Windows wheel for Python 3.11 (EC-01).

Why a wrapper: `calibrate-agent simulations --type text -m <model>` sets only the agent's model. The simulated user stays on `openai/gpt-4.1`, a paid model, and has no flag. `tools/calibrate_eval/run_text_sim.py` forces the same free model for both sides and refuses any model id that does not end in `:free`.

Budget: about 15 OpenRouter requests (6 turns per side plus 1 judge call). The free cap without purchased credits is about 50 requests per day and 20 per minute.

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

## Run log

| Date | calibrate-agent | Model | Requests | Result |
|---|---|---|---|---|
| (pending) | 0.0.81 | | | |

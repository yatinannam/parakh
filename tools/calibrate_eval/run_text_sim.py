"""Run Calibrate's text simulation on free OpenRouter models.

Runs only inside WSL, with `calibrate-agent==0.0.81` installed in a separate
virtual environment (see docs/runbooks/calibrate-wsl.md). This file is MIT and
contains no Calibrate code; it only imports the installed package.

Why a wrapper: Calibrate's CLI passes `--model` to the agent only. The simulated
user keeps the default `user_model="openai/gpt-4.1"`, a paid model, and no flag
changes it. This wrapper swaps the module attribute `run_simulation` for a thin
async wrapper that sets `user_model` to the same free model, then hands control
to Calibrate's own CLI.

Usage:
    python run_text_sim.py --model <id ending in :free> --config text_sim_config.json --out DIR
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PLACEHOLDER = "__FREE_MODEL__"


def resolve_config(src: Path, model: str, out_dir: Path) -> Path:
    """Write a copy of the config with the placeholder replaced by `model`."""
    text = src.read_text(encoding="utf-8").replace(PLACEHOLDER, model)
    json.loads(text)  # fail early on invalid JSON
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = out_dir / "config.resolved.json"
    resolved.write_text(text, encoding="utf-8")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_text_sim.py")
    parser.add_argument("--model", required=True, help="OpenRouter model id ending in :free")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if not args.model.endswith(":free"):
        print("refusing to run: --model must be an OpenRouter ':free' model id", file=sys.stderr)
        return 2
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY not set; source ~/calibrate-eval/.env first", file=sys.stderr)
        return 2

    resolved = resolve_config(args.config, args.model, args.out)
    os.environ["ENABLE_TRACING"] = "false"

    import calibrate_agent.llm.run_simulation as sim  # type: ignore[import-not-found]
    from calibrate_agent import cli  # type: ignore[import-not-found]

    original = sim.run_simulation

    async def run_with_free_user_model(*a, **kw):
        kw["user_model"] = args.model
        return await original(*a, **kw)

    sim.run_simulation = run_with_free_user_model

    sys.argv = [
        "calibrate-agent",
        "simulations",
        "--type",
        "text",
        "-c",
        str(resolved),
        "-m",
        args.model,
        "-p",
        "openrouter",
        "-o",
        str(args.out),
    ]
    result = cli.main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())

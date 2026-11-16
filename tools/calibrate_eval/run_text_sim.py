"""Run Calibrate's text simulation on free OpenRouter models.

Runs only inside WSL, with `calibrate-agent==0.0.81` installed in a separate
virtual environment (see docs/runbooks/calibrate-wsl.md). This file is MIT and
contains no Calibrate code; it only imports the installed package.

Why a wrapper: Calibrate's CLI passes `--model` to the agent only. The simulated
user keeps the default `user_model="openai/gpt-4.1"`, a paid model, and no flag
changes it. The judge falls back to `fallback_judge_model="openai/gpt-5.4-mini"`
when an evaluator names no `judge_model`. This wrapper swaps the module attribute
`run_simulation` for a thin async wrapper that sets both to the same free model,
then hands control to Calibrate's own CLI.

Usage:
    python run_text_sim.py --model <id ending in :free> --config text_sim_config.json --out DIR
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from collections.abc import MutableMapping
from pathlib import Path
from types import ModuleType

PLACEHOLDER = "__FREE_MODEL__"
FORCED_PARAMS = ("user_model", "fallback_judge_model")


def resolve_config(src: Path, model: str, out_dir: Path) -> Path:
    """Write a copy of the config with the placeholder replaced by `model`.

    Raises ValueError, before writing anything, for a config that could reach
    a paid model despite the wrapper: one with `agent_url` (Calibrate then
    uses `run_simulation_with_agent`, which this wrapper does not patch) or an
    evaluator whose `judge_model` is not a `:free` model.
    """
    text = src.read_text(encoding="utf-8").replace(PLACEHOLDER, model)
    data = json.loads(text)  # fail early on invalid JSON
    if data.get("agent_url"):
        raise ValueError("config sets agent_url; external agents are not supported")
    for evaluator in data.get("evaluators", []):
        judge = evaluator.get("judge_model")
        if judge is not None and not str(judge).endswith(":free"):
            raise ValueError(f"evaluator judge_model {judge!r} is not a ':free' model")
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = out_dir / "config.resolved.json"
    resolved.write_text(text, encoding="utf-8")
    return resolved


def disable_tracing(env: MutableMapping[str, str]) -> None:
    """Turn Calibrate's OpenTelemetry tracing off.

    Calibrate reads `bool(os.getenv("ENABLE_TRACING"))`, so any non-empty value,
    including "false", enables it. Only removing the variable disables it.
    """
    env.pop("ENABLE_TRACING", None)


def force_free_models(sim: ModuleType, model: str) -> None:
    """Replace `sim.run_simulation` so every paid default model becomes `model`.

    Raises RuntimeError if the installed signature lacks a parameter this
    wrapper relies on, which means the Calibrate version has drifted.
    """
    original = sim.run_simulation
    params = inspect.signature(original).parameters
    missing = [name for name in FORCED_PARAMS if name not in params]
    if missing:
        raise RuntimeError(
            f"run_simulation has no parameter(s) {', '.join(missing)}; "
            "the installed calibrate-agent does not match 0.0.81"
        )

    async def run_with_free_models(*a, **kw):
        for name in FORCED_PARAMS:
            kw[name] = model
        return await original(*a, **kw)

    sim.run_simulation = run_with_free_models


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

    try:
        resolved = resolve_config(args.config, args.model, args.out)
    except ValueError as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    disable_tracing(os.environ)

    import calibrate_agent.llm.run_simulation as sim  # type: ignore[import-not-found]
    from calibrate_agent import cli  # type: ignore[import-not-found]

    force_free_models(sim, args.model)

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

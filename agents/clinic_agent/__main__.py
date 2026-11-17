"""Run the clinic test agent: python -m agents.clinic_agent."""

import argparse
import asyncio
import contextlib
import os
import sys

import httpx
from dotenv import dotenv_values
from pipecat.workers.runner import WorkerRunner

from agents.clinic_agent.bot import build_task
from agents.clinic_agent.config import AgentConfig, load_config, verify_models

MODELS_URL = "https://api.groq.com/openai/v1/models"


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(prog="clinic_agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    key = dotenv_values(".env").get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not key:
        _fail("GROQ_API_KEY is not set in .env or the environment.")
        return
    config = load_config()
    try:
        response = httpx.get(MODELS_URL, headers={"Authorization": f"Bearer {key}"}, timeout=10)
        response.raise_for_status()
        available = {item["id"] for item in response.json()["data"]}
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        _fail(f"Could not list Groq models ({type(exc).__name__}).")
        return
    try:
        verify_models(available, config)
    except RuntimeError as exc:
        _fail(str(exc))
        return

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(config, key, args.host, args.port))


async def _serve(config: AgentConfig, key: str, host: str, port: int) -> None:
    """Serve calls until interrupted.

    One pipeline serves call after call and resets its per-call state when a caller
    connects (bot.build_task). A new one is built only if the pipeline ends anyway,
    for example after a fatal error. WorkerRunner.run swallows the cancellation that
    Ctrl+C raises, so after each run we check for a pending cancel and stop instead of
    building another pipeline.
    """
    current = asyncio.current_task()
    while True:
        task, _transport = build_task(config, key, host=host, port=port)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(task)
        await runner.run()
        if current is not None and current.cancelling():
            return


if __name__ == "__main__":
    main()

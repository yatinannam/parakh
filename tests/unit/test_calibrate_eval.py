import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from tools.calibrate_eval.run_text_sim import (
    PLACEHOLDER,
    disable_tracing,
    force_free_models,
    main,
    resolve_config,
)


def _fake_sim_module(calls):
    async def run_simulation(
        bot_model="openai/gpt-4.1",
        user_model="openai/gpt-4.1",
        fallback_judge_model="openai/gpt-5.4-mini",
    ):
        calls.append(
            {
                "bot_model": bot_model,
                "user_model": user_model,
                "fallback_judge_model": fallback_judge_model,
            }
        )
        return "ok"

    mod = types.ModuleType("fake_sim")
    mod.run_simulation = run_simulation  # type: ignore[attr-defined]
    return mod


def test_resolve_config_replaces_placeholder(tmp_path):
    src = tmp_path / "c.json"
    src.write_text(json.dumps({"evaluators": [{"judge_model": PLACEHOLDER}]}), encoding="utf-8")
    out = resolve_config(src, "meta/x:free", tmp_path / "dir with space")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["evaluators"][0]["judge_model"] == "meta/x:free"
    assert PLACEHOLDER not in out.read_text(encoding="utf-8")


def test_shipped_config_is_valid_and_uses_placeholder():
    root = Path(__file__).resolve().parents[2]
    text = (root / "tools" / "calibrate_eval" / "text_sim_config.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert all(e["judge_model"] == PLACEHOLDER for e in data["evaluators"])
    assert data["settings"]["max_turns"] <= 6


def test_refuses_paid_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    argv = ["run_text_sim.py", "--model", "openai/gpt-4.1", "--config", "c", "--out", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 2
    assert "must be an OpenRouter ':free' model id" in capsys.readouterr().err


def test_requires_openrouter_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    argv = ["run_text_sim.py", "--model", "a/b:free", "--config", "c", "--out", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 2
    assert "OPENROUTER_API_KEY not set" in capsys.readouterr().err


def test_force_free_models_overrides_paid_defaults():
    calls = []
    mod = _fake_sim_module(calls)
    force_free_models(mod, "a/b:free")
    result = asyncio.run(mod.run_simulation(bot_model="a/b:free"))
    assert result == "ok"
    assert calls == [
        {"bot_model": "a/b:free", "user_model": "a/b:free", "fallback_judge_model": "a/b:free"}
    ]


def test_force_free_models_refuses_unknown_signature():
    async def run_simulation(bot_model="x"):
        return "ok"

    mod = types.ModuleType("fake_sim")
    mod.run_simulation = run_simulation  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="user_model"):
        force_free_models(mod, "a/b:free")


@pytest.mark.parametrize("value", ["false", "0", "1", ""])
def test_disable_tracing_removes_the_variable(value):
    # Calibrate checks bool(os.getenv("ENABLE_TRACING")), so any non-empty
    # value, including "false", turns tracing on. Only absence disables it.
    env = {"ENABLE_TRACING": value, "OTHER": "kept"}
    disable_tracing(env)
    assert env == {"OTHER": "kept"}


def test_resolve_config_refuses_external_agent(tmp_path):
    # An agent_url config takes Calibrate's run_simulation_with_agent path,
    # which has its own paid defaults that the wrapper does not patch.
    src = tmp_path / "c.json"
    src.write_text(json.dumps({"agent_url": "http://localhost:9000", "evaluators": []}))
    with pytest.raises(ValueError, match="agent_url"):
        resolve_config(src, "a/b:free", tmp_path / "out")
    assert not (tmp_path / "out" / "config.resolved.json").exists()


def test_resolve_config_refuses_paid_judge_model(tmp_path):
    src = tmp_path / "c.json"
    evaluators = [{"judge_model": PLACEHOLDER}, {"judge_model": "openai/gpt-5.4-mini"}]
    src.write_text(json.dumps({"evaluators": evaluators}))
    with pytest.raises(ValueError, match="judge_model"):
        resolve_config(src, "a/b:free", tmp_path / "out")
    assert not (tmp_path / "out" / "config.resolved.json").exists()


def test_main_rejects_unsafe_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    src = tmp_path / "c.json"
    src.write_text(json.dumps({"agent_url": "http://localhost:9000", "evaluators": []}))
    out = tmp_path / "out"
    argv = ["run_text_sim.py", "--model", "a/b:free", "--config", str(src), "--out", str(out)]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 2
    assert "refusing to run" in capsys.readouterr().err

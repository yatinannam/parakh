import json
import sys
from pathlib import Path

from tools.calibrate_eval.run_text_sim import PLACEHOLDER, main, resolve_config


def test_resolve_config_replaces_placeholder(tmp_path):
    src = tmp_path / "c.json"
    src.write_text(json.dumps({"evaluators": [{"judge_model": PLACEHOLDER}]}), encoding="utf-8")
    out = resolve_config(src, "meta/x:free", tmp_path / "dir with space")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["evaluators"][0]["judge_model"] == "meta/x:free"
    assert PLACEHOLDER not in out.read_text(encoding="utf-8")


def test_shipped_config_is_valid_and_uses_placeholder():
    text = Path("tools/calibrate_eval/text_sim_config.json").read_text(encoding="utf-8")
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

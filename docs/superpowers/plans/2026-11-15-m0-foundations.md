# M0 Foundations and Task 1 Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the repo on a tested, CI-checked Python 3.11 base with secret, emoji and knowledge-graph guards, verify the free Groq key, and complete Task 1 by running one Calibrate text simulation in WSL on free models.

**Architecture:** `uv` project with a `src/parakh` package (a CLI stub for now) and a top-level `tools/` package for repo tooling (`no_emoji`, `kg_render`, `check_keys`). Pre-commit and GitHub Actions run the same checks. Calibrate is installed only inside WSL2 Ubuntu, driven by a small MIT wrapper of our own that forces free OpenRouter models.

**Tech Stack:** Python 3.11, uv, Typer, pydantic v2, PyYAML, httpx, python-dotenv, pytest, ruff, pyright, pre-commit, gitleaks, GitHub Actions. WSL2 Ubuntu 24.04 (Python 3.12) for Calibrate.

**Spec:** `docs/superpowers/specs/2026-11-15-parakh-design.md` (sections 3, 7, 9, 10 M0, 11 EC-01/03/14/16/17, 12 D2/D8, 15).

## Global Constraints

- Free only, no card. If any sign-up or install asks for a card, stop and record it (EC-17).
- Python `>=3.11,<3.12` for Parakh (`.python-version` = `3.11`).
- MIT licence. No Calibrate code or text copied into this repo. Calibrate configs here are written from scratch from its public docs.
- Secrets live only in `.env` (Parakh) or `~/calibrate-eval/.env` (WSL). Never printed, logged or committed.
- No emojis anywhere in the project: code, comments, docs, commit messages, CI output.
- Conventional Commits, each ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, pushed to `main`.
- Every task that adds a component, tool, decision or risk adds its node and edges to `docs/kg/graph.yaml`. After Task 4, also re-render `docs/kg/README.md`.
- Line endings LF (`.gitattributes`).

## Review Focus

1. Legitimate non-ASCII text (Devanagari "दो", danda "।", `±`, `×`, em dash, `₹`) must never be flagged as emoji. Test: Task 3 `test_non_emoji_unicode_not_flagged`.
2. Binary or non-UTF-8 tracked files (future `.wav`, `.png`) must be skipped by the emoji scan, not crash it. Test: Task 3 `test_binary_and_undecodable_files_skipped`.
3. Knowledge-graph labels with Mermaid-special characters (`=`, `:`, `(`, `"`, `+`, `/`) must render to valid quoted Mermaid. Test: Task 4 `test_labels_with_special_chars_are_quoted`.
4. A missing `.env`, an empty key, a 401 and a network error must each give a clear message and a non-zero exit, and must never echo the key. Test: Task 6 `test_key_never_printed` plus the parametrised failure test.
5. The repo path contains spaces (`.../Yatin/Projects/parakh` under OneDrive). Tools that take paths must work from a directory with spaces. Tests: Task 3 and Task 4 use `tmp_path / "dir with space"`.

---

### Task 1: Repo hygiene files

**Files:**
- Create: `.gitignore`, `.gitattributes`, `.env.example`, `LICENSE`, `.python-version`

**Interfaces:**
- Produces: ignore rules later tasks rely on (`.env`, `.venv/`, `.cache/`, `runs/`, `data/real/`).

- [ ] **Step 1: Write `.gitignore`**

Entries: `.env`, `!.env.example`, `.venv/`, `.cache/`, `runs/`, `data/real/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `dist/`, `build/`, `*.egg-info/`, `Thumbs.db`, `.DS_Store`.

- [ ] **Step 2: Write `.gitattributes`**

```
* text=auto eol=lf
*.wav binary
*.mp3 binary
*.flac binary
*.png binary
*.jpg binary
```

- [ ] **Step 3: Write `.env.example`**

Keys with empty values and one comment line each: `GROQ_API_KEY=` (agent STT and LLM, judge), `GEMINI_API_KEY=` (judge fallback, M3; synthetic data only). Add a comment that the OpenRouter key lives only in WSL `~/calibrate-eval/.env`.

- [ ] **Step 4: Write `LICENSE`** (standard MIT text, `Copyright (c) 2026 Yatin Annam`) and `.python-version` containing `3.11`.

- [ ] **Step 5: Renormalise line endings and verify**

Run: `git add --renormalize . && git status --short`
Expected: the docs files show as modified (CRLF to LF) or nothing. `git check-ignore -v .env` prints the `.gitignore` rule.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .gitattributes .env.example LICENSE .python-version docs
git commit -m "chore: add repo hygiene files and normalise line endings"
```

---

### Task 2: Python project skeleton with CLI stub

**Files:**
- Create: `pyproject.toml`, `uv.lock` (generated), `src/parakh/__init__.py`, `src/parakh/cli.py`, `tools/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `parakh.__version__: str` = `"0.0.1"`; `parakh.cli.app: typer.Typer`; console script `parakh`; `parakh version` prints `parakh 0.0.1`.

- [ ] **Step 1: Write `pyproject.toml`**

- `[project]` with name `parakh`, version `0.0.1`, `requires-python = ">=3.11,<3.12"`, license `MIT`. Dependencies: `typer>=0.12`, `pydantic>=2.7`, `pyyaml>=6.0`, `httpx>=0.27`, `python-dotenv>=1.0`.
- `[project.scripts] parakh = "parakh.cli:app"`.
- `[dependency-groups] dev = ["pytest>=8", "ruff>=0.6", "pyright>=1.1.380", "pre-commit>=3.7"]`.
- Build backend: hatchling, with `packages = ["src/parakh"]`.
- `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `pythonpath = ["."]` (so `tools` imports).
- `[tool.ruff]`: `line-length = 100`, `target-version = "py311"`; lint `select = ["E","F","I","UP","B","SIM"]`.
- `[tool.pyright]`: `include = ["src","tools","tests"]`, `exclude = ["tools/calibrate_eval"]`, `pythonVersion = "3.11"`, `typeCheckingMode = "standard"`.

- [ ] **Step 2: Write the failing test** in `tests/unit/test_cli.py`

```python
from typer.testing import CliRunner
from parakh import __version__
from parakh.cli import app

def test_version_prints_package_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"parakh {__version__}"
    assert __version__ == "0.0.1"
```

- [ ] **Step 3: Sync and run the test to see it fail**

Run: `uv sync && uv run pytest tests/unit/test_cli.py -v`
Expected: FAIL (ImportError on `parakh.cli`).

- [ ] **Step 4: Implement `src/parakh/__init__.py` (`__version__ = "0.0.1"`) and `src/parakh/cli.py`** with a Typer `app`, a `version()` command, and a no-op callback so Typer keeps `version` as a subcommand.

- [ ] **Step 5: Verify**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run parakh version`
Expected: tests pass, ruff and pyright clean, the last command prints `parakh 0.0.1`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src tools/__init__.py tests
git commit -m "build: add uv project skeleton with parakh CLI stub"
```

---

### Task 3: No-emoji guard

**Files:**
- Create: `tools/no_emoji.py`, `tests/unit/test_no_emoji.py`

**Interfaces:**
- Produces: `find_emoji(text: str) -> list[tuple[int, int, str]]` returning (line, column, character) with 1-based line and column; `scan_paths(paths: list[Path]) -> list[tuple[Path, int, int, str]]`; `main(argv: list[str] | None = None) -> int`. With no args it scans `git ls-files` output; with args it scans those paths. It prints `path:line:col: U+XXXX` per hit and returns 1 on any hit, else 0. Run as `python -m tools.no_emoji`.

- [ ] **Step 1: Write the failing tests**

```python
from tools.no_emoji import find_emoji, scan_paths

def test_plain_text_clean():
    assert find_emoji("Latency p95 is 840 ms.\n") == []

def test_emoji_flagged_with_position():
    assert find_emoji("ok\nall good ✅\n") == [(2, 10, "✅")]

def test_flag_and_star_and_pictograph_flagged():
    hits = find_emoji("\U0001F1EE\U0001F1F3 ⭐ \U0001F680")
    assert {h[2] for h in hits} >= {"\U0001F1EE", "⭐", "\U0001F680"}

def test_variation_selector_flagged():
    assert find_emoji("❤️")  # heart + VS16

def test_non_emoji_unicode_not_flagged():
    assert find_emoji("दो । ±20 ms 2 × 2 — ₹500 kyā") == []

def test_binary_and_undecodable_files_skipped(tmp_path):
    d = tmp_path / "dir with space"; d.mkdir()
    (d / "a.wav").write_bytes(b"RIFF\x00\xff\xfe\x00")
    (d / "b.md").write_text("fine\n", encoding="utf-8")
    (d / "c.md").write_text("bad \U0001F600\n", encoding="utf-8")
    hits = scan_paths([d / "a.wav", d / "b.md", d / "c.md"])
    assert [(p.name, line) for p, line, _, _ in hits] == [("c.md", 1)]
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_no_emoji.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `tools/no_emoji.py`**

Flag these code points: `U+1F000-U+1FAFF`, `U+2600-U+27BF`, `U+2B00-U+2BFF`, `U+231A-U+231B`, `U+2328`, `U+23CF`, `U+23E9-U+23F3`, `U+23F8-U+23FA`, `U+3030`, `U+303D`, `U+3297`, `U+3299`, `U+FE0F`, `U+20E3`. Skip a file if it contains a NUL byte in its first 8 KiB, or if it fails to decode as UTF-8.

- [ ] **Step 4: Verify on the tests and on the repo**

Run: `uv run pytest tests/unit/test_no_emoji.py -v && uv run python -m tools.no_emoji`
Expected: tests pass. The repo scan prints nothing and exits 0. If it finds hits in existing docs, replace those characters with plain text.

- [ ] **Step 5: Add KG node** `t_no_emoji` (type `component`, label `No-emoji guard`, path `tools/no_emoji.py`), with edges `{from: ci, to: t_no_emoji, rel: calls}` and `{from: t_no_emoji, to: m0, rel: delivered_in}`.

- [ ] **Step 6: Commit**

```bash
git add tools/no_emoji.py tests/unit/test_no_emoji.py docs/kg/graph.yaml
git commit -m "feat(tools): add no-emoji guard for tracked files"
```

---

### Task 4: Knowledge-graph renderer and sync check

**Files:**
- Create: `tools/kg_render.py`, `tests/unit/test_kg_render.py`
- Modify: `docs/kg/README.md` (replace the hand-written diagrams with generated blocks between markers), `docs/kg/graph.yaml` (update the header comment)

**Interfaces:**
- Produces:
  - `NodeType = Literal["constraint","component","external","decision","risk","doc","milestone"]`
  - `Rel = Literal["depends_on","calls","produces","consumes","constrained_by","decided_by","mitigates","documented_in","delivered_in","compatible_with"]`
  - pydantic models `Node(id: str, type: NodeType, label: str, summary: str = "", path: str | None = None, by: str | None = None)`, `Edge(from_: str (alias "from"), to: str, rel: Rel)`, `Graph(schema_version: int, updated: str, nodes: list[Node], edges: list[Edge])`
  - `load_graph(path: Path) -> Graph`, which raises `GraphError` on a duplicate id, an edge to an unknown node, or an unknown type or rel
  - `render_views(graph: Graph) -> dict[str, str]`, with keys `"pipeline"`, `"governance"`, `"milestones"`, each a Mermaid `flowchart` string
  - `apply_views(readme_text: str, views: dict[str, str]) -> str`, which replaces each block between `<!-- kg:begin NAME -->` and `<!-- kg:end NAME -->`
  - `main(argv) -> int`, which supports `--check` (exit 1 and print `docs/kg/README.md is out of date; run python -m tools.kg_render` if the result differs) and `--graph PATH --readme PATH` (defaults `docs/kg/graph.yaml`, `docs/kg/README.md`)

View filters:
- `pipeline`: component and external nodes, plus edges among them.
- `governance`: constraint, decision and risk nodes, plus edges that touch at least one of them. The other end is shown too.
- `milestones`: milestone nodes, plus `delivered_in` edges as grouped subgraphs.

Shapes: component `id["label"]`, external `id{{"label"}}`, constraint `id(["label"])`, decision `id[/"label"/]`, risk `id>"label"]`, doc `id[("label")]`, milestone `id(("label"))`. Edge text is the rel. Nodes and edges are sorted by id, so output is deterministic. Inside labels, `"` is replaced with `#quot;`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from tools.kg_render import GraphError, apply_views, load_graph, main, render_views

def write(p, text): p.write_text(text, encoding="utf-8"); return p

G = """schema_version: 1
updated: 2026-11-15
nodes:
  - {id: a, type: component, label: "Caller TTS + cache"}
  - {id: b, type: external, label: "OpenRouter :free"}
  - {id: d, type: decision, label: 'D3 HMS = "hospital" (mgmt)'}
edges:
  - {from: a, to: b, rel: depends_on}
  - {from: a, to: d, rel: decided_by}
"""

def test_duplicate_id_rejected(tmp_path):
    with pytest.raises(GraphError, match="duplicate"):
        load_graph(write(tmp_path / "g.yaml", G.replace("id: b,", "id: a,")))

def test_dangling_edge_rejected(tmp_path):
    with pytest.raises(GraphError, match="unknown node"):
        load_graph(write(tmp_path / "g.yaml", G.replace("to: b,", "to: zz,")))

def test_unknown_rel_rejected(tmp_path):
    with pytest.raises(GraphError):
        load_graph(write(tmp_path / "g.yaml", G.replace("rel: depends_on", "rel: likes")))

def test_labels_with_special_chars_are_quoted(tmp_path):
    views = render_views(load_graph(write(tmp_path / "g.yaml", G)))
    assert 'a["Caller TTS + cache"]' in views["pipeline"]
    assert 'b{{"OpenRouter :free"}}' in views["pipeline"]
    assert "#quot;hospital#quot;" in views["governance"]

def test_render_is_deterministic(tmp_path):
    g = load_graph(write(tmp_path / "g.yaml", G))
    assert render_views(g) == render_views(g)

def test_check_detects_drift_and_write_fixes_it(tmp_path):
    d = tmp_path / "dir with space"; d.mkdir()
    gp = write(d / "g.yaml", G)
    rp = write(d / "README.md", "x\n<!-- kg:begin pipeline -->\nold\n<!-- kg:end pipeline -->\n")
    assert main(["--check", "--graph", str(gp), "--readme", str(rp)]) == 1
    assert main(["--graph", str(gp), "--readme", str(rp)]) == 0
    assert main(["--check", "--graph", str(gp), "--readme", str(rp)]) == 0
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_kg_render.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `tools/kg_render.py`** to the interfaces above. `apply_views` leaves a README block untouched when the README has no markers for that view name.

- [ ] **Step 4: Convert `docs/kg/README.md`**

Replace each of the three hand-written Mermaid blocks with a marker pair (`pipeline`, `governance`, `milestones`) and keep the prose. In `graph.yaml`, change the header comment to say the README views are generated by `python -m tools.kg_render`.

- [ ] **Step 5: Render and verify**

Run: `uv run python -m tools.kg_render && uv run python -m tools.kg_render --check && uv run pytest -q`
Expected: the first command rewrites the README. `--check` exits 0. All tests pass. Open `docs/kg/README.md` and confirm three fenced `mermaid` blocks.

- [ ] **Step 6: Add KG node** `t_kg_render` (component, path `tools/kg_render.py`), with edges `{from: t_kg_render, to: d8, rel: decided_by}`, `{from: ci, to: t_kg_render, rel: calls}` and `{from: t_kg_render, to: m0, rel: delivered_in}`. Re-render.

- [ ] **Step 7: Commit**

```bash
git add tools/kg_render.py tests/unit/test_kg_render.py docs/kg
git commit -m "feat(tools): generate knowledge-graph Mermaid views with sync check"
```

---

### Task 5: Pre-commit and CI

**Files:**
- Create: `.pre-commit-config.yaml`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `python -m tools.no_emoji` (Task 3), `python -m tools.kg_render --check` (Task 4).

- [ ] **Step 1: Write `.pre-commit-config.yaml`**

Hooks:
- `https://github.com/pre-commit/pre-commit-hooks` rev `v5.0.0`: `check-yaml`, `check-toml`, `end-of-file-fixer`, `trailing-whitespace`, `check-added-large-files` with `--maxkb=500`.
- `https://github.com/astral-sh/ruff-pre-commit` rev `v0.6.9`: `ruff` with `--fix`, then `ruff-format`.
- `https://github.com/gitleaks/gitleaks` rev `v8.21.2`: `gitleaks`.
- Local, `language: system`, `pass_filenames: false`: `no-emoji` (`uv run python -m tools.no_emoji`) and `kg-sync` (`uv run python -m tools.kg_render --check`, `files: ^docs/kg/`).

- [ ] **Step 2: Bump revs and install**

Run: `uv run pre-commit autoupdate && uv run pre-commit install && uv run pre-commit run --all-files`
Expected: revs are updated to the latest tags. All hooks pass, or auto-fix and pass on a second run. gitleaks reports no leaks.

- [ ] **Step 3: Write `.github/workflows/ci.yml`**

- Triggers: `push` to `main`, and `pull_request`. Top-level `permissions: contents: read`.
- Job `test`: matrix `os: [ubuntu-latest, windows-latest]`. Steps: `actions/checkout@v4`; `astral-sh/setup-uv@v6` with `python-version: "3.11"`; `uv sync --locked`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run pyright`; `uv run pytest -q`; `uv run python -m tools.no_emoji`; `uv run python -m tools.kg_render --check`.
- Job `secrets`: `ubuntu-latest`; `actions/checkout@v4` with `fetch-depth: 0`; `gitleaks/gitleaks-action@v2` with `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.
- No other secrets are used.

- [ ] **Step 4: Check GitHub secret scanning and push protection**

Run: `gh api repos/yatinannam/parakh --jq .security_and_analysis`
Expected: `secret_scanning` and `secret_scanning_push_protection` are `enabled`. If not, stop and ask Yatin before changing repo settings.

- [ ] **Step 5: Commit, push, watch CI**

```bash
git add .pre-commit-config.yaml .github/workflows/ci.yml docs/kg
git commit -m "ci: add pre-commit hooks and GitHub Actions checks"
git push origin main
gh run watch --exit-status
```

Expected: both `test` jobs and `secrets` pass. Then set the `ci` node summary to `ci.yml: test (ubuntu, windows), secrets (gitleaks); e2e.yml in M4.`, add `{from: ci, to: m0, rel: delivered_in}`, re-render, and commit with `docs(kg): record CI jobs`.

---

### Task 6: API key runbook and Groq key check

**Files:**
- Create: `tools/check_keys.py`, `tests/unit/test_check_keys.py`, `docs/runbooks/api-keys.md`

**Interfaces:**
- Produces:
  - `@dataclass KeyCheck(ok: bool, detail: str, models: list[str])`
  - `check_groq(api_key: str, client: httpx.Client) -> KeyCheck`: sends `GET https://api.groq.com/openai/v1/models` with `Authorization: Bearer <key>` and a 10 s timeout. `ok` is true on HTTP 200. `models` holds the sorted ids. `detail` gives the HTTP status, or the exception class name on a network error.
  - `main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int`: reads `--env` (default `.env`) with python-dotenv. Returns exit 2 with `GROQ_API_KEY not set` if the key is missing or empty, 1 if the check fails, 0 on success. On success it prints `groq: ok (<n> models; whisper-large-v3-turbo: yes|no)`. It never prints the key.

- [ ] **Step 1: Write the failing tests**

```python
import httpx, pytest
from tools.check_keys import check_groq, main

KEY = "gsk_test_SECRET_123"

def client(status, body=None, exc=None):
    def handler(request):
        if exc: raise exc
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        return httpx.Response(status, json=body or {})
    return httpx.Client(transport=httpx.MockTransport(handler))

def test_ok_lists_models():
    r = check_groq(KEY, client(200, {"data": [{"id": "whisper-large-v3-turbo"}, {"id": "a"}]}))
    assert r.ok and r.models == ["a", "whisper-large-v3-turbo"]

@pytest.mark.parametrize("status,exc,detail", [
    (401, None, "401"), (0, httpx.ConnectError("x"), "ConnectError")])
def test_failures(status, exc, detail):
    r = check_groq(KEY, client(status, exc=exc))
    assert not r.ok and detail in r.detail

def test_missing_key_exit_2(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"; env.write_text("GROQ_API_KEY=\n")
    assert main(["--env", str(env)]) == 2
    assert "GROQ_API_KEY not set" in capsys.readouterr().err

def test_key_never_printed(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"; env.write_text(f"GROQ_API_KEY={KEY}\n")
    for c in (client(200, {"data": []}), client(401)):
        main(["--env", str(env)], client=c)
    out = capsys.readouterr()
    assert KEY not in out.out and KEY not in out.err
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_check_keys.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `tools/check_keys.py`** to the interfaces above.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/unit/test_check_keys.py -v`
Expected: PASS.

- [ ] **Step 5: Write `docs/runbooks/api-keys.md`**

Cover:
- Groq: sign up at console.groq.com, create a key, copy `.env.example` to `.env` and fill in `GROQ_API_KEY`. Run `uv run python -m tools.check_keys`. Optionally switch on Zero Data Retention in Groq's Data Controls.
- Gemini: deferred to M3.
- OpenRouter: WSL only, see `calibrate-wsl.md`.
- The no-card rule (EC-17), and what to do if a key leaks (revoke it at the provider first, then rotate it).

- [ ] **Step 6: HUMAN STEP (Yatin): create the Groq account and key, without a card, and put it in `.env`.**

Then run: `uv run python -m tools.check_keys`
Expected: `groq: ok (<n> models; whisper-large-v3-turbo: yes)`. If the answer is `no`, record the Whisper model ids that are available in the runbook, for M1.

- [ ] **Step 7: Add KG nodes** `t_check_keys` (component), `doc_runbook_keys` (doc), with edges `{from: t_check_keys, to: x_groq, rel: calls}`, `{from: t_check_keys, to: c_secrets, rel: constrained_by}`, `{from: x_groq, to: doc_runbook_keys, rel: documented_in}` and `{from: t_check_keys, to: m0, rel: delivered_in}`. Re-render.

- [ ] **Step 8: Commit and push**

```bash
git add tools/check_keys.py tests/unit/test_check_keys.py docs/runbooks/api-keys.md docs/kg
git commit -m "feat(tools): add Groq key check and API key runbook"
git push origin main
```

---

### Task 7: Calibrate text simulation in WSL (Task 1 run)

**Files:**
- Create: `tools/calibrate_eval/README.md`, `tools/calibrate_eval/text_sim_config.json`, `tools/calibrate_eval/run_text_sim.py`, `docs/runbooks/calibrate-wsl.md`
- Modify: `docs/research/2026-11-15-calibrate-analysis.md` (status, run results, final verdict), `docs/kg/graph.yaml`

**Interfaces:**
- `run_text_sim.py` runs **only inside WSL**, against a separately installed `calibrate-agent==0.0.81`. It is excluded from pyright (Task 2 config). Usage: `python run_text_sim.py --model <free id> --config text_sim_config.json --out <dir>`.

Background, found while writing this plan: Calibrate's internal text simulation passes `--model` only to the agent. The simulated user keeps the default `user_model="openai/gpt-4.1"`, a paid model (`calibrate_agent/llm/run_simulation.py`, the `run_simulation(... bot_model=args.model ...)` call). A free run therefore needs our wrapper, which replaces the module attribute `calibrate_agent.llm.run_simulation.run_simulation` with an async wrapper that sets `user_model` to the free model, then calls `calibrate_agent.cli.main()`. Because the CLI looks up `run_simulation` as a module global at call time, the patch takes effect.

- [ ] **Step 1: Write `text_sim_config.json` from scratch** (synthetic, our own words, schema from Calibrate's public docs)

Contents:
- `system_prompt`: a short receptionist prompt for "Parakh Clinic", which books appointments with Dr. Rao or Dr. Iyer.
- `tools`: `[]`.
- `personas`: one persona, `{label: "hinglish caller", characteristics: "You speak Hinglish (Hindi-English code-mixed, Roman script). You want an appointment with Dr. Rao tomorrow morning. Your phone number is 9845012345.", gender: "female", language: "english"}`.
- `scenarios`: one scenario, `{name: "book follow-up", description: "Ask for a follow-up with Dr. Rao tomorrow around 10:30 and give your number when asked."}`.
- `evaluators`: one, `{name: "booked_correctly", type: "binary", system_prompt: "<own words: did the agent confirm a booking with Dr. Rao, tomorrow around 10:30, for 9845012345?>", judge_model: "__FREE_MODEL__"}`.
- `settings`: `{agent_speaks_first: true, max_turns: 6}`.

- [ ] **Step 2: Write `run_text_sim.py`**

It loads the config, replaces `"__FREE_MODEL__"` with `--model`, and writes the result to `<out>/config.resolved.json`. It applies the `user_model` patch described above, sets `sys.argv` to `["calibrate-agent", "simulations", "--type", "text", "-c", <resolved>, "-m", <model>, "-p", "openrouter", "-o", <out>]`, then calls `calibrate_agent.cli.main()`. It sets `os.environ["ENABLE_TRACING"] = "false"` before importing Calibrate.

- [ ] **Step 3: Write `docs/runbooks/calibrate-wsl.md` and `tools/calibrate_eval/README.md`**

The runbook holds the exact commands of Steps 4-8. The README is a three-line pointer: it says the folder holds MIT wrapper code that drives a separately installed CC-BY-SA package, and that no Calibrate code is included.

- [ ] **Step 4: HUMAN STEP (Yatin), in a WSL terminal:**

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev build-essential libasound2-dev
```

- [ ] **Step 5: HUMAN STEP (Yatin): create a free OpenRouter account and key, without a card. Store it only in WSL:**

```bash
mkdir -p ~/calibrate-eval && printf 'OPENROUTER_API_KEY=%s\n' '<key>' > ~/calibrate-eval/.env && chmod 600 ~/calibrate-eval/.env
```

- [ ] **Step 6: Install Calibrate in WSL and confirm the paid default**

Run (via `wsl.exe -d Ubuntu -- bash -lc '...'`):
`cd ~/calibrate-eval && python3 -m venv .venv && .venv/bin/pip install calibrate-agent==0.0.81 && grep -n "bot_model=args.model" .venv/lib/python3.12/site-packages/calibrate_agent/llm/run_simulation.py`
Expected: the install succeeds (if `simpleaudio` fails to build, record the error and retry with `pip install --no-deps calibrate-agent==0.0.81` plus every dependency except `simpleaudio`). The grep shows the call. If it does not, re-read the installed source and update the wrapper.

- [ ] **Step 7: Pick a free model**

Run: `curl -s https://openrouter.ai/api/v1/models | python3 -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin)['data'] if m['id'].endswith(':free')]"`
Expected: a list of ids. Prefer an instruction-tuned model of 70B parameters or more. Record the chosen id in the runbook.

- [ ] **Step 8: Run the simulation** (about 15 requests, within the roughly 50 per day free cap)

Run: `cd ~/calibrate-eval && set -a && . ./.env && set +a && .venv/bin/python /mnt/c/Users/ninja/OneDrive/Documents/Yatin/Projects/parakh/tools/calibrate_eval/run_text_sim.py --model <id> --config /mnt/c/Users/ninja/OneDrive/Documents/Yatin/Projects/parakh/tools/calibrate_eval/text_sim_config.json --out ~/calibrate-eval/out-1`
Expected: Calibrate prints a transcript and the `booked_correctly` result. Exit code 0. On a 402 or 429, record the exact error line and stop. Do not buy credits.

- [ ] **Step 9: Record results** in `docs/research/2026-11-15-calibrate-analysis.md`

- Set `Status` to done.
- Add a "Run" section: date, Calibrate version, model id, number of requests used, turns, evaluator result, and a short excerpt of the synthetic transcript.
- Add the new finding: the simulated user's model has no CLI flag and defaults to paid `openai/gpt-4.1`.
- State the final verdict: D1 confirmed, or the reason it is not.

- [ ] **Step 10: Add KG nodes** `t_calibrate_eval` (component, path `tools/calibrate_eval`) and `doc_runbook_calibrate` (doc), with edges `{from: t_calibrate_eval, to: x_calibrate, rel: calls}`, `{from: t_calibrate_eval, to: x_openrouter, rel: calls}`, `{from: t_calibrate_eval, to: d2, rel: decided_by}`, `{from: x_calibrate, to: doc_runbook_calibrate, rel: documented_in}` and `{from: t_calibrate_eval, to: m0, rel: delivered_in}`. Re-render.

- [ ] **Step 11: Commit and push**

```bash
git add tools/calibrate_eval docs/runbooks/calibrate-wsl.md docs/research docs/kg
git commit -m "docs(research): run Calibrate text simulation on free models"
git push origin main
```

---

### Task 8: README, docs index, milestone close-out

**Files:**
- Create: `README.md`
- Modify: `docs/README.md`, `docs/kg/graph.yaml`, `docs/kg/README.md`, `docs/superpowers/specs/2026-11-15-parakh-design.md` (only if M0 changed a fact)

- [ ] **Step 1: Write `README.md`** (technical, professional, no emojis)

Sections:
1. One-paragraph summary.
2. Status: M0 complete, M1 next.
3. What Parakh measures: latency, script-tolerant WER, task success, judge.
4. Architecture: the pipeline in one paragraph plus a link to the KG.
5. Requirements: Windows or Linux, Python 3.11, uv, ffmpeg.
6. Development setup: `uv sync`, `uv run pre-commit install`, `uv run pytest`.
7. Repository layout.
8. Documentation links.
9. Constraints: free tiers only, synthetic data only.
10. License: MIT, plus a note on the clean-room relationship with Calibrate.

- [ ] **Step 2: Update `docs/README.md`** with the runbooks and plans rows.

- [ ] **Step 3: Close the milestone in the KG.** Set `updated:`, give the `m0` node a summary that says it is complete, and re-render.

- [ ] **Step 4: Verify everything**

Run: `uv run pre-commit run --all-files && uv run pytest -q && uv run python -m tools.kg_render --check`
Expected: all pass.

- [ ] **Step 5: Commit, push, confirm CI**

```bash
git add README.md docs
git commit -m "docs: add project README and close out M0"
git push origin main
gh run watch --exit-status
```

Expected: CI green.

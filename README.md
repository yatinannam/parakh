# Parakh

Parakh is a test harness, under construction, for voice agents that serve Indian callers. It is designed to play a scripted synthetic caller to an agent over a Pipecat-protocol WebSocket, degrade the caller's audio to telephone quality, inject interruptions, and score each call on response latency, script-tolerant word error rate on Hinglish (Hindi-English code-mixed) speech, task success against a mock hospital management system, and an advisory LLM-judge rating. It targets a CPU-only laptop and free API tiers only.

## Status

| Milestone | Scope | State |
|---|---|---|
| M0 | Repository hygiene, CI, tooling, Task 1 evaluation of Calibrate | Complete (2026-11-16) |
| M1 | MVP: one scenario, clean audio, a Pipecat test agent, latency and WER | Next |
| M2 | Degradation presets (phone codec, noise, packet loss) and interruptions | Planned |
| M3 | Indic layer: script-tolerant scorer, Hinglish scenario pack, LLM judge; then Kannada-English and Tamil-English | Planned |
| M4 | Mock HMS adapter for deterministic task success; end-to-end CI workflow | Planned |
| M5 | Public release: scenario pack, comparison run | Planned |

The `parakh` command currently only reports its version. The pipeline below is the design being built from M1 onwards.

## What Parakh measures

| Metric | Definition |
|---|---|
| Response latency | Per turn: first agent audio frame above -45 dBFS after the caller's speech end, minus the caller's speech end. Reported as p50, p90, p95 and max per run and per preset. Barge-in stop latency (time for the agent to go quiet after the caller cuts in) from M2. |
| Word error rate | Strict WER (NFC, lowercase, punctuation stripped) and loose WER/CER from a script-tolerant normaliser that matches Devanagari and Roman spellings of the same word, number forms and common variants. The headline is conversation-level loose WER on the agent's own transcript. |
| Task success | Deterministic: the mock HMS's final state is compared field by field with the scenario's expected state (doctor, date, time, phone). Pass or fail with a diff. |
| LLM judge | A rubric rating from a free-tier LLM (Groq first, Gemini fallback), on synthetic transcripts only. Advisory: it never decides a pass. |

## Architecture

A scenario YAML file defines the caller's script and the expected end state. Parakh synthesises the caller's turns with edge-tts and caches them by content hash, then applies a seeded degradation preset (band-limit, 8 kHz resampling, G.711 mu-law, noise at a set SNR, packet loss). The call driver streams the audio in real-time 20 ms frames to the agent under test over a WebSocket using Pipecat's protobuf frame protocol, runs the turn-taking and barge-in logic, and records both directions with timestamps. After the call, the scorers compute latency, WER, task success and the judge rating, and write `report.json` (versioned schema) and a self-contained `report.html`.

```
scenario YAML -> caller TTS + cache -> degrader -> call driver <-> agent under test -> mock HMS
                                                       |
                                                       v
                                 recorded audio + events -> scorers -> report.json, report.html
```

Because the transport speaks Pipecat's protocol, the same test agent can be exercised by Parakh and by Pipecat-based tools such as Calibrate. Scoring runs after the call ends, so local models never compete with the live call for CPU.

Details: design spec, [section 5](docs/superpowers/specs/2026-11-15-parakh-design.md#5-architecture). Component, decision and risk relationships: [knowledge graph](docs/kg/README.md).

## Requirements

- Windows 10 or 11, or Linux. CI runs on `windows-latest` and `ubuntu-latest`.
- Python 3.11 (pinned in `.python-version`).
- [uv](https://docs.astral.sh/uv/) 0.11 or later.
- Git.
- ffmpeg on `PATH` (from M1, for audio decoding and degradation).
- A free Groq API key (from M1). No credit or debit card is needed for anything in this project.
- Hardware target: a 4-core or larger CPU with 16 GB RAM. No GPU is used.
- WSL2 only if you want to repeat the Calibrate comparison ([runbook](docs/runbooks/calibrate-wsl.md)).

## Development setup

```
git clone https://github.com/yatinannam/parakh.git
cd parakh
uv sync
uv run pre-commit install
uv run pytest
uv run parakh version
```

API keys go in `.env`, which is gitignored. Copy `.env.example` to `.env`, set `GROQ_API_KEY`, and check it with `uv run python -m tools.check_keys`. The check lists models only and never prints the key. See the [API keys runbook](docs/runbooks/api-keys.md).

Checks, and where each runs. Pre-commit runs on every commit; run the type check and tests yourself before pushing, or let CI catch them.

| Check | Command | Pre-commit | CI |
|---|---|---|---|
| Lint | `uv run ruff check .` | yes (with `--fix`) | yes |
| Format | `uv run ruff format --check .` | yes (formats) | yes |
| Types | `uv run pyright` | no | yes |
| Tests | `uv run pytest -q` | no | yes |
| No emoji in tracked files | `uv run python -m tools.no_emoji` | yes | yes |
| Knowledge-graph views in sync | `uv run python -m tools.kg_render --check` | yes | yes |
| Secret scan | gitleaks | yes | yes (full history) |
| YAML, TOML, whitespace, large files | pre-commit-hooks | yes | no |

GitHub Actions and pre-commit hooks are pinned to full commit SHAs, and a unit test fails on any unpinned one. Dependabot proposes Action updates weekly. See [CONTRIBUTING.md](CONTRIBUTING.md) for the working rules.

## Repository layout

```
src/parakh/            Package. M0: CLI entry point only.
tests/unit/            Unit tests.
tools/                 Development tools: no_emoji, kg_render, check_keys.
tools/calibrate_eval/  MIT wrapper and synthetic config for the Calibrate comparison (WSL only).
docs/                  Spec, plans, research, runbooks, knowledge graph.
.github/               CI workflow and Dependabot config.
```

Planned packages (scenario, tts, degrade, transport, score, judge, budget, report, adapters), the test agent (`agents/clinic_agent`) and the mock HMS (`services/mock_hms`) are listed in [spec section 7](docs/superpowers/specs/2026-11-15-parakh-design.md#7-repo-layout).

## Documentation

| Document | Contents |
|---|---|
| [docs/README.md](docs/README.md) | Index of all project documentation. |
| [Design spec](docs/superpowers/specs/2026-11-15-parakh-design.md) | Goals, architecture, components, testing, CI, milestones, edge-case register, decisions. |
| [Calibrate analysis](docs/research/2026-11-15-calibrate-analysis.md) | Task 1: what Calibrate covers and lacks, the free-model run, and the verdict. |
| [Free-tier and platform notes](docs/research/2026-11-15-free-tier-and-platform-notes.md) | Provider limits and data policies, Windows wheel checks, local model notes. |
| [Knowledge graph](docs/kg/README.md) | `graph.yaml` plus generated Mermaid views of the pipeline, governance and milestones. |
| [Runbooks](docs/runbooks/) | API keys; Calibrate in WSL. |

## Constraints

- **Free tiers only.** Groq and Gemini free tiers; OpenRouter `:free` models only for the Calibrate comparison. Any step that asks for a card is out of scope.
- **Synthetic data only to hosted LLM APIs.** Some free tiers may train on inputs. Scenarios, caller scripts and patient records are synthetic. Real recordings (a person reading synthetic scripts) stay on the local machine under `data/real/`, which is gitignored, and are transcribed locally.
- **No secrets in git.** `.env` is gitignored, gitleaks runs in pre-commit and CI, and GitHub push protection is on.
- **CPU only.** Local models (faster-whisper small int8, later Indic Parler-TTS) run on CPU and never at the same time.
- **No emoji** in any tracked file, enforced by `tools/no_emoji.py`.

## Relationship to Calibrate

[Calibrate](https://github.com/ARTPARK-SAHAI-ORG/calibrate) (ARTPARK-SAHAI) is a Pipecat-based evaluation framework for text and voice agents. Task 1 reviewed its source and ran one of its text simulations on free models. It covers persona simulation, interruptions and mean latency. It does not cover telephone-channel degradation, script-tolerant code-mixed scoring for external agents, deterministic task success, latency distributions, or a voice path that runs on free tiers. Parakh is therefore a standalone tool that stays protocol-compatible with Calibrate. The full findings are in the [Calibrate analysis](docs/research/2026-11-15-calibrate-analysis.md).

This is a clean-room relationship. Calibrate is licensed CC-BY-SA-4.0, and no Calibrate code is copied into this repository. `tools/calibrate_eval/` contains only MIT code that imports a separately installed copy of `calibrate-agent` inside WSL, for the comparison run.

## License

MIT. See [LICENSE](LICENSE).

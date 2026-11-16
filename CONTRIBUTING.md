# Contributing to Parakh

Parakh is a personal project maintained by Yatin. These rules apply to every change, including changes made with AI assistance.

## Clean-room rule for Calibrate

[Calibrate](https://github.com/ARTPARK-SAHAI-ORG/calibrate) is licensed CC-BY-SA-4.0. Parakh is MIT. Code derived from Calibrate cannot be relicensed as MIT, so:

- Never copy, paste, translate or paraphrase Calibrate code into this repository, not even a few lines, a test fixture or a config schema.
- Read Calibrate's source only to understand behaviour, and describe what you learn in your own words with a file path for reference, as in [`docs/research/2026-11-15-calibrate-analysis.md`](docs/research/2026-11-15-calibrate-analysis.md).
- Clone or install Calibrate only outside this repository: in a scratch directory or in WSL (see [`docs/runbooks/calibrate-wsl.md`](docs/runbooks/calibrate-wsl.md)). Never add it as a dependency of Parakh.
- `tools/calibrate_eval/` is the only place that touches Calibrate. It holds MIT code that imports a separately installed copy at run time; it contains no Calibrate code.
- Shared ground is the Pipecat protocol. Use `pipecat-ai` (BSD-2) as a dependency; never copy its code either.

The same applies to other copyleft sources: edge-tts (LGPL-3.0) is used unmodified as a dependency and never vendored, and noise datasets under share-alike licences stay out of the repository (spec EC-62 to EC-64).

## Hard constraints

- **Free tiers only.** No step may need a credit or debit card or a paid tier. If a provider asks for a card, stop.
- **Synthetic data only to hosted APIs.** Scenarios, scripts and patient records are synthetic. Real recordings stay in `data/real/` (gitignored) and are transcribed locally.
- **No secrets in git.** Keys live in `.env` (gitignored). Never paste a key into an issue, a commit, a log or a chat. If a key leaks, follow [`docs/runbooks/api-keys.md`](docs/runbooks/api-keys.md).
- **CPU only.** Local models run on CPU, and heavy models never run at the same time.
- **No emoji** in any tracked file, commit message or output. `tools/no_emoji.py` enforces this for files.

## Workflow

1. `uv sync`, then `uv run pre-commit install` once per clone.
2. Write the failing test first, watch it fail, then write the code that makes it pass.
3. Before pushing, run what pre-commit does not: `uv run pyright` and `uv run pytest -q`. CI runs every check on Ubuntu and Windows.
4. Update the docs with the change: the spec when a fact or decision changes, the edge-case register for new edge cases, runbooks for new manual steps, and `docs/README.md` for new documents.
5. Update the knowledge graph (`docs/kg/graph.yaml`) for new components, decisions, risks or documents, then run `uv run python -m tools.kg_render`.
6. Commit with [Conventional Commits](https://www.conventionalcommits.org/) messages and push to `main`.

## Supply chain

GitHub Actions and pre-commit hooks are pinned to full commit SHAs with the version in a comment; `tests/unit/test_supply_chain_pins.py` fails on any unpinned one. To update hook pins, run `uv run pre-commit autoupdate --freeze` and make sure the ruff hook version still matches the ruff version in `uv.lock`.

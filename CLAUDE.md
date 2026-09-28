# fiduciaire-agent

## Purpose
Swiss fiduciary pre-accounting demo, built for a job application (junior software
architect for a Geneva fiduciary). QR-bills and camt.053 in; deterministic code reads, reconciles,
controls and builds every entry; a Claude agent classifies over MCP what no rule covers; a person
approves every entry. Design decisions in `docs/adr/`, real agent runs in `docs/essais.md`.

## Stack
Python 3.13, uv, SQLite (stdlib), MCP Python SDK 2.x. No other runtime dependency.

## Commands
- Install: `uv sync`
- Demo: `uv run fidu demo`, then `fidu anomalies`, `fidu proposees`, `fidu a-classer`, `fidu evaluer`
- MCP server: `uv run fidu-mcp` (stdio, database from `FIDU_BASE`)
- Test: `uv run pytest -q`

## Invariants (tests enforce them, do not weaken)
- The MCP server exposes no tool that approves or rejects an entry.
- Entries are only built by `ledger.py`; the agent sends a classification, never lines.
- The demo's controls find exactly the seven planted anomalies, nothing else.
- All data is fictitious and every name carries « Démo »; never add a real company or person.

## Definition of done
Run all of these before saying a task is finished (work loop: ~/.claude/CLAUDE.md):
- `uv run ruff check .` and `uv run ruff format --check .` pass (ruff locked in uv.lock, rules in pyproject.toml)
- `uv run pytest -q` passes
- CI (.github/workflows/ci.yml) runs the same checks on every push; `.py` files are auto-formatted after each edit (hook)

## Conventions
- Code, commits and file names in English; user-facing text (CLI, MCP messages, README, ADR) in French for a francophone fiduciary. Small, focused commits.
- Tests in `tests/` (Python) or next to the code (Node), mirroring the modules they cover.
- Secrets only in `.env` (git-ignored); document variables in `.env.example`.

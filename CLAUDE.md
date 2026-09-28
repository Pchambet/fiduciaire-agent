# fiduciaire-agent

## Purpose
TODO — what this project does, for whom, and what "done" looks like.

## Stack
python

## Commands
- Install: `uv sync`
- Run: `uv run fiduciaire-agent`
- Test: `uv run pytest`
- Add a dependency: `uv add <pkg>`

## Definition of done
Run all of these before saying a task is finished (work loop: ~/.claude/CLAUDE.md):
- `uv run ruff check .` and `uv run ruff format --check .` pass (ruff locked in uv.lock, rules in pyproject.toml)
- `uv run pytest -q` passes
- CI (.github/workflows/ci.yml) runs the same checks on every push; `.py` files are auto-formatted after each edit (hook)

## Conventions
- Code, commits and file names in English; small, focused commits.
- Tests in `tests/` (Python) or next to the code (Node), mirroring the modules they cover.
- Secrets only in `.env` (git-ignored); document variables in `.env.example`.

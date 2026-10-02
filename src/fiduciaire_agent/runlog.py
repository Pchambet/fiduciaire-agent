"""An agent run, read from its stream-json transcript.

The first evaluation table was copied by hand from this output and the transcripts were not
kept, so only its scores can be re-checked. `fidu essai` keeps the transcript and derives every
column from it, so that a later run can be checked line by line.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# System events describe the local setup (paths, plugins, sockets), not the run, so the kept copy
# leaves them out. The model is also on every assistant message.
KEPT_EVENTS = ("assistant", "user", "result")
USAGE = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _events(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    return (json.loads(line) for line in lines if line.strip())


def summarize(lines: Iterable[str]) -> dict[str, Any]:
    """The columns of the README table, from `claude -p ... --output-format stream-json --verbose`.

    A tool result flagged as an error counts as a server refusal: the agent runs with `--tools ""`,
    so every tool it can call belongs to the MCP server, which refuses by raising `ToolError`.
    """
    model, calls, refusals, result = None, set(), set(), None
    for event in _events(lines):
        if event.get("type") == "result":
            result = event
        elif event.get("type") in ("assistant", "user"):
            message = event["message"]
            model = model or message.get("model")
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_use":
                    calls.add(block["id"])
                elif block.get("type") == "tool_result" and block.get("is_error"):
                    refusals.add(block["tool_use_id"])
    if result is None:
        raise ValueError(
            "aucun événement result : l'essai n'est pas allé au bout, "
            "ou ce n'est pas une sortie stream-json"
        )
    usage = result.get("usage", {})
    return {
        "model": model,
        "finished": result.get("subtype") == "success" and not result.get("is_error"),
        "tool_calls": len(calls),
        "server_refusals": len(refusals),
        "turns": result["num_turns"],
        "duration_s": round(result["duration_ms"] / 1000, 1),
        "cost_usd": round(result["total_cost_usd"], 4),
        **{key: usage.get(key) for key in USAGE},
    }


def record(transcript: Path, folder: Path, score: dict[str, Any]) -> dict[str, Any]:
    """Keep the transcript in `folder` and append its row to `folder/results.jsonl`.

    `score` is `books.evaluate` on the books the run left behind, so record a run before anyone
    approves or rejects its entries.
    """
    lines = transcript.read_text(encoding="utf-8").splitlines()
    summary = summarize(lines)
    today = dt.datetime.now(dt.UTC).date().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while (
        copy := folder / f"{today}-{summary['model'] or 'unknown'}-{n}.jsonl"
    ).exists():
        n += 1
    kept = [
        line
        for line in lines
        if line.strip() and json.loads(line).get("type") in KEPT_EVENTS
    ]
    copy.write_text("\n".join(kept) + "\n", encoding="utf-8")
    row = {
        "date": today,
        "transcript": copy.name,
        "correct": score["justes"],
        "total": score["total"],
        **summary,
    }
    with (folder / "results.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row

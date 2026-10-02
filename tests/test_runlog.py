"""Reading an agent run from its stream-json transcript instead of copying numbers by hand."""

import json

import pytest

from fiduciaire_agent import books, runlog
from fiduciaire_agent.cli import main

MODEL = "claude-test-1"


def _assistant(message_id, *blocks):
    return {
        "type": "assistant",
        "message": {"id": message_id, "model": MODEL, "content": list(blocks)},
    }


def _call(call_id):
    return {"type": "tool_use", "id": call_id, "name": "mcp__fiduciaire__a_classer"}


def _answer(call_id, refused=False):
    block = {"type": "tool_result", "tool_use_id": call_id, "content": "…"}
    if refused:
        block["is_error"] = True
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def _transcript():
    """Three tool calls (two in one message, streamed as separate events), one refused."""
    return [
        {"type": "system", "subtype": "init", "model": MODEL, "cwd": "/home/someone"},
        _assistant("m1", {"type": "text", "text": "Je commence."}),
        _assistant("m1", _call("t1")),
        _answer("t1"),
        _assistant("m2", _call("t2")),
        _assistant("m2", _call("t3")),
        _answer("t2", refused=True),
        _answer("t3"),
        _assistant("m3", {"type": "text", "text": "Résumé."}),
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 4,
            "duration_ms": 41_960,
            "total_cost_usd": 0.141234,
            "usage": {
                "input_tokens": 30,
                "output_tokens": 2_000,
                "cache_read_input_tokens": 50_000,
                "cache_creation_input_tokens": 9_000,
            },
        },
    ]


def _lines(events):
    return [json.dumps(e) + "\n" for e in events]


def test_summary_reads_every_column_of_the_table():
    assert runlog.summarize(_lines(_transcript())) == {
        "model": MODEL,
        "finished": True,
        "tool_calls": 3,
        "server_refusals": 1,
        "turns": 4,
        "duration_s": 42.0,
        "cost_usd": 0.1412,
        "input_tokens": 30,
        "output_tokens": 2_000,
        "cache_read_input_tokens": 50_000,
        "cache_creation_input_tokens": 9_000,
    }


def test_unfinished_run_is_refused():
    with pytest.raises(ValueError, match="result"):
        runlog.summarize(_lines(_transcript()[:-1]))


def test_essai_keeps_the_transcript_and_appends_the_score(world, tmp_path, capsys):
    _, db = world
    books.propose(db, "F-hotel-7730", "6640", None, "Nuitées d'un séminaire client")
    base = db.execute("PRAGMA database_list").fetchone()["file"]
    raw = tmp_path / "run.jsonl"
    raw.write_text("".join(_lines(_transcript())), encoding="utf-8")
    runs = tmp_path / "runs"

    assert main(["--base", base, "essai", str(raw), "--dossier", str(runs)]) == 0
    assert main(["--base", base, "essai", str(raw), "--dossier", str(runs)]) == 0

    results = [json.loads(x) for x in (runs / "results.jsonl").read_text().splitlines()]
    assert len(results) == 2
    first = results[0]
    assert (first["correct"], first["total"], first["tool_calls"]) == (1, 9, 3)
    kept = (runs / first["transcript"]).read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["type"] for x in kept][-1] == "result"
    assert "/home/someone" not in "".join(kept)  # system events record local paths
    assert runlog.summarize(kept)["tool_calls"] == 3  # the kept copy can be re-checked
    # a second run never overwrites the first one's transcript
    assert results[1]["transcript"] != first["transcript"]
    assert '"correct": 1' in capsys.readouterr().out

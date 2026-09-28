"""The MCP server, driven the way Claude drives it: by an MCP client, in memory and over stdio."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client import Client

from fiduciaire_agent.mcp_server import create_server

TOOLS = {
    "situation",
    "pieces_a_classer",
    "plan_comptable",
    "anomalies",
    "expliquer_piece",
    "proposer_ecriture",
}


def run(server, scenario):
    async def go():
        async with Client(server) as client:
            return await scenario(client)

    return asyncio.run(go())


def db_path(db) -> Path:
    return Path(db.execute("PRAGMA database_list").fetchone()["file"])


def test_six_tools_and_no_way_to_approve(db):
    async def scenario(c):
        return (await c.list_tools()).tools

    tools = run(create_server(db_path(db)), scenario)
    assert {t.name for t in tools} == TOOLS
    assert {t.name for t in tools if not t.annotations.read_only_hint} == {
        "proposer_ecriture"
    }
    assert not any(
        word in t.name for t in tools for word in ("valid", "approuv", "rejet")
    )
    assert all(t.description for t in tools)


def test_agent_classifies_and_the_entry_stays_proposed(db):
    async def scenario(c):
        todo = (await c.call_tool("pieces_a_classer", {})).structured_content
        r = await c.call_tool(
            "proposer_ecriture",
            {
                "piece": "F-hotel-7730",
                "compte": "6640",
                "justification": "Nuitées d'un séminaire client",
            },
        )
        return todo, r

    todo, r = run(create_server(db_path(db)), scenario)
    assert todo["total"] == 9
    assert not r.is_error and r.structured_content["statut"] == "proposée"


def test_refusals_come_back_as_readable_tool_errors(db):
    async def scenario(c):
        return await c.call_tool(
            "proposer_ecriture",
            {
                "piece": "F-hotel-7730",
                "compte": "6640",
                "code_tva": "TVA81",
                "justification": "Nuitées",
            },
        )

    r = run(create_server(db_path(db)), scenario)
    assert r.is_error and "justification" in r.content[0].text


def test_missing_database_is_explained(tmp_path):
    async def scenario(c):
        return await c.call_tool("situation", {})

    r = run(create_server(tmp_path / "absente.db"), scenario)
    assert r.is_error and "fidu demo" in r.content[0].text


def test_runs_as_a_stdio_subprocess(db):
    """The real transport: the protocol goes through stdin and stdout, so nothing else may be printed there."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "fiduciaire_agent.mcp_server"],
        env={"PATH": os.environ["PATH"], "FIDU_BASE": str(db_path(db))},
    )

    async def scenario(c):
        return (await c.call_tool("situation", {})).structured_content

    assert run(params, scenario)["a_classer"] == 9

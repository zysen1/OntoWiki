"""MCP server. Tools: wiki_query, wiki_claim, wiki_provenance, wiki_at, wiki_lint."""

from __future__ import annotations

from pathlib import Path

from ontowiki.mcp_server.handlers import (
    as_json,
    wiki_at,
    wiki_claim,
    wiki_lint,
    wiki_provenance,
    wiki_query,
)
from ontowiki.service import Workspace

TOOL_NAMES = ("wiki_query", "wiki_claim", "wiki_provenance", "wiki_at", "wiki_lint")


def build_server(workspace: str | Path):
    from mcp.server.fastmcp import FastMCP

    wiki = Workspace(workspace)
    mcp = FastMCP(
        name="OntoWiki",
        instructions=(
            "OntoWiki is an ontology-constrained, bi-temporal wiki compiled on top of llmwiki. "
            "Use wiki_query for questions, wiki_at to see what was believed on a date, "
            "wiki_claim and wiki_provenance to inspect a claim, and wiki_lint to list "
            "contradictions, stale claims, and orphan pages. Lint does not change the graph."
        ),
    )

    @mcp.tool(name="wiki_query", description="Answer from the compiled wiki. Pass as_of (YYYY-MM-DD) for transaction time.")
    def query(question: str, as_of: str = "", depth: int = 3) -> str:
        return as_json(wiki_query(wiki, question, as_of or None, depth))

    @mcp.tool(name="wiki_claim", description="List active claims for a subject, optionally filtered by predicate and as_of.")
    def claim(subject: str, predicate: str = "", as_of: str = "") -> str:
        return as_json(wiki_claim(wiki, subject, predicate or None, as_of or None))

    @mcp.tool(name="wiki_provenance", description="Return a claim plus every source episode and quote that supports it.")
    def provenance(claim_id: str) -> str:
        return as_json(wiki_provenance(wiki, claim_id))

    @mcp.tool(name="wiki_at", description="Snapshot of claims believed at a transaction time (YYYY-MM-DD).")
    def at(time: str) -> str:
        return as_json(wiki_at(wiki, time))

    @mcp.tool(name="wiki_lint", description="Contradictions, stale claims, and orphan pages for review. Does not edit the wiki.")
    def lint(as_of: str = "") -> str:
        return as_json(wiki_lint(wiki, as_of or None))

    return mcp


def registered_tool_names(server) -> set[str]:
    tools = server._tool_manager.list_tools()
    if isinstance(tools, dict):
        return set(tools)
    return {tool.name for tool in tools}

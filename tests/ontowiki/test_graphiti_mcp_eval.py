import asyncio
import json
from pathlib import Path

import pytest

from ontowiki.compile.compiler import compile_workspace
from ontowiki.demo.export import build_timeline, contradiction_pairs_at, visible_claim_ids
from ontowiki.eval.harness import run_eval
from ontowiki.kg.graphiti_backend import episode_kwargs, graphiti_schema
from ontowiki.mcp_server.handlers import wiki_claim, wiki_provenance, wiki_query
from ontowiki.ontology.schema import load_ontology
from ontowiki.paths import bundled_ontology, bundled_sources, committed_eval, committed_timeline
from ontowiki.service import Workspace


def test_graphiti_schema_and_episode_payload():
    ontology = load_ontology(bundled_ontology())
    schema = graphiti_schema(ontology)
    assert "Paper" in schema["entity_types"]
    assert "INTRODUCES" in schema["edge_types"]
    assert "INTRODUCES" in schema["edge_type_map"][("Paper", "Concept")]
    kwargs = episode_kwargs(
        title="HippoRAG 2",
        prose="HippoRAG 2 introduces associative retrieval.",
        source_path="2025-02-20-hipporag2.md",
        published="2025-02-20",
        claims=[
            {
                "subject": "HippoRAG 2",
                "predicate": "INTRODUCES",
                "object": "Associative retrieval",
                "quote": "HippoRAG 2 introduces associative retrieval.",
            }
        ],
        ontology=ontology,
    )
    assert kwargs["reference_time"].tzinfo is not None
    assert "Validated claims" in kwargs["episode_body"]
    assert kwargs["entity_types"]["Paper"].__name__ == "Paper"

    class Fake:
        def __init__(self):
            self.calls = []

        async def add_episode(self, **payload):
            self.calls.append(payload)

    from ontowiki.kg.graphiti_backend import GraphitiMirror

    fake = Fake()
    mirror = GraphitiMirror(fake, ontology)
    asyncio.run(
        mirror.sync_source(
            title=kwargs["name"],
            prose="HippoRAG 2 introduces associative retrieval.",
            source_path="2025-02-20-hipporag2.md",
            published="2025-02-20",
            claims=[],
        )
    )
    assert fake.calls[0]["group_id"] == "ontowiki"
    assert fake.calls[0]["reference_time"].isoformat().startswith("2025-02-20")


def test_mcp_handlers_answer_and_show_provenance(tmp_path: Path):
    compile_workspace(bundled_ontology(), bundled_sources(), tmp_path)
    workspace = Workspace(tmp_path)
    try:
        result = wiki_query(
            workspace,
            "What implementation status did the notes record for the LLM Wiki idea?",
            as_of="2026-04-04",
        )
        assert result["answer"] == "no open implementation"
        claims = wiki_claim(workspace, "LLM Wiki", predicate="HAS_OPEN_IMPLEMENTATION", as_of="2026-04-04")
        assert len(claims) == 1
        provenance = wiki_provenance(workspace, claims[0]["id"])
        assert provenance["provenance"][0]["quote"]
        assert provenance["claim"]["source"] == "2026-04-04-karpathy-gist.md"
    finally:
        workspace.close()


def test_mcp_server_registers_tools(tmp_path: Path):
    pytest.importorskip("mcp")
    compile_workspace(bundled_ontology(), bundled_sources(), tmp_path)
    from ontowiki.mcp_server.server import TOOL_NAMES, build_server, registered_tool_names

    server = build_server(tmp_path)
    assert set(TOOL_NAMES) <= registered_tool_names(server)


def test_eval_is_deterministic_and_matches_committed_artifact():
    first = run_eval()
    second = run_eval()
    assert first == second
    assert first["lightrag"]["status"] == "not_run"
    saved = json.loads(committed_eval().read_text(encoding="utf-8"))
    assert first == saved


def test_timeline_grows_and_matches_committed_artifact():
    data = build_timeline()
    assert data["ticks"][0] == "2025-02-20"
    early = "2026-05-20"
    late = "2026-06-11"
    assert contradiction_pairs_at(data, early) == []
    assert contradiction_pairs_at(data, late)
    early_objects = _objects(data, early)
    late_objects = _objects(data, late)
    assert "no open implementation" in early_objects
    assert "open implementation of the LLM Wiki idea" not in early_objects
    assert "no open implementation" not in _objects(data, "2026-10-14")
    assert "open implementation of the LLM Wiki idea" in late_objects
    saved = json.loads(committed_timeline().read_text(encoding="utf-8"))
    assert data == saved


def _objects(data: dict, time: str) -> set[str]:
    visible = set(visible_claim_ids(data, time))
    return {claim["object"] for claim in data["claims"] if claim["id"] in visible}

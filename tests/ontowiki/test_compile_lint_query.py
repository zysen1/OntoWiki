import json
from pathlib import Path

from ontowiki.compile.compiler import compile_workspace
from ontowiki.lint.agent import LintAgent, write_review
from ontowiki.ontology.validate import validate_page
from ontowiki.paths import bundled_ontology, bundled_sources
from ontowiki.query.ask import ask
from ontowiki.service import Workspace


def _compile(tmp_path: Path) -> Workspace:
    report = compile_workspace(bundled_ontology(), bundled_sources(), tmp_path)
    assert report.ok, report.rejected
    assert report.accepted > 0
    assert report.contradictions == 1
    assert report.superseded >= 1
    return Workspace(tmp_path)


def test_bundled_corpus_compiles_valid_pages(tmp_path: Path):
    workspace = _compile(tmp_path)
    try:
        pages = list(workspace.wiki_dir.rglob("*.md"))
        assert any(path.name == "hipporag-2.md" for path in pages)
        paper = next(path for path in pages if path.name == "hipporag-2.md")
        text = paper.read_text(encoding="utf-8")
        assert validate_page(text, workspace.ontology) == []
        assert "associative retrieval" in text.lower()
        hippo = workspace.store.entity_by_name("HippoRAG 2")
        assert hippo is not None
        assert hippo.properties["arxiv_id"] == "2502.14802"
    finally:
        workspace.close()


def test_bad_claim_is_rejected_and_does_not_enter_the_graph(tmp_path: Path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "bad.md").write_text(
        """---
title: Bad
published: 2024-01-01
---

A grounded sentence that the quote will not match.

```ontowiki
entities:
  - type: Paper
    name: Example Paper
  - type: Concept
    name: Example Concept
claims:
  - subject: Example Paper
    predicate: INTRODUCES
    object: Example Concept
    valid_from: 2024-01-01
    quote: "this quote was never written in the prose"
```
""",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    report = compile_workspace(bundled_ontology(), sources, out)
    assert not report.ok
    assert report.accepted == 0
    workspace = Workspace(out)
    try:
        assert workspace.store.all_claims() == []
    finally:
        workspace.close()


def test_lint_finds_contradiction_stale_and_orphan(tmp_path: Path):
    workspace = _compile(tmp_path)
    try:
        (workspace.wiki_dir / "loose.md").write_text("# Loose\n\nNobody links here.\n", encoding="utf-8")
        report = LintAgent(workspace.store, workspace.ontology, workspace.wiki_dir).run("2026-10-19")
        counts = report.counts
        assert counts["contradiction"] >= 1
        assert counts["stale"] >= 1
        assert counts["orphan"] >= 2
        path = write_review(report, workspace.wiki_dir)
        text = path.read_text(encoding="utf-8")
        assert "Review only" in text
        assert "Freshness questions" in text
        saved = json.loads((workspace.wiki_dir / "_lint" / "review.json").read_text(encoding="utf-8"))
        assert saved["as_of"] == "2026-10-19"
    finally:
        workspace.close()


def test_query_respects_transaction_time_and_disclosure_depth(tmp_path: Path):
    workspace = _compile(tmp_path)
    try:
        early = ask(
            workspace.store,
            "What implementation status did the notes record for the LLM Wiki idea?",
            as_of="2026-04-04",
        )
        late = ask(
            workspace.store,
            "What implementation status did the notes record for the LLM Wiki idea?",
            as_of="2026-10-19",
        )
        assert early.answer == "no open implementation"
        assert late.answer == "open implementation of the LLM Wiki idea"
        assert early.sources == ["2026-04-04-karpathy-gist.md"]
        assert late.sources == ["2026-06-02-llmwiki-ships.md"]
        shallow = ask(workspace.store, "What concept does HippoRAG 2 introduce?", depth=0)
        deep = ask(workspace.store, "What concept does HippoRAG 2 introduce?", depth=3)
        assert deep.answer == "Associative retrieval"
        assert len(deep.disclosure) > len(shallow.disclosure)
        assert "Evidence" in deep.disclosure
        assert "Evidence" not in shallow.disclosure
        paper = ask(workspace.store, "Which paper constrains GraphRAG with an ontology constraint?")
        assert paper.answer == "BEACON-SP"
    finally:
        workspace.close()

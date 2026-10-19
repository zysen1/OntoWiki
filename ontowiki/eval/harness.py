"""Compare OntoWiki with plain vector RAG on the bundled reading notes.

LightRAG is reported as not-run unless a later change actually executes it.
This module never invents a score.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ontowiki.compile.compiler import compile_workspace
from ontowiki.eval.vector_rag import index_sources, retrieve
from ontowiki.paths import bundled_ontology, bundled_qa, bundled_sources, committed_eval
from ontowiki.query.ask import ask
from ontowiki.service import Workspace
from ontowiki.text import estimate_tokens

K = 3

METRIC_NOTES = {
    "answer_hit": "1 when the gold answer string appears in the system answer, case-insensitive.",
    "source_recall": (
        "Fraction of gold source filenames among the sources the system used. "
        "OntoWiki cites the episodes of the claims it answered from. "
        "Vector RAG cites its top-3 chunks."
    ),
    "traceable": "1 when the source that produced the answer is one of the gold sources.",
    "context_tokens": "Estimated tokens (characters/4) in the context the system returned for that question.",
    "vector_rag": (
        "TF-IDF over source prose. The ontology block is stripped before indexing. "
        "The answer is the best-overlapping sentence in the top chunk. as_of is ignored."
    ),
    "ontowiki": (
        "Answer comes from ontology-checked claims filtered by transaction time (as_of). "
        "Context is the progressive-disclosure bundle: index, answer, valid time, quote."
    ),
    "lightrag": "Left not-run. LightRAG needs an LLM endpoint; this harness does not fabricate that run.",
}


def run_eval(
    *,
    ontology: Path | None = None,
    sources: Path | None = None,
    qa_path: Path | None = None,
) -> dict:
    ontology = ontology or bundled_ontology()
    sources = sources or bundled_sources()
    questions = json.loads((qa_path or bundled_qa()).read_text(encoding="utf-8"))["questions"]
    chunks = index_sources(sources)
    with tempfile.TemporaryDirectory() as tmp:
        compile_workspace(ontology, sources, tmp)
        workspace = Workspace(tmp)
        try:
            details = [_one(workspace, chunks, question) for question in questions]
        finally:
            workspace.close()
    return {
        "corpus": "agent-research",
        "questions": len(details),
        "vector_rag_k": K,
        "notes": METRIC_NOTES,
        "ontowiki": _aggregate(details, "ontowiki"),
        "vector_rag": _aggregate(details, "vector_rag"),
        "lightrag": _lightrag_status(),
        "details": details,
    }


def _one(workspace: Workspace, chunks, question: dict) -> dict:
    as_of = question.get("as_of")
    onto = ask(workspace.store, question["question"], as_of=as_of, depth=3)
    rag = retrieve(chunks, question["question"], k=K)
    gold = question["gold_answer"]
    gold_sources = question["gold_sources"]
    return {
        "id": question["id"],
        "question": question["question"],
        "as_of": as_of,
        "gold_answer": gold,
        "gold_sources": gold_sources,
        "ontowiki": _grade(gold, gold_sources, onto.answer, onto.sources, onto.sources[:1], onto.disclosure),
        "vector_rag": _grade(
            gold,
            gold_sources,
            rag.answer,
            rag.sources,
            [rag.answer_source] if rag.answer_source else [],
            rag.context,
        ),
    }


def _grade(
    gold: str,
    gold_sources: list[str],
    answer: str,
    sources: list[str],
    answer_sources: list[str],
    context: str,
) -> dict:
    names = [_name(source) for source in sources]
    answer_names = [_name(source) for source in answer_sources]
    recall = 0.0 if not gold_sources else round(sum(1 for source in gold_sources if source in names) / len(gold_sources), 4)
    return {
        "answer": answer,
        "sources": names,
        "answer_hit": int(gold.lower() in answer.lower()) if answer else 0,
        "source_recall": recall,
        "traceable": int(any(source in gold_sources for source in answer_names)),
        "context_tokens": estimate_tokens(context),
    }


def _aggregate(details: list[dict], system: str) -> dict:
    count = len(details) or 1
    hits = sum(row[system]["answer_hit"] for row in details)
    recall = sum(row[system]["source_recall"] for row in details) / count
    traceable = sum(row[system]["traceable"] for row in details)
    tokens = sum(row[system]["context_tokens"] for row in details) / count
    return {
        "answer_hit": round(hits / count, 4),
        "source_recall": round(recall, 4),
        "traceable": round(traceable / count, 4),
        "mean_context_tokens": round(tokens, 1),
    }


def _lightrag_status() -> dict:
    if os.environ.get("ONTOWIKI_LIGHTRAG") != "1":
        return {
            "status": "not_run",
            "reason": (
                "LightRAG was not executed. Set ONTOWIKI_LIGHTRAG=1 only when an LLM endpoint "
                "and a built LightRAG index are available. No score is invented in their place."
            ),
        }
    try:
        import lightrag  # noqa: F401
    except ImportError as exc:
        return {"status": "not_run", "reason": f"ONTOWIKI_LIGHTRAG=1 but lightrag did not import ({exc})."}
    return {
        "status": "not_run",
        "reason": "lightrag imports, but this harness has no LLM-backed index build, so it still refuses to score it.",
    }


def _name(path: str) -> str:
    return Path(path).name


def dump_eval(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def committed_matches(payload: dict | None = None) -> bool:
    path = committed_eval()
    if not path.exists():
        return False
    live = payload if payload is not None else run_eval()
    saved = json.loads(path.read_text(encoding="utf-8"))
    return live == saved

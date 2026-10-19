"""Timeline snapshot for the web demo.

The clock is the source's published date, replayed in order, so scrubbing the
timeline does not depend on the wall clock of the machine that compiled it.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ontowiki.compile.compiler import compile_workspace
from ontowiki.kg.models import Claim
from ontowiki.kg.store import SqliteTemporalKG, stable_id
from ontowiki.lint.agent import LintAgent
from ontowiki.paths import bundled_ontology, bundled_sources, committed_timeline
from ontowiki.service import Workspace


def build_timeline(
    ontology: Path | None = None,
    sources: Path | None = None,
) -> dict:
    ontology = ontology or bundled_ontology()
    sources = sources or bundled_sources()
    with tempfile.TemporaryDirectory() as tmp:
        compile_workspace(ontology, sources, tmp)
        workspace = Workspace(tmp)
        try:
            return snapshot(workspace.store, LintAgent(workspace.store, workspace.ontology, workspace.wiki_dir).run())
        finally:
            workspace.close()


def snapshot(store: SqliteTemporalKG, lint) -> dict:
    claims = store.all_claims()
    nodes = _nodes(store, claims)
    return {
        "ontology": "agent-research",
        "clock": "source-published-date",
        "ticks": _ticks(store),
        "nodes": nodes,
        "claims": [_claim(claim) for claim in claims],
        "contradictions": [
            {"id": row.id, "claimA": row.claim_a, "claimB": row.claim_b, "detectedAt": row.detected_at}
            for row in store.contradictions()
        ],
        "lint": [
            {
                "kind": finding.kind,
                "severity": finding.severity,
                "message": finding.message,
                "suggestion": finding.suggestion,
                "claimIds": finding.claim_ids,
                "paths": finding.paths,
                "visibleFrom": finding.visible_from,
            }
            for finding in lint.findings
        ],
    }


def visible_claim_ids(data: dict, time: str, *, show_history: bool = False) -> list[str]:
    visible: list[str] = []
    for claim in data["claims"]:
        if claim["ingestedAt"] > time:
            continue
        invalidated = claim["invalidatedAt"]
        if invalidated and invalidated <= time and not show_history:
            continue
        visible.append(claim["id"])
    return visible


def contradiction_pairs_at(data: dict, time: str, *, show_history: bool = False) -> list[tuple[str, str]]:
    visible = set(visible_claim_ids(data, time, show_history=show_history))
    pairs: list[tuple[str, str]] = []
    for row in data["contradictions"]:
        if row["claimA"] in visible and row["claimB"] in visible:
            pairs.append((row["claimA"], row["claimB"]))
    return pairs


def dump_timeline(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def committed_timeline_matches(payload: dict | None = None) -> bool:
    path = committed_timeline()
    if not path.exists():
        return False
    live = payload if payload is not None else build_timeline()
    saved = json.loads(path.read_text(encoding="utf-8"))
    return live == saved


def _ticks(store: SqliteTemporalKG) -> list[str]:
    return sorted({episode.ingested_at for episode in store.episodes()})


def _nodes(store: SqliteTemporalKG, claims: list[Claim]) -> list[dict]:
    nodes: list[dict] = []
    for entity in store.entities():
        touching = [claim for claim in claims if claim.subject_id == entity.id or claim.object_id == entity.id]
        if not touching:
            continue
        nodes.append(
            {
                "id": entity.id,
                "label": entity.name,
                "type": entity.type,
                "firstSeen": min(claim.ingested_at for claim in touching),
            }
        )
    literals: dict[str, list[Claim]] = {}
    for claim in claims:
        if claim.object_id is None and claim.object_literal:
            literals.setdefault(_literal_id(claim.value_key), []).append(claim)
    for node_id, group in sorted(literals.items()):
        nodes.append(
            {
                "id": node_id,
                "label": group[0].object_literal,
                "type": "Literal",
                "firstSeen": min(claim.ingested_at for claim in group),
            }
        )
    nodes.sort(key=lambda node: (node["firstSeen"], node["label"]))
    return nodes


def _claim(claim: Claim) -> dict:
    target = claim.object_id or _literal_id(claim.value_key)
    return {
        "id": claim.id,
        "source": claim.subject_id,
        "target": target,
        "predicate": claim.predicate,
        "subject": claim.subject_name,
        "object": claim.object_display,
        "validFrom": claim.valid_from,
        "validTo": claim.valid_to,
        "ingestedAt": claim.ingested_at,
        "invalidatedAt": claim.invalidated_at,
        "status": claim.status,
        "quote": claim.quote,
        "episode": Path(claim.episode_path).name,
        "episodeTitle": claim.episode_title,
        "reviewAfter": claim.review_after,
    }


def _literal_id(value_key: str) -> str:
    return "lit:" + stable_id("literal", value_key)

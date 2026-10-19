"""MCP tool bodies. They stay importable without the MCP SDK."""

from __future__ import annotations

import json

from ontowiki.lint.agent import LintAgent, render_review
from ontowiki.query.ask import ask
from ontowiki.service import Workspace, claim_to_dict


def wiki_query(workspace: Workspace, question: str, as_of: str | None = None, depth: int = 3) -> dict:
    return ask(workspace.store, question, as_of=as_of or None, depth=depth).to_dict()


def wiki_claim(
    workspace: Workspace,
    subject: str,
    predicate: str | None = None,
    as_of: str | None = None,
) -> list[dict]:
    claims = workspace.store.claims_as_of(as_of or None)
    matched = [claim for claim in claims if subject.lower() in claim.subject_name.lower()]
    if predicate:
        folded = predicate.lower()
        matched = [claim for claim in matched if claim.predicate.lower() == folded]
    return [claim_to_dict(claim) for claim in matched]


def wiki_provenance(workspace: Workspace, claim_id: str) -> dict:
    claim = workspace.store.claim(claim_id)
    if claim is None:
        return {"error": f"no claim {claim_id}"}
    rows = workspace.store.provenance(claim_id)
    return {
        "claim": claim_to_dict(claim),
        "provenance": [
            {
                "episode": row.episode_path,
                "title": row.episode_title,
                "quote": row.quote,
            }
            for row in rows
        ],
    }


def wiki_at(workspace: Workspace, time: str) -> dict:
    claims = workspace.store.claims_as_of(time)
    return {"as_of": time, "claims": [claim_to_dict(claim) for claim in claims]}


def wiki_lint(workspace: Workspace, as_of: str | None = None) -> dict:
    report = LintAgent(workspace.store, workspace.ontology, workspace.wiki_dir).run(as_of or None)
    return {
        "as_of": report.as_of,
        "counts": report.counts,
        "review": render_review(report),
        "findings": [finding.to_dict() for finding in report.findings],
    }


def as_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)

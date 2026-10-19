"""Open a compiled workspace. Shared by the CLI, MCP server, and lint."""

from __future__ import annotations

from pathlib import Path

from ontowiki.kg.models import Claim
from ontowiki.kg.store import SqliteTemporalKG
from ontowiki.ontology.schema import Ontology, load_ontology


class Workspace:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        graph = self.path / ".ontowiki" / "graph.sqlite"
        ontology_path = self.path / ".ontowiki" / "ontology.yaml"
        if not graph.exists() or not ontology_path.exists():
            raise FileNotFoundError(
                f"{self.path} is not a compiled OntoWiki workspace. Run `python -m ontowiki compile` first."
            )
        self.ontology: Ontology = load_ontology(ontology_path)
        self.store = SqliteTemporalKG(graph)
        self.wiki_dir = self.path / "wiki"

    def close(self) -> None:
        self.store.close()


def claim_to_dict(claim: Claim) -> dict:
    return {
        "id": claim.id,
        "subject": claim.subject_name,
        "subject_type": claim.subject_type,
        "predicate": claim.predicate,
        "object": claim.object_display,
        "valid_from": claim.valid_from,
        "valid_to": claim.valid_to,
        "ingested_at": claim.ingested_at,
        "invalidated_at": claim.invalidated_at,
        "status": claim.status,
        "quote": claim.quote,
        "source": Path(claim.episode_path).name,
        "review_after": claim.review_after,
    }

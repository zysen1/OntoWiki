"""Optional sync into Graphiti (getzep/graphiti, Apache-2.0).

Graphiti is a bi-temporal graph for agent memory: ``add_episode`` records a
``reference_time`` and later invalidates edges whose facts no longer hold.
That is the right long-term backend when a deployment already runs Neo4j or
FalkorDB and an LLM.

It is not the default here, for three reasons:

* Graphiti's extractor is an LLM. OntoWiki already accepts a claim only after
  ontology validation and a grounded quote, and CI cannot depend on an API key.
* The reference deployment needs Neo4j, FalkorDB, Neptune, or Kuzu. The
  timeline demo and the test suite have to run with no extra service.
* The SQLite store already keeps valid time and transaction time, and it
  invalidates instead of overwriting. That is the contract we need from Graphiti.

When ``GRAPHITI_NEO4J_URI`` is set and ``graphiti-core`` imports, the compiler
can mirror each source. The mirror passes ontology-derived ``entity_types``
and ``edge_types`` through to ``add_episode`` (Graphiti has supported those
hooks since the custom-ontology API). SQLite stays the audit log that lint
reads. Graphiti may still re-extract; treat it as a serving index, not as the
source of truth, unless you have checked the two graphs against each other.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, create_model

from ontowiki.dates import as_utc
from ontowiki.ontology.schema import Ontology


def graphiti_schema(ontology: Ontology) -> dict[str, Any]:
    """Pydantic types shaped the way ``Graphiti.add_episode`` expects them."""
    entity_types: dict[str, type[BaseModel]] = {}
    for name, spec in ontology.entity_types.items():
        fields: dict[str, Any] = {}
        for prop_name, prop in spec.properties.items():
            annotation = {"string": str, "integer": int, "number": float, "boolean": bool}[prop.type]
            if prop.required:
                fields[prop_name] = (annotation, ...)
            else:
                fields[prop_name] = (annotation | None, None)
        entity_types[name] = create_model(name, __base__=BaseModel, **fields)

    edge_types: dict[str, type[BaseModel]] = {}
    edge_type_map: dict[tuple[str, str], list[str]] = {}
    for name, relation in ontology.relation_types.items():
        edge_types[name] = create_model(
            name,
            __base__=BaseModel,
            fact=(str, Field(description=relation.description or name)),
        )
        for source in relation.source:
            for target in relation.target:
                edge_type_map.setdefault((source, target), []).append(name)
    return {
        "entity_types": entity_types,
        "edge_types": edge_types,
        "edge_type_map": edge_type_map,
    }


def episode_kwargs(
    *,
    title: str,
    prose: str,
    source_path: str,
    published: str,
    claims: list[dict[str, str]],
    ontology: Ontology,
    group_id: str = "ontowiki",
) -> dict[str, Any]:
    """Arguments for ``Graphiti.add_episode`` that stay inside the public API."""
    bullets = "\n".join(
        f"- {claim['subject']} {claim['predicate']} {claim['object']} | {claim['quote']}" for claim in claims
    )
    body = prose.strip()
    if bullets:
        body = f"{body}\n\nValidated claims:\n{bullets}"
    schema = graphiti_schema(ontology)
    return {
        "name": title,
        "episode_body": body,
        "source_description": source_path,
        "reference_time": as_utc(published),
        "group_id": group_id,
        "entity_types": schema["entity_types"],
        "edge_types": schema["edge_types"],
        "edge_type_map": schema["edge_type_map"],
        "custom_extraction_instructions": (
            "Prefer the validated claims listed in the episode. "
            f"Stay inside the {ontology.name} ontology. "
            "Do not invent entities or relations that the episode does not state."
        ),
    }


class GraphitiMirror:
    """Sequential ``add_episode`` calls. The client is injected so tests need no server."""

    def __init__(self, client: Any, ontology: Ontology, group_id: str = "ontowiki"):
        self.client = client
        self.ontology = ontology
        self.group_id = group_id

    async def sync_source(
        self,
        *,
        title: str,
        prose: str,
        source_path: str,
        published: str,
        claims: list[dict[str, str]],
    ) -> datetime:
        kwargs = episode_kwargs(
            title=title,
            prose=prose,
            source_path=source_path,
            published=published,
            claims=claims,
            ontology=self.ontology,
            group_id=self.group_id,
        )
        await self.client.add_episode(**kwargs)
        return kwargs["reference_time"]


def client_from_env() -> Any | None:
    """Build a Graphiti client when the process is configured for Neo4j. Else None."""
    uri = os.environ.get("GRAPHITI_NEO4J_URI")
    if not uri:
        return None
    try:
        from graphiti_core import Graphiti
    except ImportError:
        return None
    user = os.environ.get("GRAPHITI_NEO4J_USER", "neo4j")
    password = os.environ.get("GRAPHITI_NEO4J_PASSWORD", "")
    return Graphiti(uri, user, password)

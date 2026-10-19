"""Records stored in the temporal graph."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    name: str
    properties: dict
    created_at: str


@dataclass(frozen=True)
class Episode:
    id: str
    source_path: str
    title: str
    published: str
    ingested_at: str


@dataclass(frozen=True)
class Claim:
    id: str
    subject_id: str
    subject_name: str
    subject_type: str
    predicate: str
    object_id: str | None
    object_name: str | None
    object_literal: str | None
    fact_key: str
    value_key: str
    valid_from: str
    valid_to: str | None
    ingested_at: str
    invalidated_at: str | None
    episode_id: str
    episode_path: str
    episode_title: str
    quote: str
    status: str
    review_after: str | None

    @property
    def object_display(self) -> str:
        return self.object_name or self.object_literal or ""


@dataclass(frozen=True)
class Provenance:
    claim_id: str
    episode_id: str
    episode_path: str
    episode_title: str
    quote: str


@dataclass(frozen=True)
class Contradiction:
    id: str
    claim_a: str
    claim_b: str
    detected_at: str


@dataclass(frozen=True)
class UpsertResult:
    claim_id: str
    action: str
    contradicted: tuple[str, ...] = ()

"""Pluggable ontology: entity types, relation types, and aliases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

ConflictPolicy = Literal["coexist", "supersede", "contradict"]


class PropertySpec(BaseModel):
    type: Literal["string", "integer", "number", "boolean"] = "string"
    required: bool = False


class EntityType(BaseModel):
    description: str = ""
    folder: str = "entities"
    properties: dict[str, PropertySpec] = Field(default_factory=dict)


class RelationType(BaseModel):
    description: str = ""
    source: list[str]
    target: list[str] = Field(default_factory=list)
    functional: bool = False
    on_conflict: ConflictPolicy = "coexist"
    allow_literal: bool = False
    literal_type: Literal["string", "integer", "number", "boolean"] = "string"
    stale_after_days: int | None = None

    @field_validator("on_conflict", mode="before")
    @classmethod
    def _policy(cls, value: str) -> str:
        if value not in {"coexist", "supersede", "contradict"}:
            raise ValueError(f"unknown on_conflict: {value}")
        return value


class AliasTable(BaseModel):
    entity_types: dict[str, str] = Field(default_factory=dict)
    predicates: dict[str, str] = Field(default_factory=dict)


class Ontology(BaseModel):
    name: str
    version: str = "1"
    description: str = ""
    entity_types: dict[str, EntityType]
    relation_types: dict[str, RelationType]
    aliases: AliasTable = Field(default_factory=AliasTable)

    def entity_type(self, name: str) -> str | None:
        if name in self.entity_types:
            return name
        lowered = {key.lower(): key for key in self.entity_types}
        if name.lower() in lowered:
            return lowered[name.lower()]
        mapped = self.aliases.entity_types.get(name) or self.aliases.entity_types.get(name.lower())
        if mapped in self.entity_types:
            return mapped
        return None

    def predicate(self, name: str) -> str | None:
        if name in self.relation_types:
            return name
        upper = name.upper()
        if upper in self.relation_types:
            return upper
        mapped = self.aliases.predicates.get(name) or self.aliases.predicates.get(name.lower())
        if mapped in self.relation_types:
            return mapped
        return None

    def relation(self, predicate: str) -> RelationType:
        canonical = self.predicate(predicate)
        if canonical is None:
            raise KeyError(predicate)
        return self.relation_types[canonical]


def load_ontology(path: str | Path) -> Ontology:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"ontology at {path} is not a mapping")
    return Ontology.model_validate(raw)


def dump_ontology(ontology: Ontology) -> dict[str, Any]:
    return ontology.model_dump()

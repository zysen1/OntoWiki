"""Deterministic repair, with an optional LLM pass for what rules cannot fix."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ontowiki.dates import normalize_date
from ontowiki.ontology.schema import Ontology
from ontowiki.ontology.validate import Issue, validate_claim, validate_entity

LLMRepair = Callable[[dict[str, Any]], dict[str, Any]]


class RuleRepairer:
    """Normalize case, aliases, dates, and entity names. Never invents a quote."""

    def __init__(self, ontology: Ontology):
        self.ontology = ontology

    def repair_entity(self, raw: dict, known: dict[str, str]) -> tuple[dict, list[str]]:
        notes: list[str] = []
        repaired = dict(raw)
        type_name = self.ontology.entity_type(str(repaired.get("type") or ""))
        if type_name and type_name != repaired.get("type"):
            notes.append(f"entity type {repaired.get('type')!r} -> {type_name}")
            repaired["type"] = type_name
        name = str(repaired.get("name") or "").strip()
        canonical = _match_known(name, known)
        declared = self.ontology.entity_type(str(repaired.get("type") or ""))
        if canonical and canonical != name and known.get(canonical) == declared:
            notes.append(f"entity name {name!r} -> {canonical}")
            repaired["name"] = canonical
        else:
            repaired["name"] = name
        spec = self.ontology.entity_types.get(repaired.get("type"))
        properties = dict(repaired.get("properties") or {})
        if spec is not None:
            cleaned, property_notes = _clean_properties(properties, spec.properties)
            notes.extend(property_notes)
            repaired["properties"] = cleaned
        return repaired, notes

    def repair_claim(self, raw: dict, known: dict[str, str]) -> tuple[dict, list[str]]:
        notes: list[str] = []
        repaired = dict(raw)
        predicate = self.ontology.predicate(str(repaired.get("predicate") or ""))
        if predicate and predicate != repaired.get("predicate"):
            notes.append(f"predicate {repaired.get('predicate')!r} -> {predicate}")
            repaired["predicate"] = predicate
        for field in ("subject", "object"):
            value = str(repaired.get(field) or "").strip()
            if not value:
                continue
            canonical = _match_known(value, known)
            if canonical and canonical != value and self._accepts(field, canonical, known, repaired):
                notes.append(f"{field} {value!r} -> {canonical}")
                repaired[field] = canonical
            else:
                repaired[field] = value
        for field in ("valid_from", "valid_to", "review_after"):
            if not repaired.get(field):
                continue
            normalized = normalize_date(str(repaired[field]))
            if normalized and normalized != str(repaired[field]):
                notes.append(f"{field} {repaired[field]!r} -> {normalized}")
                repaired[field] = normalized
            elif normalized:
                repaired[field] = normalized
        if repaired.get("quote"):
            repaired["quote"] = str(repaired["quote"]).strip()
        return repaired, notes

    def _accepts(self, field: str, canonical: str, known: dict[str, str], repaired: dict) -> bool:
        if field != "object":
            return True
        predicate = repaired.get("predicate")
        relation = self.ontology.relation_types.get(predicate) if isinstance(predicate, str) else None
        matched = known.get(canonical)
        if relation is None or matched is None or not relation.target:
            return True
        return matched in relation.target


class LLMRepairer:
    """Ask an injected client to rewrite a claim. The caller validates again."""

    def __init__(self, client: LLMRepair):
        self.client = client

    def repair_claim(self, raw: dict, issues: list[Issue]) -> tuple[dict, list[str]]:
        if not issues:
            return raw, []
        try:
            fixed = self.client({"claim": raw, "issues": [issue.message for issue in issues]})
        except Exception as exc:  # noqa: BLE001 — injected clients fail in many ways
            return raw, [f"llm repair failed: {exc}"]
        if not isinstance(fixed, dict):
            return raw, ["llm repair returned a non-object"]
        merged = dict(raw)
        merged.update(fixed)
        return merged, ["llm repair applied"]


def repair_until_valid(
    raw: dict,
    ontology: Ontology,
    known: dict[str, str],
    prose: str,
    llm: LLMRepairer | None = None,
) -> tuple[dict | None, list[str], list[Issue]]:
    """Rule-repair, validate, optionally LLM-repair once, validate again."""
    rules = RuleRepairer(ontology)
    repaired, notes = rules.repair_claim(raw, known)
    issues = validate_claim(repaired, ontology, known, prose)
    if issues and llm is not None:
        repaired, llm_notes = llm.repair_claim(repaired, issues)
        notes.extend(llm_notes)
        follow, follow_notes = rules.repair_claim(repaired, known)
        notes.extend(follow_notes)
        repaired = follow
        issues = validate_claim(repaired, ontology, known, prose)
    if issues:
        return None, notes, issues
    return repaired, notes, []


def repair_entity_until_valid(
    raw: dict,
    ontology: Ontology,
    known: dict[str, str],
) -> tuple[dict | None, list[str], list[Issue]]:
    rules = RuleRepairer(ontology)
    repaired, notes = rules.repair_entity(raw, known)
    issues = validate_entity(repaired, ontology)
    if issues:
        return None, notes, issues
    return repaired, notes, []


def _match_known(name: str, known: dict[str, str]) -> str | None:
    if name in known:
        return name
    folded = {key.lower(): key for key in known}
    return folded.get(name.lower())


def _clean_properties(properties: dict, spec: dict) -> tuple[dict, list[str]]:
    notes: list[str] = []
    cleaned: dict = {}
    for key, value in properties.items():
        prop = spec.get(key)
        if prop is None:
            notes.append(f"dropped unknown property {key}")
            continue
        coerced = _coerce(value, prop.type)
        if coerced is None:
            notes.append(f"dropped {key}: cannot coerce to {prop.type}")
            continue
        cleaned[key] = coerced
    return cleaned, notes


def _coerce(value, type_name: str):
    if type_name == "string":
        return value if isinstance(value, str) else str(value)
    if type_name == "integer":
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        return None
    if type_name == "number":
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            return None
        try:
            return float(value)
        except ValueError:
            return None
    if type_name == "boolean" and isinstance(value, bool):
        return value
    return None

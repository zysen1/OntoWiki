"""Validate claims and generated pages against an ontology."""

from __future__ import annotations

from dataclasses import dataclass

from ontowiki.dates import normalize_date
from ontowiki.ontology.schema import Ontology

_PY_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


def validate_entity(raw: dict, ontology: Ontology) -> list[Issue]:
    issues: list[Issue] = []
    name = str(raw.get("name") or "").strip()
    if not name:
        issues.append(Issue("entity_name", "entity name is empty"))
    type_name = ontology.entity_type(str(raw.get("type") or ""))
    if type_name is None:
        issues.append(Issue("entity_type", f"unknown entity type {raw.get('type')!r}"))
        return issues
    spec = ontology.entity_types[type_name]
    properties = raw.get("properties") or {}
    if not isinstance(properties, dict):
        issues.append(Issue("properties", "properties must be a mapping"))
        return issues
    for key, value in properties.items():
        prop = spec.properties.get(key)
        if prop is None:
            issues.append(Issue("unknown_property", f"unknown property {key} on {type_name}"))
            continue
        expected = _PY_TYPES[prop.type]
        if value is None or not isinstance(value, expected):
            issues.append(Issue("property_type", f"{type_name}.{key} is not {prop.type}"))
    for key, prop in spec.properties.items():
        if prop.required and not properties.get(key):
            issues.append(Issue("required", f"{type_name}.{key} is required"))
    return issues


def validate_claim(
    raw: dict,
    ontology: Ontology,
    entities: dict[str, str],
    prose: str,
) -> list[Issue]:
    """``entities`` maps canonical entity name to canonical type."""
    issues: list[Issue] = []
    subject = str(raw.get("subject") or "").strip()
    predicate = ontology.predicate(str(raw.get("predicate") or ""))
    if not subject:
        issues.append(Issue("subject", "claim subject is empty"))
    if predicate is None:
        issues.append(Issue("predicate", f"unknown predicate {raw.get('predicate')!r}"))
        return issues
    relation = ontology.relation_types[predicate]
    subject_type = entities.get(subject)
    if subject_type is None:
        issues.append(Issue("subject_unknown", f"subject {subject!r} is not a declared entity"))
    elif subject_type not in relation.source:
        issues.append(
            Issue(
                "domain",
                f"{predicate} does not allow a {subject_type} subject",
            )
        )
    issues.extend(_check_object(raw, relation, entities))
    issues.extend(_check_time(raw))
    quote = str(raw.get("quote") or "").strip()
    if not quote:
        issues.append(Issue("quote", "claim is missing a provenance quote"))
    elif quote not in prose:
        issues.append(Issue("grounding", "quote is not a substring of the source prose"))
    return issues


def _check_object(raw: dict, relation, entities: dict[str, str]) -> list[Issue]:
    literal = raw.get("object_literal")
    object_name = str(raw.get("object") or "").strip()
    if relation.allow_literal:
        if literal is None or str(literal).strip() == "":
            return [Issue("literal", f"{raw.get('predicate')} requires object_literal")]
        return []
    if not object_name:
        return [Issue("object", "claim object is empty")]
    object_type = entities.get(object_name)
    if object_type is None:
        return [Issue("object_unknown", f"object {object_name!r} is not a declared entity")]
    if object_type not in relation.target:
        return [Issue("range", f"{raw.get('predicate')} does not allow a {object_type} object")]
    return []


def _check_time(raw: dict) -> list[Issue]:
    issues: list[Issue] = []
    start = normalize_date(str(raw.get("valid_from") or ""))
    if start is None:
        issues.append(Issue("valid_from", f"invalid valid_from {raw.get('valid_from')!r}"))
        return issues
    end_raw = raw.get("valid_to")
    if end_raw:
        end = normalize_date(str(end_raw))
        if end is None:
            issues.append(Issue("valid_to", f"invalid valid_to {end_raw!r}"))
        elif end < start:
            issues.append(Issue("valid_to", "valid_to is before valid_from"))
    review = raw.get("review_after")
    if review and normalize_date(str(review)) is None:
        issues.append(Issue("review_after", f"invalid review_after {review!r}"))
    return issues


def validate_page(text: str, ontology: Ontology) -> list[Issue]:
    """Check a generated markdown page's frontmatter and claim headings."""
    issues: list[Issue] = []
    meta, body = _frontmatter(text)
    if meta.get("orphan") is True:
        return issues
    entity_type = meta.get("entity_type")
    if entity_type is None:
        issues.append(Issue("page_type", "page is missing entity_type"))
    elif ontology.entity_type(str(entity_type)) is None:
        issues.append(Issue("page_type", f"page entity_type {entity_type!r} is not in the ontology"))
    if not str(meta.get("entity_name") or "").strip():
        issues.append(Issue("page_name", "page is missing entity_name"))
    for line in body.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("- **") and "**" in stripped[4:]):
            continue
        predicate = stripped[4:].split("**", 1)[0]
        if ontology.predicate(predicate) is None:
            issues.append(Issue("page_predicate", f"page uses unknown predicate {predicate}"))
    issues.extend(_footnote_issues(body))
    return issues


def _frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    import yaml

    loaded = yaml.safe_load(parts[1]) or {}
    if not isinstance(loaded, dict):
        return {}, parts[2]
    return loaded, parts[2]


def _footnote_issues(body: str) -> list[Issue]:
    import re

    used = set(re.findall(r"\[\^([^\]]+)\](?!:)", body))
    defined = set(re.findall(r"^\[\^([^\]]+)\]:", body, flags=re.MULTILINE))
    missing = sorted(used - defined)
    return [Issue("footnote", f"citation [^{key}] has no definition") for key in missing]

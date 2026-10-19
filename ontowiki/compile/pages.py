"""Render ontology-shaped markdown pages from the temporal graph."""

from __future__ import annotations

import os
from pathlib import Path

from ontowiki.kg.models import Claim, Entity
from ontowiki.kg.store import SqliteTemporalKG
from ontowiki.ontology.schema import Ontology
from ontowiki.text import slugify


def write_pages(
    store: SqliteTemporalKG,
    ontology: Ontology,
    wiki_dir: Path,
    orphans: list[dict],
) -> list[str]:
    wiki_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    entities = store.entities()
    claims = store.all_claims()
    for entity in entities:
        path = page_path(wiki_dir, ontology, entity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_entity_page(entity, entities, claims, ontology, wiki_dir), encoding="utf-8")
        written.append(str(path.relative_to(wiki_dir)))
    for orphan in orphans:
        relative = Path(str(orphan["path"]))
        path = wiki_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _orphan_page(
                str(orphan["title"]),
                str(orphan["body"]),
                ontology.name,
                str(orphan.get("published") or ""),
            ),
            encoding="utf-8",
        )
        written.append(str(relative))
    index = wiki_dir / "index.md"
    index.write_text(_index(entities, ontology, wiki_dir), encoding="utf-8")
    overview = wiki_dir / "overview.md"
    overview.write_text(_overview(ontology, entities, claims, store), encoding="utf-8")
    written.extend(["index.md", "overview.md"])
    return written


def page_path(wiki_dir: Path, ontology: Ontology, entity: Entity) -> Path:
    folder = ontology.entity_types[entity.type].folder
    return wiki_dir / folder / f"{slugify(entity.name)}.md"


def _entity_page(
    entity: Entity,
    entities: list[Entity],
    claims: list[Claim],
    ontology: Ontology,
    wiki_dir: Path,
) -> str:
    own = [claim for claim in claims if claim.subject_id == entity.id]
    active = [claim for claim in own if claim.invalidated_at is None]
    history = [claim for claim in own if claim.invalidated_at is not None]
    lines = [
        "---",
        f"ontology: {ontology.name}",
        f"entity_type: {entity.type}",
        f"entity_name: {entity.name}",
        "---",
        "",
        f"# {entity.name}",
        "",
        ontology.entity_types[entity.type].description,
        "",
    ]
    if active:
        first = active[0]
        lines.append(f"{entity.name} {first.predicate} {first.object_display}.[^{_cite_id(first)}]")
        lines.append("")
    lines.append("## Claims")
    lines.append("")
    if not own:
        lines.append("No claims.")
        lines.append("")
    for claim in active:
        lines.extend(_claim_block(claim, entities, ontology, wiki_dir, entity))
    lines.append("## History")
    lines.append("")
    if not history:
        lines.append("No superseded claims.")
        lines.append("")
    for claim in history:
        end = claim.valid_to or "open"
        lines.append(
            f"- {claim.valid_from} .. {end} **{claim.predicate}** {claim.object_display} ({claim.status})"
        )
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    seen: set[str] = set()
    for claim in own:
        key = _cite_id(claim)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"[^{key}]: {Path(claim.episode_path).name} — \"{claim.quote}\"")
    lines.append("")
    return "\n".join(lines)


def _claim_block(
    claim: Claim,
    entities: list[Entity],
    ontology: Ontology,
    wiki_dir: Path,
    entity: Entity,
) -> list[str]:
    target = claim.object_display
    if claim.object_name:
        match = next(item for item in entities if item.name == claim.object_name)
        href = Path(_relative_link(wiki_dir, ontology, entity, match))
        target = f"[{claim.object_name}]({href.as_posix()})"
    end = claim.valid_to or "open"
    return [
        f"- **{claim.predicate}** {target}",
        f"  - valid: {claim.valid_from} .. {end}",
        f"  - status: {claim.status}",
        f"  - provenance: {Path(claim.episode_path).name}",
        f"  - \"{claim.quote}\"",
        "",
    ]


def _relative_link(wiki_dir: Path, ontology: Ontology, source: Entity, target: Entity) -> str:
    origin = page_path(wiki_dir, ontology, source)
    dest = page_path(wiki_dir, ontology, target)
    return Path(os.path.relpath(dest, origin.parent)).as_posix()


def _cite_id(claim: Claim) -> str:
    return claim.id[:8]


def _index(entities: list[Entity], ontology: Ontology, wiki_dir: Path) -> str:
    lines = [
        "---",
        f"ontology: {ontology.name}",
        "title: Index",
        "---",
        "",
        "# Index",
        "",
        "Entity pages compiled under the ontology. Orphan notes are omitted until lint clears them.",
        "",
    ]
    current = ""
    for entity in entities:
        if entity.type != current:
            current = entity.type
            lines.extend([f"## {current}", ""])
        path = page_path(wiki_dir, ontology, entity)
        href = Path(os.path.relpath(path, wiki_dir)).as_posix()
        lines.append(f"- [{entity.name}]({href})")
    lines.append("")
    return "\n".join(lines)


def _overview(ontology: Ontology, entities: list[Entity], claims: list[Claim], store: SqliteTemporalKG) -> str:
    active = [claim for claim in claims if claim.invalidated_at is None]
    contradicted = [claim for claim in active if claim.status == "contradicted"]
    lines = [
        "---",
        f"ontology: {ontology.name}",
        "title: Overview",
        "---",
        "",
        f"# {ontology.name}",
        "",
        ontology.description or "Compiled wiki.",
        "",
        f"- Entities: {len(entities)}",
        f"- Claims recorded: {len(claims)}",
        f"- Active claims: {len(active)}",
        f"- Claims in contradiction: {len(contradicted)}",
        f"- Open contradictions: {len(store.contradictions())}",
        "",
        "Read `index.md` first, then an entity page, then the quote on each claim.",
        "",
    ]
    return "\n".join(lines)


def _orphan_page(title: str, body: str, ontology_name: str, published: str) -> str:
    header = [
        "---",
        f"ontology: {ontology_name}",
        "orphan: true",
        f"title: {title}",
    ]
    if published:
        header.append(f"published: {published}")
    header.append("---")
    return "\n".join(
        [
            *header,
            "",
            f"# {title}",
            "",
            body.strip(),
            "",
        ]
    )

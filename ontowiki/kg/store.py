"""SQLite bi-temporal knowledge graph.

Each claim has a valid-time interval (when it was true in the world) and a
transaction interval (when this wiki believed it): ``ingested_at`` through
``invalidated_at``. Supersession closes the old interval. It does not delete
the row. See ``ontowiki/kg/graphiti_backend.py`` for why this, and not a live
Graphiti/Neo4j process, is the default.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ontowiki.kg.models import Claim, Contradiction, Entity, Episode, Provenance, UpsertResult
from ontowiki.ontology.schema import Ontology, RelationType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    title TEXT NOT NULL,
    published TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(type, name)
);
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_id TEXT,
    object_literal TEXT,
    fact_key TEXT NOT NULL,
    value_key TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    ingested_at TEXT NOT NULL,
    invalidated_at TEXT,
    episode_id TEXT NOT NULL,
    quote TEXT NOT NULL,
    status TEXT NOT NULL,
    review_after TEXT
);
CREATE TABLE IF NOT EXISTS provenance (
    claim_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    quote TEXT NOT NULL,
    PRIMARY KEY (claim_id, episode_id)
);
CREATE TABLE IF NOT EXISTS contradictions (
    id TEXT PRIMARY KEY,
    claim_a TEXT NOT NULL,
    claim_b TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    UNIQUE(claim_a, claim_b)
);
"""

_CLAIM_SQL = """
SELECT
    c.id, c.subject_id, s.name AS subject_name, s.type AS subject_type,
    c.predicate, c.object_id, o.name AS object_name, c.object_literal,
    c.fact_key, c.value_key, c.valid_from, c.valid_to, c.ingested_at,
    c.invalidated_at, c.episode_id, e.source_path AS episode_path,
    e.title AS episode_title, c.quote, c.status, c.review_after
FROM claims c
JOIN entities s ON s.id = c.subject_id
LEFT JOIN entities o ON o.id = c.object_id
JOIN episodes e ON e.id = c.episode_id
"""


def stable_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def fact_key(subject: str, predicate: str, value: str, functional: bool) -> str:
    subject_key = subject.strip().lower()
    if functional:
        return f"{subject_key}|{predicate}"
    return f"{subject_key}|{predicate}|{value.strip().lower()}"


def value_key(object_name: str | None, literal: str | None) -> str:
    return (object_name or literal or "").strip().lower()


def intervals_overlap(a_from: str, a_to: str | None, b_from: str, b_to: str | None) -> bool:
    a_end = a_to or "9999-12-31"
    b_end = b_to or "9999-12-31"
    return a_from < b_end and b_from < a_end


class SqliteTemporalKG:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def add_episode(self, episode: Episode) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO episodes (id, source_path, title, published, ingested_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (episode.id, episode.source_path, episode.title, episode.published, episode.ingested_at),
        )
        self._conn.commit()

    def add_entity(self, entity: Entity) -> str:
        existing = self.entity_by_name(entity.name)
        if existing and existing.type == entity.type:
            merged = dict(existing.properties)
            merged.update({key: value for key, value in entity.properties.items() if value not in (None, "")})
            self._conn.execute(
                "UPDATE entities SET properties_json = ? WHERE id = ?",
                (json.dumps(merged, sort_keys=True), existing.id),
            )
            self._conn.commit()
            return existing.id
        self._conn.execute(
            "INSERT INTO entities (id, type, name, properties_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (entity.id, entity.type, entity.name, json.dumps(entity.properties, sort_keys=True), entity.created_at),
        )
        self._conn.commit()
        return entity.id

    def entity_by_name(self, name: str) -> Entity | None:
        row = self._conn.execute("SELECT * FROM entities WHERE name = ?", (name,)).fetchone()
        if row is None:
            folded = self._conn.execute(
                "SELECT * FROM entities WHERE lower(name) = lower(?)",
                (name,),
            ).fetchone()
            row = folded
        return _entity(row) if row else None

    def entities(self) -> list[Entity]:
        rows = self._conn.execute("SELECT * FROM entities ORDER BY type, name").fetchall()
        return [_entity(row) for row in rows]

    def name_index(self) -> dict[str, str]:
        return {entity.name: entity.type for entity in self.entities()}

    def upsert_claim(
        self,
        *,
        subject: str,
        predicate: str,
        object_name: str | None,
        object_literal: str | None,
        valid_from: str,
        valid_to: str | None,
        ingested_at: str,
        episode_id: str,
        quote: str,
        review_after: str | None,
        ontology: Ontology,
    ) -> UpsertResult:
        relation = ontology.relation(predicate)
        canonical = ontology.predicate(predicate)
        assert canonical is not None
        subject_entity = self.entity_by_name(subject)
        if subject_entity is None:
            raise KeyError(subject)
        object_entity = self.entity_by_name(object_name) if object_name else None
        vkey = value_key(object_entity.name if object_entity else None, object_literal)
        fkey = fact_key(subject_entity.name, canonical, vkey, relation.functional)
        claim_id = stable_id(episode_id, fkey, vkey, valid_from)
        active = [claim for claim in self._fact_claims(fkey) if claim.invalidated_at is None]
        same = [claim for claim in active if claim.value_key == vkey]
        if same:
            self._add_provenance(same[0].id, episode_id, quote)
            return UpsertResult(same[0].id, "duplicate")
        others = [claim for claim in active if claim.value_key != vkey]
        action, contradicted = self._resolve_conflicts(
            others, relation, valid_from, ingested_at, claim_id
        )
        status = "contradicted" if action == "contradict" else "active"
        self._insert_claim(
            id=claim_id,
            subject_id=subject_entity.id,
            predicate=canonical,
            object_id=object_entity.id if object_entity else None,
            object_literal=object_literal,
            fact_key=fkey,
            value_key=vkey,
            valid_from=valid_from,
            valid_to=valid_to,
            ingested_at=ingested_at,
            episode_id=episode_id,
            quote=quote,
            status=status,
            review_after=review_after,
        )
        self._add_provenance(claim_id, episode_id, quote)
        return UpsertResult(claim_id, action, tuple(contradicted))

    def claims_as_of(self, known_at: str | None = None) -> list[Claim]:
        """Belief at transaction time ``known_at``. None means the current belief."""
        clauses = ["c.invalidated_at IS NULL"]
        params: list[str] = []
        if known_at is not None:
            clauses = ["c.ingested_at <= ?", "(c.invalidated_at IS NULL OR c.invalidated_at > ?)"]
            params = [known_at, known_at]
        sql = _CLAIM_SQL + " WHERE " + " AND ".join(clauses) + " ORDER BY c.ingested_at, c.id"
        return [_claim(row) for row in self._conn.execute(sql, params).fetchall()]

    def all_claims(self) -> list[Claim]:
        sql = _CLAIM_SQL + " ORDER BY c.ingested_at, c.id"
        return [_claim(row) for row in self._conn.execute(sql).fetchall()]

    def claim(self, claim_id: str) -> Claim | None:
        sql = _CLAIM_SQL + " WHERE c.id = ?"
        row = self._conn.execute(sql, (claim_id,)).fetchone()
        return _claim(row) if row else None

    def provenance(self, claim_id: str) -> list[Provenance]:
        rows = self._conn.execute(
            "SELECT p.claim_id, p.episode_id, p.quote, e.source_path, e.title "
            "FROM provenance p JOIN episodes e ON e.id = p.episode_id "
            "WHERE p.claim_id = ? ORDER BY e.ingested_at",
            (claim_id,),
        ).fetchall()
        return [
            Provenance(row["claim_id"], row["episode_id"], row["source_path"], row["title"], row["quote"])
            for row in rows
        ]

    def contradictions(self) -> list[Contradiction]:
        rows = self._conn.execute(
            "SELECT id, claim_a, claim_b, detected_at FROM contradictions ORDER BY detected_at, id"
        ).fetchall()
        return [Contradiction(row["id"], row["claim_a"], row["claim_b"], row["detected_at"]) for row in rows]

    def episodes(self) -> list[Episode]:
        rows = self._conn.execute(
            "SELECT id, source_path, title, published, ingested_at FROM episodes ORDER BY ingested_at, source_path"
        ).fetchall()
        return [Episode(row["id"], row["source_path"], row["title"], row["published"], row["ingested_at"]) for row in rows]

    def _fact_claims(self, fkey: str) -> list[Claim]:
        sql = _CLAIM_SQL + " WHERE c.fact_key = ? ORDER BY c.ingested_at, c.id"
        return [_claim(row) for row in self._conn.execute(sql, (fkey,)).fetchall()]

    def _resolve_conflicts(
        self,
        others: list[Claim],
        relation: RelationType,
        valid_from: str,
        ingested_at: str,
        new_id: str,
    ) -> tuple[str, list[str]]:
        overlapping = [
            old
            for old in others
            if intervals_overlap(old.valid_from, old.valid_to, valid_from, None)
        ]
        if not overlapping or not relation.functional or relation.on_conflict == "coexist":
            return "insert", []
        if relation.on_conflict == "supersede" and all(valid_from > old.valid_from for old in overlapping):
            for old in overlapping:
                self._supersede(old.id, valid_to=valid_from, invalidated_at=ingested_at)
            return "supersede", []
        contradicted: list[str] = []
        for old in overlapping:
            self._set_status(old.id, "contradicted")
            self._add_contradiction(old.id, new_id, ingested_at)
            contradicted.append(old.id)
        return "contradict", contradicted

    def _supersede(self, claim_id: str, *, valid_to: str, invalidated_at: str) -> None:
        self._conn.execute(
            "UPDATE claims SET valid_to = ?, invalidated_at = ?, status = 'superseded' WHERE id = ?",
            (valid_to, invalidated_at, claim_id),
        )

    def _set_status(self, claim_id: str, status: str) -> None:
        self._conn.execute("UPDATE claims SET status = ? WHERE id = ?", (status, claim_id))

    def _add_contradiction(self, left: str, right: str, detected_at: str) -> None:
        claim_a, claim_b = sorted((left, right))
        row_id = stable_id("contradiction", claim_a, claim_b)
        self._conn.execute(
            "INSERT OR IGNORE INTO contradictions (id, claim_a, claim_b, detected_at) VALUES (?, ?, ?, ?)",
            (row_id, claim_a, claim_b, detected_at),
        )

    def _insert_claim(self, **fields: object) -> None:
        columns = [
            "id",
            "subject_id",
            "predicate",
            "object_id",
            "object_literal",
            "fact_key",
            "value_key",
            "valid_from",
            "valid_to",
            "ingested_at",
            "episode_id",
            "quote",
            "status",
            "review_after",
        ]
        values = [fields[column] for column in columns]
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO claims ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        self._conn.commit()

    def _add_provenance(self, claim_id: str, episode_id: str, quote: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO provenance (claim_id, episode_id, quote) VALUES (?, ?, ?)",
            (claim_id, episode_id, quote),
        )
        self._conn.commit()


def _entity(row: sqlite3.Row) -> Entity:
    return Entity(
        id=row["id"],
        type=row["type"],
        name=row["name"],
        properties=json.loads(row["properties_json"]),
        created_at=row["created_at"],
    )


def _claim(row: sqlite3.Row) -> Claim:
    return Claim(
        id=row["id"],
        subject_id=row["subject_id"],
        subject_name=row["subject_name"],
        subject_type=row["subject_type"],
        predicate=row["predicate"],
        object_id=row["object_id"],
        object_name=row["object_name"],
        object_literal=row["object_literal"],
        fact_key=row["fact_key"],
        value_key=row["value_key"],
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        ingested_at=row["ingested_at"],
        invalidated_at=row["invalidated_at"],
        episode_id=row["episode_id"],
        episode_path=row["episode_path"],
        episode_title=row["episode_title"],
        quote=row["quote"],
        status=row["status"],
        review_after=row["review_after"],
    )

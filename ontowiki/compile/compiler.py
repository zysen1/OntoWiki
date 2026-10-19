"""Compile sources into validated claims, a temporal graph, and wiki pages."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ontowiki.compile.extract import SourceDocument, load_sources
from ontowiki.compile.pages import write_pages
from ontowiki.dates import normalize_date
from ontowiki.kg.graphiti_backend import GraphitiMirror
from ontowiki.kg.models import Entity, Episode
from ontowiki.kg.store import SqliteTemporalKG, stable_id
from ontowiki.ontology.repair import LLMRepairer, repair_entity_until_valid, repair_until_valid
from ontowiki.ontology.schema import Ontology, load_ontology
from ontowiki.ontology.validate import validate_page


@dataclass
class Rejection:
    source: str
    message: str


@dataclass
class CompileReport:
    accepted: int = 0
    rejected: list[Rejection] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    contradictions: int = 0
    superseded: int = 0

    @property
    def ok(self) -> bool:
        return not self.rejected


class Compiler:
    def __init__(self, ontology: Ontology, store: SqliteTemporalKG, llm: LLMRepairer | None = None):
        self.ontology = ontology
        self.store = store
        self.llm = llm

    def run(self, sources: list[SourceDocument], wiki_dir: Path) -> CompileReport:
        report = CompileReport()
        orphans: list[dict] = []
        mirrored: list[tuple[SourceDocument, list[dict[str, str]]]] = []
        for source in sources:
            accepted, source_orphans = self._ingest(source, report)
            orphans.extend(source_orphans)
            mirrored.append((source, accepted))
        report.pages = write_pages(self.store, self.ontology, wiki_dir, orphans)
        report.contradictions = len(self.store.contradictions())
        self._check_pages(wiki_dir, report)
        self._mirror = mirrored
        return report

    def mirror_payloads(self) -> list[tuple[SourceDocument, list[dict[str, str]]]]:
        return getattr(self, "_mirror", [])

    def _ingest(self, source: SourceDocument, report: CompileReport) -> tuple[list[dict[str, str]], list[dict]]:
        published = normalize_date(source.published)
        if published is None:
            report.rejected.append(Rejection(source.relpath, f"bad published date {source.published!r}"))
            return [], []
        episode = Episode(
            id=stable_id("episode", source.relpath),
            source_path=source.relpath,
            title=source.title,
            published=published,
            ingested_at=published,
        )
        self.store.add_episode(episode)
        if not self._ingest_entities(source, published, report):
            return [], []
        stamped = [dict(page, published=published) for page in source.orphan_pages]
        return self._ingest_claims(source, episode, report), stamped

    def _ingest_entities(self, source: SourceDocument, published: str, report: CompileReport) -> bool:
        for raw in source.entities:
            known = self.store.name_index()
            repaired, notes, issues = repair_entity_until_valid(raw, self.ontology, known)
            report.repairs.extend(f"{source.relpath}: {note}" for note in notes)
            if repaired is None:
                detail = "; ".join(issue.message for issue in issues)
                report.rejected.append(Rejection(source.relpath, detail))
                return False
            entity = Entity(
                id=stable_id("entity", repaired["type"], repaired["name"].lower()),
                type=repaired["type"],
                name=repaired["name"],
                properties=repaired.get("properties") or {},
                created_at=published,
            )
            self.store.add_entity(entity)
        return True

    def _ingest_claims(self, source: SourceDocument, episode: Episode, report: CompileReport) -> list[dict[str, str]]:
        accepted: list[dict[str, str]] = []
        for raw in source.claims:
            known = self.store.name_index()
            repaired, notes, issues = repair_until_valid(raw, self.ontology, known, source.prose, self.llm)
            report.repairs.extend(f"{source.relpath}: {note}" for note in notes)
            if repaired is None:
                detail = "; ".join(issue.message for issue in issues)
                report.rejected.append(Rejection(source.relpath, detail))
                continue
            literal = repaired.get("object_literal")
            literal_text = None if literal is None else str(literal)
            result = self.store.upsert_claim(
                subject=repaired["subject"],
                predicate=repaired["predicate"],
                object_name=str(repaired.get("object") or "").strip() or None,
                object_literal=literal_text,
                valid_from=normalize_date(str(repaired["valid_from"])) or episode.ingested_at,
                valid_to=normalize_date(str(repaired["valid_to"])) if repaired.get("valid_to") else None,
                ingested_at=episode.ingested_at,
                episode_id=episode.id,
                quote=str(repaired["quote"]).strip(),
                review_after=normalize_date(str(repaired["review_after"])) if repaired.get("review_after") else None,
                ontology=self.ontology,
            )
            report.accepted += 1
            if result.action == "supersede":
                report.superseded += 1
            display = literal_text or str(repaired.get("object") or "")
            accepted.append(
                {
                    "subject": repaired["subject"],
                    "predicate": repaired["predicate"],
                    "object": display,
                    "quote": str(repaired["quote"]).strip(),
                }
            )
        return accepted

    def _check_pages(self, wiki_dir: Path, report: CompileReport) -> None:
        for path in sorted(wiki_dir.rglob("*.md")):
            relative = path.relative_to(wiki_dir).as_posix()
            if relative in {"index.md", "overview.md"} or relative.startswith("_lint/"):
                continue
            issues = validate_page(path.read_text(encoding="utf-8"), self.ontology)
            for issue in issues:
                report.rejected.append(Rejection(str(path.relative_to(wiki_dir)), issue.message))


def compile_workspace(
    ontology_path: str | Path,
    sources_dir: str | Path,
    out_dir: str | Path,
    *,
    llm: LLMRepairer | None = None,
    graphiti_client=None,
) -> CompileReport:
    ontology = load_ontology(ontology_path)
    out = Path(out_dir)
    graph_path = out / ".ontowiki" / "graph.sqlite"
    if graph_path.exists():
        graph_path.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / ".ontowiki").mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(ontology_path), out / ".ontowiki" / "ontology.yaml")
    _copy_sources(Path(sources_dir), out / "sources")
    store = SqliteTemporalKG(graph_path)
    try:
        compiler = Compiler(ontology, store, llm=llm)
        report = compiler.run(load_sources(sources_dir), out / "wiki")
        if graphiti_client is not None:
            _sync_graphiti(graphiti_client, ontology, compiler.mirror_payloads())
        return report
    finally:
        store.close()


def _copy_sources(sources_dir: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for path in sources_dir.rglob("*.md"):
        target = dest / path.relative_to(sources_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)


def _sync_graphiti(client, ontology: Ontology, payloads: list[tuple[SourceDocument, list[dict[str, str]]]]) -> None:
    import asyncio

    mirror = GraphitiMirror(client, ontology)

    async def _run() -> None:
        for source, claims in payloads:
            if not claims and not source.prose:
                continue
            await mirror.sync_source(
                title=source.title,
                prose=source.prose,
                source_path=source.relpath,
                published=normalize_date(source.published) or source.published,
                claims=claims,
            )

    asyncio.run(_run())

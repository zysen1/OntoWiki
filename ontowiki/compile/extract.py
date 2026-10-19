"""Read a source file and the optional ```ontowiki block inside it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_FENCE = re.compile(r"```ontowiki\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    relpath: str
    title: str
    published: str
    prose: str
    entities: list[dict]
    claims: list[dict]
    orphan_pages: list[dict]


def load_sources(directory: str | Path) -> list[SourceDocument]:
    root = Path(directory)
    documents = [_load(path, root) for path in sorted(root.rglob("*.md"))]
    documents = [doc for doc in documents if doc is not None]
    documents.sort(key=lambda doc: (doc.published, doc.relpath))
    return documents


def _load(path: Path, root: Path) -> SourceDocument | None:
    raw = path.read_text(encoding="utf-8")
    meta, body = _frontmatter(raw)
    published = str(meta.get("published") or "").strip()
    title = str(meta.get("title") or path.stem).strip()
    prose, payload = _split_payload(body)
    if not published and not payload:
        return None
    return SourceDocument(
        path=path,
        relpath=str(path.relative_to(root)),
        title=title,
        published=published,
        prose=prose.strip(),
        entities=list(payload.get("entities") or []),
        claims=list(payload.get("claims") or []),
        orphan_pages=list(payload.get("orphan_pages") or []),
    )


def _frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    loaded = yaml.safe_load(parts[1]) or {}
    if not isinstance(loaded, dict):
        return {}, parts[2]
    return loaded, parts[2].lstrip("\n")


def _split_payload(body: str) -> tuple[str, dict]:
    match = _FENCE.search(body)
    if not match:
        return body, {}
    loaded = yaml.safe_load(match.group(1)) or {}
    if not isinstance(loaded, dict):
        loaded = {}
    prose = body[: match.start()] + body[match.end() :]
    return prose, loaded

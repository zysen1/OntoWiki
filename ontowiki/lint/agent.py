"""Background lint: contradictions, stale claims, orphan pages.

Findings are written for a person to review. Nothing is deleted or invalidated
from this pass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ontowiki.dates import days_between, normalize_date
from ontowiki.kg.models import Claim
from ontowiki.kg.store import SqliteTemporalKG, intervals_overlap
from ontowiki.ontology.schema import Ontology

_SKIP_PAGES = {"index.md", "overview.md"}


@dataclass
class Finding:
    kind: str
    severity: str
    message: str
    suggestion: str
    claim_ids: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    visible_from: str = "0001-01-01"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LintReport:
    as_of: str
    findings: list[Finding]

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.kind] = counts.get(finding.kind, 0) + 1
        return counts


class LintAgent:
    def __init__(self, store: SqliteTemporalKG, ontology: Ontology, wiki_dir: Path):
        self.store = store
        self.ontology = ontology
        self.wiki_dir = wiki_dir

    def run(self, as_of: str | None = None) -> LintReport:
        resolved = as_of or _latest(self.store) or "9999-12-31"
        findings = [
            *self._contradictions(resolved),
            *self._stale(resolved),
            *self._orphans(),
        ]
        findings.sort(key=lambda item: (item.kind, item.visible_from, item.message))
        return LintReport(as_of=resolved, findings=findings)

    def _contradictions(self, as_of: str) -> list[Finding]:
        active = self.store.claims_as_of(as_of)
        grouped: dict[str, list[Claim]] = {}
        for claim in active:
            grouped.setdefault(claim.fact_key, []).append(claim)
        findings: list[Finding] = []
        for group in grouped.values():
            findings.extend(_conflict_group(group, self.ontology))
        return findings

    def _stale(self, as_of: str) -> list[Finding]:
        findings: list[Finding] = []
        for claim in self.store.claims_as_of(as_of):
            reason = _stale_reason(claim, as_of, self.ontology)
            if reason is None:
                continue
            findings.append(
                Finding(
                    kind="stale",
                    severity="warn",
                    message=reason,
                    suggestion="Re-read the source and either supersede the claim or extend review_after.",
                    claim_ids=[claim.id],
                    paths=[claim.episode_path],
                    visible_from=claim.review_after or claim.valid_from,
                )
            )
        return findings

    def _orphans(self) -> list[Finding]:
        if not self.wiki_dir.exists():
            return []
        known = self.store.name_index()
        linked = _inbound_links(self.wiki_dir)
        findings: list[Finding] = []
        for path in sorted(self.wiki_dir.rglob("*.md")):
            relative = path.relative_to(self.wiki_dir).as_posix()
            if relative in _SKIP_PAGES or relative.startswith("_lint/"):
                continue
            text = path.read_text(encoding="utf-8")
            meta, _body = _frontmatter(text)
            if meta.get("orphan") is True or _is_orphan(meta, known, relative, linked):
                findings.append(
                    Finding(
                        kind="orphan",
                        severity="warn",
                        message=f"{relative} has no entity in the graph and nothing links to it.",
                        suggestion="Link it from an entity page, or drop it in review.",
                        paths=[relative],
                        visible_from=str(meta.get("published") or "0001-01-01"),
                    )
                )
        return findings


def write_review(report: LintReport, wiki_dir: Path) -> Path:
    folder = wiki_dir / "_lint"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "review.md"
    path.write_text(render_review(report), encoding="utf-8")
    (folder / "review.json").write_text(
        json.dumps({"as_of": report.as_of, "findings": [item.to_dict() for item in report.findings]}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def render_review(report: LintReport) -> str:
    lines = [
        f"# OntoWiki lint — {report.as_of}",
        "",
        "Review only. This pass does not invalidate claims or delete pages.",
        "",
    ]
    if not report.findings:
        lines.extend(["No findings.", ""])
        return "\n".join(lines)
    current = ""
    for finding in report.findings:
        if finding.kind != current:
            current = finding.kind
            lines.extend([f"## {current.title()}", ""])
        lines.append(f"- **{finding.severity}** {finding.message}")
        if finding.paths:
            lines.append(f"  - paths: {', '.join(finding.paths)}")
        if finding.claim_ids:
            lines.append(f"  - claims: {', '.join(finding.claim_ids)}")
        lines.append(f"  - suggestion: {finding.suggestion}")
    lines.append("")
    return "\n".join(lines)


def _conflict_group(group: list[Claim], ontology: Ontology) -> list[Finding]:
    if len(group) < 2:
        return []
    relation = ontology.relation_types.get(group[0].predicate)
    if relation is None or not relation.functional or relation.on_conflict == "coexist":
        return []
    findings: list[Finding] = []
    for index, left in enumerate(group):
        for right in group[index + 1 :]:
            if left.value_key == right.value_key:
                continue
            if not intervals_overlap(left.valid_from, left.valid_to, right.valid_from, right.valid_to):
                continue
            visible = max(left.ingested_at, right.ingested_at)
            findings.append(
                Finding(
                    kind="contradiction",
                    severity="error",
                    message=(
                        f"{left.subject_name} {left.predicate} is both "
                        f"{left.object_display!r} and {right.object_display!r}."
                    ),
                    suggestion="Keep both edges visible and ask a reviewer which value holds.",
                    claim_ids=sorted((left.id, right.id)),
                    paths=sorted({left.episode_path, right.episode_path}),
                    visible_from=visible,
                )
            )
    return findings


def _stale_reason(claim: Claim, as_of: str, ontology: Ontology) -> str | None:
    if claim.review_after and claim.review_after <= as_of:
        return (
            f"{claim.subject_name} {claim.predicate} {claim.object_display!r} "
            f"was due for review on {claim.review_after}."
        )
    relation = ontology.relation_types.get(claim.predicate)
    if relation and relation.stale_after_days is not None:
        age = days_between(claim.valid_from, as_of)
        if age > relation.stale_after_days:
            return (
                f"{claim.subject_name} {claim.predicate} is {age} days old "
                f"(stale after {relation.stale_after_days})."
            )
    return None


def _is_orphan(meta: dict, known: dict[str, str], relative: str, linked: set[str]) -> bool:
    name = str(meta.get("entity_name") or "").strip()
    if name and name in known:
        return False
    if name:
        return True
    return relative not in linked and Path(relative).name not in linked


def _inbound_links(wiki_dir: Path) -> set[str]:
    import re

    found: set[str] = set()
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in wiki_dir.rglob("*.md"):
        for match in pattern.findall(path.read_text(encoding="utf-8")):
            target = match.split("#", 1)[0]
            if target:
                found.add(Path(target).name)
                found.add(target)
    return found


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


def _latest(store: SqliteTemporalKG) -> str | None:
    dates = [episode.ingested_at for episode in store.episodes()]
    if not dates:
        return None
    return max(dates)


def default_as_of(value: str | None, store: SqliteTemporalKG) -> str:
    if value:
        normalized = normalize_date(value)
        if normalized is None:
            raise ValueError(f"bad as_of {value!r}")
        return normalized
    return _latest(store) or "9999-12-31"

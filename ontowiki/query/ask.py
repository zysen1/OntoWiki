"""Progressive disclosure over the compiled wiki.

Level 0 is the index of matched names, level 1 adds the chosen answer line,
level 2 adds claim status and valid time, level 3 adds the grounded quote.
Deeper levels only append. They do not replace earlier ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from ontowiki.kg.models import Claim, Entity
from ontowiki.kg.store import SqliteTemporalKG
from ontowiki.text import estimate_tokens, stem, stems


@dataclass(frozen=True)
class QueryResult:
    answer: str
    sources: list[str]
    claim_ids: list[str]
    disclosure: str
    context_tokens: int
    as_of: str | None

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "sources": self.sources,
            "claim_ids": self.claim_ids,
            "disclosure": self.disclosure,
            "context_tokens": self.context_tokens,
            "as_of": self.as_of,
        }


def ask(
    store: SqliteTemporalKG,
    question: str,
    *,
    as_of: str | None = None,
    depth: int = 3,
) -> QueryResult:
    claims = store.claims_as_of(as_of)
    entities = store.entities()
    answer, chosen = _select(question, claims, entities)
    disclosure = _disclose(answer, chosen, depth)
    sources = sorted({_filename(claim.episode_path) for claim in chosen})
    return QueryResult(
        answer=answer,
        sources=sources,
        claim_ids=[claim.id for claim in chosen],
        disclosure=disclosure,
        context_tokens=estimate_tokens(disclosure),
        as_of=as_of,
    )


def _select(
    question: str,
    claims: list[Claim],
    entities: list[Entity],
) -> tuple[str, list[Claim]]:
    mentioned = _mentioned(question, entities)
    if "which paper" in question.lower():
        paper = _paper_for(question, claims, entities, mentioned)
        if paper is not None:
            return paper
    ranked = sorted(claims, key=lambda claim: (_score(question, claim), claim.id), reverse=True)
    if not ranked or _score(question, ranked[0]) <= 0:
        return "", []
    best = ranked[0]
    support = [claim for claim in ranked if claim.fact_key == best.fact_key and _score(question, claim) > 0]
    # The best value only. Supporting duplicates of another value stay out of the answer.
    support = [claim for claim in support if claim.value_key == best.value_key]
    return best.object_display, support[:3]


def _paper_for(
    question: str,
    claims: list[Claim],
    entities: list[Entity],
    mentioned: list[Entity],
) -> tuple[str, list[Claim]] | None:
    mentioned_names = {entity.name for entity in mentioned if entity.type != "Paper"}
    if not mentioned_names:
        return None
    scored: list[tuple[int, Entity, list[Claim]]] = []
    for paper in entities:
        if paper.type != "Paper":
            continue
        links = [
            claim
            for claim in claims
            if claim.subject_id == paper.id and (claim.object_name in mentioned_names or claim.object_display in mentioned_names)
        ]
        if not links:
            continue
        bonus = sum(2 for claim in links if _predicate_in_question(claim.predicate, question))
        scored.append((len(links) + bonus, paper, links))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1].name))
    _score_value, paper, links = scored[0]
    return paper.name, links


def _mentioned(question: str, entities: list[Entity]) -> list[Entity]:
    folded = question.lower()
    hits = [entity for entity in entities if entity.name.lower() in folded]
    hits.sort(key=lambda entity: len(entity.name), reverse=True)
    kept: list[Entity] = []
    for entity in hits:
        if any(entity.name.lower() in prior.name.lower() and entity.name.lower() != prior.name.lower() for prior in kept):
            continue
        kept.append(entity)
    return kept


def _score(question: str, claim: Claim) -> int:
    haystack = stems(f"{claim.subject_name} {claim.predicate} {claim.object_display} {claim.quote}")
    return sum(1 for token in stems(question) if token in haystack)


def _predicate_in_question(predicate: str, question: str) -> bool:
    question_stems = stems(question)
    head = predicate.split("_")[0]
    return stem(head.lower()) in question_stems


def _disclose(answer: str, claims: list[Claim], depth: int) -> str:
    if depth < 0:
        depth = 0
    names = sorted({claim.subject_name for claim in claims} | {claim.object_display for claim in claims if claim.object_display})
    parts = [f"Index: {', '.join(names)}".rstrip()]
    if depth >= 1:
        parts.append(f"Answer: {answer}" if answer else "Answer:")
    if depth >= 2:
        for claim in claims:
            end = claim.valid_to or "open"
            parts.append(
                f"{claim.subject_name} {claim.predicate} {claim.object_display} "
                f"[{claim.status}] {claim.valid_from}..{end}"
            )
    if depth >= 3:
        for claim in claims:
            parts.append(f"Evidence ({_filename(claim.episode_path)}): {claim.quote}")
    return "\n".join(parts)


def _filename(path: str) -> str:
    return path.rsplit("/", 1)[-1]

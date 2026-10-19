"""Plain vector RAG baseline.

Chunks are the prose of each source (the ontology block is removed, so the
baseline cannot read the structured claims). Ranking is TF-IDF cosine.
There is no LLM in the loop: the answer is the sentence in the top chunk
with the largest token overlap with the question. ``as_of`` is ignored,
because a vector index has no valid time.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ontowiki.compile.extract import load_sources
from ontowiki.text import stems

_SENTENCE = re.compile(r"(?<=[.?!])\s+")


@dataclass(frozen=True)
class Chunk:
    source: str
    text: str


@dataclass(frozen=True)
class Retrieval:
    answer: str
    sources: list[str]
    context: str
    answer_source: str


def index_sources(directory: str | Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in load_sources(directory):
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", document.prose) if part.strip()]
        if not paragraphs:
            continue
        for paragraph in paragraphs:
            chunks.append(Chunk(document.relpath, f"{document.title}\n\n{paragraph}"))
    return chunks


def retrieve(chunks: list[Chunk], question: str, k: int = 3) -> Retrieval:
    if not chunks:
        return Retrieval("", [], "", "")
    vectors, idf = _tfidf(chunks)
    query = _vector(stems(question), idf)
    ranked = sorted(
        ((_cosine(query, vectors[index]), index) for index in range(len(chunks))),
        key=lambda item: (-item[0], chunks[item[1]].source),
    )
    chosen = [chunks[index] for score, index in ranked[:k] if score > 0]
    if not chosen:
        chosen = [chunks[ranked[0][1]]]
    top = chosen[0]
    answer = _best_sentence(top.text, question)
    context = "\n\n".join(chunk.text for chunk in chosen)
    return Retrieval(answer, [chunk.source for chunk in chosen], context, top.source)


def _best_sentence(text: str, question: str) -> str:
    sentences = [part.strip() for part in _SENTENCE.split(text) if part.strip()]
    if not sentences:
        return text.strip()
    question_stems = stems(question)
    scored = sorted(
        sentences,
        key=lambda sentence: (
            -sum(1 for token in stems(sentence) if token in question_stems),
            sentences.index(sentence),
        ),
    )
    return scored[0]


def _tfidf(chunks: list[Chunk]) -> tuple[list[dict[str, float]], dict[str, float]]:
    counts = [Counter(stems(chunk.text)) for chunk in chunks]
    document_frequency: Counter[str] = Counter()
    for count in counts:
        document_frequency.update(count.keys())
    total = len(chunks)
    idf = {term: math.log((1 + total) / (1 + freq)) + 1 for term, freq in document_frequency.items()}
    vectors = [_vector(count, idf) for count in counts]
    return vectors, idf


def _vector(counts: Counter[str] | set[str], idf: dict[str, float]) -> dict[str, float]:
    if isinstance(counts, set):
        counts = Counter(counts)
    total = sum(counts.values()) or 1
    return {term: (freq / total) * idf[term] for term, freq in counts.items() if term in idf}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(weight * right.get(term, 0.0) for term, weight in left.items())
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)

"""Small text helpers shared by query, eval, and page rendering."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "for",
        "to",
        "and",
        "or",
        "on",
        "in",
        "with",
        "by",
        "as",
        "at",
        "from",
        "that",
        "this",
        "did",
        "does",
        "do",
        "was",
        "were",
        "is",
        "are",
        "be",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "there",
        "into",
        "over",
        "than",
        "then",
        "its",
        "it",
    }
)


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOP]


def stem(token: str) -> str:
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def stems(text: str) -> set[str]:
    return {stem(token) for token in tokenize(text)}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "untitled"


def estimate_tokens(text: str) -> int:
    """Rough context size. Not a model tokenizer: four characters to one token."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)

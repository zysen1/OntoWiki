"""ISO date helpers. All stored times are ``YYYY-MM-DD`` so order is lexical."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_ISO = re.compile(r"^(\d{4})[-/](\d{2})[-/](\d{2})$")
_YEAR_MONTH = re.compile(r"^(\d{4})[-/](\d{2})$")


def normalize_date(value: str) -> str | None:
    """Return ``YYYY-MM-DD`` or None when the value is not a calendar date."""
    text = value.strip()
    match = _ISO.match(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return _valid(year, month, day)
    match = _YEAR_MONTH.match(text)
    if match:
        year, month = (int(part) for part in match.groups())
        return _valid(year, month, 1)
    return None


def _valid(year: int, month: int, day: int) -> str | None:
    try:
        datetime(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def as_utc(value: str) -> datetime:
    normalized = normalize_date(value)
    if normalized is None:
        raise ValueError(f"not a date: {value}")
    year, month, day = (int(part) for part in normalized.split("-"))
    return datetime(year, month, day, tzinfo=UTC)


def days_between(start: str, end: str) -> int:
    return (as_utc(end) - as_utc(start)).days

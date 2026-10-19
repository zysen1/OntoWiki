"""Locations of the bundled corpus and committed artifacts."""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parent


def bundled_ontology() -> Path:
    return PACKAGE / "ontologies" / "agent-research.yaml"


def bundled_sources() -> Path:
    return PACKAGE / "corpus" / "sources"


def bundled_qa() -> Path:
    return PACKAGE / "corpus" / "qa.json"


def committed_eval() -> Path:
    return PACKAGE / "eval" / "results.json"


def committed_timeline() -> Path:
    return REPO / "web" / "src" / "data" / "ontowiki-timeline.json"

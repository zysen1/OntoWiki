from pathlib import Path

from ontowiki.ontology.repair import LLMRepairer, repair_until_valid
from ontowiki.ontology.schema import load_ontology
from ontowiki.ontology.validate import validate_claim, validate_page
from ontowiki.paths import bundled_ontology


def test_bundled_ontology_loads():
    ontology = load_ontology(bundled_ontology())
    assert ontology.name == "agent-research"
    assert ontology.predicate("introduces") == "INTRODUCES"
    assert ontology.entity_type("article") == "Paper"


def test_domain_is_enforced():
    ontology = load_ontology(bundled_ontology())
    known = {"HippoRAG 2": "Paper", "Multi-hop QA": "Task"}
    raw = {
        "subject": "HippoRAG 2",
        "predicate": "INTRODUCES",
        "object": "Multi-hop QA",
        "valid_from": "2025-02-20",
        "quote": "HippoRAG 2 introduces a task.",
    }
    issues = validate_claim(raw, ontology, known, raw["quote"])
    assert any(issue.code == "range" for issue in issues)


def test_rule_repair_normalizes_alias_and_date():
    ontology = load_ontology(bundled_ontology())
    known = {"HippoRAG 2": "Paper", "Associative retrieval": "Concept"}
    raw = {
        "subject": "hipporag 2",
        "predicate": "introduces",
        "object": "associative retrieval",
        "valid_from": "2025/02/20",
        "quote": "HippoRAG 2 introduces associative retrieval.",
    }
    repaired, notes, issues = repair_until_valid(raw, ontology, known, raw["quote"])
    assert issues == []
    assert repaired is not None
    assert repaired["predicate"] == "INTRODUCES"
    assert repaired["subject"] == "HippoRAG 2"
    assert repaired["valid_from"] == "2025-02-20"
    assert notes


def test_llm_repair_fixes_what_rules_cannot(tmp_path: Path):
    ontology = load_ontology(bundled_ontology())
    known = {"HippoRAG 2": "Paper", "Associative retrieval": "Concept"}
    prose = "HippoRAG 2 introduces associative retrieval."
    raw = {
        "subject": "HippoRAG 2",
        "predicate": "puts-forward",
        "object": "Associative retrieval",
        "valid_from": "2025-02-20",
        "quote": prose,
    }

    def client(payload: dict) -> dict:
        assert "unknown predicate" in payload["issues"][0]
        return {"predicate": "INTRODUCES"}

    repaired, notes, issues = repair_until_valid(raw, ontology, known, prose, LLMRepairer(client))
    assert issues == []
    assert repaired is not None
    assert repaired["predicate"] == "INTRODUCES"
    assert any("llm repair" in note for note in notes)


def test_ungrounded_quote_is_rejected():
    ontology = load_ontology(bundled_ontology())
    known = {"HippoRAG 2": "Paper", "Associative retrieval": "Concept"}
    raw = {
        "subject": "HippoRAG 2",
        "predicate": "INTRODUCES",
        "object": "Associative retrieval",
        "valid_from": "2025-02-20",
        "quote": "this sentence is not in the source",
    }
    repaired, _notes, issues = repair_until_valid(raw, ontology, known, "HippoRAG 2 introduces associative retrieval.")
    assert repaired is None
    assert any(issue.code == "grounding" for issue in issues)


def test_page_validator_catches_unknown_predicate_and_missing_footnote():
    ontology = load_ontology(bundled_ontology())
    text = """---
ontology: agent-research
entity_type: Paper
entity_name: Example
---

# Example

Example invents a thing.[^missing]

## Claims

- **NOT_A_PREDICATE** something
"""
    codes = {issue.code for issue in validate_page(text, ontology)}
    assert "page_predicate" in codes
    assert "footnote" in codes

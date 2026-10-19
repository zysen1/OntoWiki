from pathlib import Path

import yaml

from ontowiki.kg.models import Entity, Episode
from ontowiki.kg.store import SqliteTemporalKG, stable_id
from ontowiki.ontology.schema import Ontology

_ONTOLOGY = """
name: mini
version: "1"
entity_types:
  Person:
    folder: people
  City:
    folder: cities
relation_types:
  LIVES_IN:
    source: [Person]
    target: [City]
    functional: true
    on_conflict: supersede
  LIKES:
    source: [Person]
    target: [City]
    functional: true
    on_conflict: contradict
"""


def _world(tmp_path: Path) -> tuple[SqliteTemporalKG, Ontology]:
    ontology = Ontology.model_validate(yaml.safe_load(_ONTOLOGY))
    store = SqliteTemporalKG(tmp_path / "graph.sqlite")
    store.add_episode(Episode(stable_id("e", "a"), "a.md", "A", "2020-01-01", "2020-01-01"))
    store.add_episode(Episode(stable_id("e", "b"), "b.md", "B", "2024-01-01", "2024-01-01"))
    for name, type_name, when in (("Ada", "Person", "2020-01-01"), ("Paris", "City", "2020-01-01"), ("Lyon", "City", "2024-01-01")):
        store.add_entity(Entity(stable_id("entity", type_name, name.lower()), type_name, name, {}, when))
    return store, ontology


def test_supersede_keeps_history_and_hides_it_from_later_queries(tmp_path: Path):
    store, ontology = _world(tmp_path)
    early = stable_id("e", "a")
    later = stable_id("e", "b")
    store.upsert_claim(
        subject="Ada",
        predicate="LIVES_IN",
        object_name="Paris",
        object_literal=None,
        valid_from="2020-01-01",
        valid_to=None,
        ingested_at="2020-01-01",
        episode_id=early,
        quote="Ada lives in Paris.",
        review_after=None,
        ontology=ontology,
    )
    result = store.upsert_claim(
        subject="Ada",
        predicate="LIVES_IN",
        object_name="Lyon",
        object_literal=None,
        valid_from="2024-01-01",
        valid_to=None,
        ingested_at="2024-01-01",
        episode_id=later,
        quote="Ada lives in Lyon.",
        review_after=None,
        ontology=ontology,
    )
    assert result.action == "supersede"
    in_2022 = [claim.object_display for claim in store.claims_as_of("2022-01-01")]
    in_2024 = [claim.object_display for claim in store.claims_as_of("2024-06-01")]
    assert in_2022 == ["Paris"]
    assert in_2024 == ["Lyon"]
    assert {claim.object_display for claim in store.all_claims()} == {"Paris", "Lyon"}
    paris = next(claim for claim in store.all_claims() if claim.object_display == "Paris")
    assert paris.invalidated_at == "2024-01-01"
    assert paris.valid_to == "2024-01-01"
    store.close()


def test_contradiction_does_not_overwrite(tmp_path: Path):
    store, ontology = _world(tmp_path)
    early = stable_id("e", "a")
    later = stable_id("e", "b")
    store.upsert_claim(
        subject="Ada",
        predicate="LIKES",
        object_name="Paris",
        object_literal=None,
        valid_from="2020-01-01",
        valid_to=None,
        ingested_at="2020-01-01",
        episode_id=early,
        quote="Ada likes Paris.",
        review_after=None,
        ontology=ontology,
    )
    result = store.upsert_claim(
        subject="Ada",
        predicate="LIKES",
        object_name="Lyon",
        object_literal=None,
        valid_from="2024-01-01",
        valid_to=None,
        ingested_at="2024-01-01",
        episode_id=later,
        quote="Ada likes Lyon.",
        review_after=None,
        ontology=ontology,
    )
    assert result.action == "contradict"
    believed = sorted(claim.object_display for claim in store.claims_as_of("2024-06-01"))
    assert believed == ["Lyon", "Paris"]
    assert len(store.contradictions()) == 1
    store.close()


def test_future_claims_are_invisible(tmp_path: Path):
    store, ontology = _world(tmp_path)
    store.upsert_claim(
        subject="Ada",
        predicate="LIVES_IN",
        object_name="Lyon",
        object_literal=None,
        valid_from="2024-01-01",
        valid_to=None,
        ingested_at="2024-01-01",
        episode_id=stable_id("e", "b"),
        quote="Ada lives in Lyon.",
        review_after=None,
        ontology=ontology,
    )
    assert store.claims_as_of("2022-01-01") == []
    store.close()

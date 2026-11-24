import json

import pytest

from griga.graph.relations import RelationType
from griga.speech.constructions import (
    DEFAULT_CONSTRUCTIONS_PATH,
    by_intent,
    load_constructions,
)
from griga.speech.intents import Intent


@pytest.fixture(scope="module")
def bank():
    return load_constructions()


def test_bank_is_loaded_from_data_file(bank):
    assert DEFAULT_CONSTRUCTIONS_PATH.exists()
    assert len(bank) >= 30


def test_bank_ids_are_unique(bank):
    ids = [construction.id for construction in bank]
    assert len(ids) == len(set(ids))


def test_every_intent_has_at_least_one_construction(bank):
    covered = {construction.intent for construction in bank}
    assert covered == set(Intent)


def test_bank_covers_yes_no_answers(bank):
    yes_no = [construction for construction in bank if construction.yes_no]
    assert yes_no
    assert all(
        construction.intent
        in {Intent.ANSWER_DIRECTLY, Intent.ANSWER_WITH_HEDGE}
        for construction in yes_no
    )


def test_constructions_have_consistent_slots_and_placeholders(bank):
    for construction in bank:
        assert construction.template
        assert construction.slot_names <= set(construction.slots)
        assert set(construction.slots) <= construction.slot_names


def test_graph_constructions_reference_valid_relations(bank):
    for construction in bank:
        relation = construction.graph_pattern.relation
        if relation is not None:
            assert isinstance(relation, RelationType)
            assert construction.graph_pattern.direction in {
                "forward",
                "reverse",
            }


def test_by_intent_filters_by_intent(bank):
    greetings = by_intent(bank, Intent.GREET)
    assert greetings
    assert all(item.intent is Intent.GREET for item in greetings)


def _write_bank(tmp_path, items):
    path = tmp_path / "constructions.json"
    path.write_text(
        json.dumps({"constructions": items}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_loader_rejects_unknown_intent(tmp_path):
    path = _write_bank(
        tmp_path,
        [
            {
                "id": "bad",
                "intent": "нет_такого",
                "template": "Привет!",
            }
        ],
    )
    with pytest.raises(ValueError, match="unknown intent"):
        load_constructions(path)


def test_loader_rejects_duplicate_ids(tmp_path):
    item = {
        "id": "dup",
        "intent": "поздороваться",
        "template": "Привет!",
    }
    path = _write_bank(tmp_path, [item, dict(item)])
    with pytest.raises(ValueError, match="duplicate"):
        load_constructions(path)


def test_loader_rejects_placeholder_without_slot(tmp_path):
    path = _write_bank(
        tmp_path,
        [
            {
                "id": "bad",
                "intent": "уточнить",
                "template": "Расскажи про {X}.",
            }
        ],
    )
    with pytest.raises(ValueError, match="placeholders without slots"):
        load_constructions(path)


def test_loader_rejects_unknown_relation(tmp_path):
    path = _write_bank(
        tmp_path,
        [
            {
                "id": "bad",
                "intent": "ответить_прямо",
                "template": "{X} — {Y}.",
                "graph_pattern": {"relation": "нет_такого"},
                "slots": {
                    "X": {"pos": "noun"},
                    "Y": {"pos": "noun"},
                },
            }
        ],
    )
    with pytest.raises(ValueError, match="unknown relation"):
        load_constructions(path)

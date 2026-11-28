"""Агрегация свойств, ответы «нет» и транзитивный вывод (DEBT-208/210/213)."""

import pytest

from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph
from griga.storage.memory import MemoryStorage


@pytest.fixture()
def graph():
    return KnowledgeGraph(MemoryStorage())


def test_property_question_aggregates_all_values(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Трава зелёная.")
    dialogue.turn("Трава мягкая.")

    answer = dialogue.turn("Какая трава?")

    assert answer.intent == "ответить_прямо"
    assert "зел" in answer.response.casefold()
    assert "мягк" in answer.response.casefold()
    assert answer.response.count(" и ") == 1


def test_repeated_property_question_does_not_repeat_verbatim(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Трава зелёная.")
    dialogue.turn("Трава мягкая.")

    first = dialogue.turn("Какая трава?")
    second = dialogue.turn("Какая трава?")

    assert first.response != second.response
    assert "зел" in second.response.casefold()
    assert "мягк" in second.response.casefold()


def test_missing_property_is_unknown_not_confirmed(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Трава зелёная.")

    answer = dialogue.turn("Трава твёрдая?")

    assert answer.intent == "признать_незнание"
    assert answer.response.casefold().startswith("у меня нет")


def test_negated_property_is_answered_with_no(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Трава синяя.")
    dialogue.turn("Нет, трава зелёная.")

    answer = dialogue.turn("Трава синяя?")

    assert answer.intent == "ответить_прямо"
    assert answer.construction_id == "no_property"
    assert answer.response.casefold().startswith("нет")


def test_conflicting_is_a_is_corrected(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Трава — это растение.")
    dialogue.turn("Трава — это животное.")

    answer = dialogue.turn("Трава — это животное?")

    assert answer.intent == "ответить_прямо"
    assert answer.construction_id == "no_is_a_conflict"
    assert answer.response.casefold().startswith("нет")
    assert "растение" in answer.response.casefold()
    assert "животное" in answer.response.casefold()


def test_transitive_place_answer(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Саша живёт в Москве.")
    dialogue.turn("Москва — это город.")

    answer = dialogue.turn("Саша живёт в городе?")

    assert answer.intent == "ответить_прямо"
    assert answer.construction_id == "yes_transitive"
    assert "Москве" in answer.response
    assert "город" in answer.response.casefold()


def test_proper_name_is_capitalized_on_acknowledge(graph):
    dialogue = Dialogue(graph, learning=False)

    answer = dialogue.turn("Саша живёт в Москве.")

    assert "Саша" in answer.response
    assert "Москве" in answer.response

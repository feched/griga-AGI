"""Определения (DEBT-215), составные термины (DEBT-211) и второе лицо (DEBT-217)."""

import pytest

from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph
from griga.graph.relations import RelationType
from griga.perception import PerceptionParser
from griga.storage.memory import MemoryStorage


@pytest.fixture()
def graph():
    return KnowledgeGraph(MemoryStorage())


@pytest.fixture(scope="module")
def parser():
    return PerceptionParser()


def test_definition_ignores_incoming_is_a(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Квазар — это галактика.")

    answer = dialogue.turn("Что такое галактика?")

    assert answer.intent == "признать_незнание"
    assert "квазар" not in answer.response.casefold()


def test_definition_uses_forward_is_a(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Галактика — это скопление.")

    answer = dialogue.turn("Что такое галактика?")

    assert answer.intent == "ответить_прямо"
    assert "скопление" in answer.response.casefold()


def test_definition_uses_forward_part_of(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Корень — часть дерева.")

    answer = dialogue.turn("Что такое корень?")

    assert answer.intent == "ответить_прямо"
    assert "дерев" in answer.response.casefold()


def test_compound_definition_is_not_a_property(parser):
    result = parser.parse("Что такое чёрная дыра?")

    assert all(
        statement.relation is not RelationType.HAS_PROPERTY
        for statement in result.statements
    )
    assert "черная дыра" in result.concept_names()


def test_compound_definition_is_answered(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Чёрная дыра — это объект.")

    answer = dialogue.turn("Что такое чёрная дыра?")

    assert answer.intent == "ответить_прямо"
    assert "объект" in answer.response.casefold()


def test_first_person_answers_in_second_person(graph):
    dialogue = Dialogue(graph, learning=False)

    ack = dialogue.turn("Я люблю кофе.")
    answer = dialogue.turn("Что я люблю?")

    assert "ты любишь" in ack.response.casefold()
    assert "ты любишь кофе" in answer.response.casefold()
    assert "пользователь" not in answer.response.casefold()


def test_greeting_and_name_question(graph):
    dialogue = Dialogue(graph, learning=False)

    greeting = dialogue.turn("Привет, меня зовут Саша.")
    answer = dialogue.turn("Как меня зовут?")

    assert "саша" in greeting.response.casefold()
    assert answer.intent == "ответить_прямо"
    assert answer.response.casefold().startswith("тебя зовут")
    assert "саша" in answer.response.casefold()

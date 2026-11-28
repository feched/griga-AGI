"""Личные факты (DEBT-207) и коррекция отрицанием (DEBT-209)."""

import pytest

from griga.dialogue import Dialogue
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.relations import RelationType
from griga.perception import PerceptionParser, apply_parse
from griga.perception.models import Polarity
from griga.storage.memory import MemoryStorage


@pytest.fixture()
def graph():
    return KnowledgeGraph(MemoryStorage())


@pytest.fixture(scope="module")
def parser():
    return PerceptionParser()


def _edge(graph, source, target, relation=RelationType.HAS_PROPERTY):
    source_node = graph.find_visible_node(source)
    target_node = graph.find_visible_node(target)
    assert source_node is not None and target_node is not None
    return graph.find_edge(source_node.id, target_node.id, relation)


def test_first_person_becomes_user_node(parser):
    result = parser.parse("Я люблю кофе.")

    statement = result.find_statement(
        "пользователь", RelationType.RELATED_TO, "кофе"
    )
    assert statement is not None
    assert statement.is_fact
    assert statement.label == "любить"


def test_name_statement(parser):
    result = parser.parse("Меня зовут Саша.")

    statement = result.find_statement(
        "пользователь", RelationType.RELATED_TO, "саша"
    )
    assert statement is not None
    assert statement.label == "имя"


def test_open_question_does_not_require_known_object(parser):
    result = parser.parse("Что я люблю?")

    statement = result.find_statement(
        "пользователь", RelationType.RELATED_TO, "что"
    )
    assert statement is not None
    assert statement.is_question
    assert statement.is_open_question
    assert statement.label == "любить"


def test_correction_is_a_fact_not_negation(parser):
    result = parser.parse("Нет, трава зелёная.")

    statement = result.find_statement(
        "трава", RelationType.HAS_PROPERTY, "зеленый"
    )
    assert statement is not None
    assert statement.correction
    assert statement.polarity is Polarity.ASSERTED
    assert statement.is_fact


def test_plain_negation_is_still_not_a_fact(parser):
    result = parser.parse("Трава не синяя.")

    statement = result.find_statement(
        "трава", RelationType.HAS_PROPERTY, "синий"
    )
    assert statement is not None
    assert statement.polarity is Polarity.NEGATED
    assert not statement.is_fact
    assert not statement.correction


def test_correction_negates_old_edge(graph, parser):
    apply_parse(parser.parse("Трава синяя."), graph)
    applied = apply_parse(parser.parse("Нет, трава зелёная."), graph)

    old = _edge(graph, "трава", "синий")
    new = _edge(graph, "трава", "зеленый")

    assert old is not None and old.is_negated
    assert old.weight == Edge.MIN_WEIGHT
    assert old.metadata["status"] == "negated"
    assert new is not None and not new.is_negated
    assert len(applied.negated_edges) == 1


def test_correction_keeps_other_relations_of_same_subject(graph, parser):
    apply_parse(parser.parse("Меня зовут Саша."), graph)
    apply_parse(parser.parse("Я люблю кофе."), graph)
    apply_parse(parser.parse("Нет, я люблю чай."), graph)

    name = _edge(graph, "пользователь", "саша", RelationType.RELATED_TO)
    coffee = _edge(graph, "пользователь", "кофе", RelationType.RELATED_TO)
    tea = _edge(graph, "пользователь", "чай", RelationType.RELATED_TO)

    assert name is not None and not name.is_negated
    assert coffee is not None and coffee.is_negated
    assert tea is not None and not tea.is_negated


def test_negated_edge_is_not_used_in_answers(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Трава синяя.")
    dialogue.turn("Нет, трава зелёная.")

    stale = dialogue.turn("Трава синяя?")
    fresh = dialogue.turn("Трава зелёная?")

    assert stale.construction_id == "no_property"
    assert stale.response.casefold().startswith("нет")
    assert "да," not in stale.response.casefold()
    assert fresh.intent == "ответить_прямо"
    assert fresh.response.casefold().startswith("да")


def test_greeting_uses_known_name(graph):
    dialogue = Dialogue(graph, learning=False)

    result = dialogue.turn("Привет, меня зовут Саша.")

    assert result.intent == "поздороваться"
    assert "саша" in result.response.casefold()

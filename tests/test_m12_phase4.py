"""M12 фаза 4: банк clarify (DEBT-214) и умная коррекция (DEBT-216)."""

import pytest

from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import NodeType
from griga.graph.relations import RelationType
from griga.storage.memory import MemoryStorage


@pytest.fixture()
def graph():
    return KnowledgeGraph(MemoryStorage())


def _edge(graph, subject: str, obj: str, relation=RelationType.HAS_PROPERTY):
    source = graph.find_visible_node(subject, NodeType.CONCEPT)
    target = graph.find_visible_node(obj)
    assert source is not None, subject
    assert target is not None, obj
    edge = graph.find_edge(source.id, target.id, relation)
    assert edge is not None, f"{subject} -{relation.value}-> {obj}"
    return edge


def test_clarify_rotates_three_different_phrases(graph):
    dialogue = Dialogue(graph, learning=False)

    turns = [dialogue.turn("Абракадабра") for _ in range(3)]

    assert all(turn.intent == "уточнить" for turn in turns)
    assert all(turn.construction_id != "fallback" for turn in turns)
    responses = [turn.response for turn in turns]
    assert len(set(responses)) == 3


def test_correction_negates_only_same_category(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Яблоко красное.")
    dialogue.turn("Яблоко круглое.")

    dialogue.turn("Нет, яблоко зелёное.")

    assert _edge(graph, "яблоко", "красный").is_negated
    assert not _edge(graph, "яблоко", "круглый").is_negated
    assert not _edge(graph, "яблоко", "зеленый").is_negated


def test_correction_without_category_negates_freshest(graph):
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Яблоко красное.")
    dialogue.turn("Яблоко мокрое.")

    dialogue.turn("Нет, яблоко сухое.")

    assert not _edge(graph, "яблоко", "красный").is_negated
    assert _edge(graph, "яблоко", "мокрый").is_negated
    assert not _edge(graph, "яблоко", "сухой").is_negated

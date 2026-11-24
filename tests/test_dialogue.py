import pytest

from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph


class MemoryStorage:
    """Хранилище-заглушка: диалог проверяется без PostgreSQL."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def load_all_nodes(self, owner_id=None, *, include_global=True):
        return list(self.nodes.values())

    def load_all_edges(self, owner_id=None, *, include_global=True):
        return list(self.edges.values())

    def save_node(self, node):
        self.nodes[node.id] = node
        return node.id

    def save_edge(self, edge):
        self.edges[edge.id] = edge
        return edge.id


@pytest.fixture()
def dialogue():
    return Dialogue(KnowledgeGraph(MemoryStorage()))


def test_dialogue_learns_and_answers(dialogue):
    dialogue.turn("Трава — это растение.")
    turn = dialogue.turn("Что такое трава?")

    assert turn.response == "Трава — это растение."
    assert turn.intent == "ответить_прямо"
    assert turn.construction_id == "answer_is_a"


def test_dialogue_answers_yes_no(dialogue):
    dialogue.turn("Трава зелёная.")
    turn = dialogue.turn("Трава зелёная?")

    assert turn.response.startswith("Да,")
    assert turn.construction_id == "yes_property"


def test_dialogue_does_not_store_questions(dialogue):
    dialogue.turn("Что такое трава?")

    assert dialogue.graph.find_node("трава") is None
    assert not dialogue.graph.edges


def test_dialogue_does_not_store_negations(dialogue):
    turn = dialogue.turn("Трава не синяя.")

    assert turn.construction_id == "ack_negation"
    assert not dialogue.graph.edges


def test_dialogue_keeps_history_and_last_response(dialogue):
    first = dialogue.turn("Привет!")
    second = dialogue.turn("Трава — это растение.")

    assert dialogue.turn_index == 2
    assert dialogue.history == [
        ("Привет!", first.response),
        ("Трава — это растение.", second.response),
    ]
    assert dialogue.last_response == second.response


def test_dialogue_refuses_actions(dialogue):
    turn = dialogue.turn("Напиши код.")

    assert turn.intent == "отказать"
    assert turn.construction_id == "refuse_action"


def test_dialogue_empathizes(dialogue):
    turn = dialogue.turn("Мне грустно.")

    assert turn.intent == "выразить_эмпатию"
    assert turn.construction_id.startswith("empathize")


def test_dialogue_memory_contains_topic(dialogue):
    dialogue.turn("Трава — это растение.")
    turn = dialogue.turn("Трава зелёная.")

    names = turn.memory.names()
    assert "трава" in names
    assert "растение" in names


def test_dialogue_admits_ignorance_without_facts(dialogue):
    turn = dialogue.turn("Что такое квазар?")

    assert turn.intent == "признать_незнание"
    assert turn.construction_id in {"unknown_generic", "unknown_topic"}


def test_dialogue_does_not_repeat_identical_answer(dialogue):
    dialogue.turn("Трава — это растение.")
    first = dialogue.turn("Что такое трава?")
    second = dialogue.turn("Что такое трава?")

    assert second.response != first.response

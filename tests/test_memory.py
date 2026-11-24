import uuid

import pytest

from griga.dialogue import Dialogue
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node, NodeType
from griga.graph.relations import RelationType
from griga.memory import UserDirectory
from griga.perception import PerceptionParser, apply_parse


class ScopedStorage:
    """In-memory хранилище с фильтрацией по owner_id, как в PostgreSQL."""

    def __init__(self):
        self.users = {}
        self.nodes = {}
        self.edges = {}

    def save_user(self, user_id, name, metadata=None):
        self.users[user_id] = {
            "id": user_id,
            "name": name,
            "metadata": dict(metadata or {}),
        }
        return user_id

    def load_users(self):
        return sorted(self.users.values(), key=lambda row: row["name"])

    def save_node(self, node):
        self.nodes[node.id] = node
        return node.id

    def save_edge(self, edge):
        self.edges[edge.id] = edge
        return edge.id

    def load_all_nodes(self, owner_id=None, *, include_global=True):
        if owner_id is None:
            return list(self.nodes.values())
        return [
            node
            for node in self.nodes.values()
            if (include_global and node.owner_id is None)
            or node.owner_id == owner_id
        ]

    def load_all_edges(self, owner_id=None, *, include_global=True):
        if owner_id is None:
            return list(self.edges.values())
        return [
            edge
            for edge in self.edges.values()
            if (include_global and edge.owner_id is None)
            or edge.owner_id == owner_id
        ]


@pytest.fixture()
def storage():
    return ScopedStorage()


@pytest.fixture()
def directory(storage):
    return UserDirectory(storage)


def add_fact(graph, subject, relation, obj, owner_id=None):
    source = graph.add_node(Node(subject, owner_id=owner_id))
    target = graph.add_node(Node(obj, owner_id=owner_id))
    graph.add_edge(
        Edge(
            source_id=source.id,
            target_id=target.id,
            relation_type=relation,
            weight=0.6,
            owner_id=owner_id,
        )
    )
    return source, target


def test_ensure_creates_user_and_center_node(storage, directory):
    user = directory.ensure("Алиса")

    assert user.name == "Алиса"
    assert directory.find("алиса").id == user.id
    assert len(storage.users) == 1

    center = storage.nodes[
        next(
            node_id
            for node_id, node in storage.nodes.items()
            if node.node_type is NodeType.USER
        )
    ]
    assert center.name == "пользователь Алиса"
    assert center.owner_id == user.id


def test_ensure_is_idempotent(directory):
    first = directory.ensure("Алиса")
    second = directory.ensure("Алиса")

    assert first.id == second.id
    assert len(directory.list_users()) == 1


def test_ensure_rejects_empty_name(directory):
    with pytest.raises(ValueError, match="non-empty"):
        directory.ensure("   ")


def test_graph_for_includes_global_and_own_nodes(storage, directory):
    alice = directory.ensure("Алиса")
    bob = directory.ensure("Боб")

    add_fact(KnowledgeGraph(storage), "трава", RelationType.IS_A, "растение")
    alice_graph = directory.graph_for(alice)
    add_fact(alice_graph, "алиса", RelationType.RELATED_TO, "кофе", alice.id)
    add_fact(
        directory.graph_for(bob), "боб", RelationType.RELATED_TO, "чай", bob.id
    )

    graph = directory.graph_for(alice)
    names = {node.name for node in graph.nodes.values()}

    assert "трава" in names
    assert "растение" in names
    assert "кофе" in names
    assert "чай" not in names
    assert graph.find_node("боб") is None


def test_graph_for_hides_other_users_edges(storage, directory):
    alice = directory.ensure("Алиса")
    bob = directory.ensure("Боб")
    add_fact(
        directory.graph_for(bob), "боб", RelationType.RELATED_TO, "чай", bob.id
    )

    alice_graph = directory.graph_for(alice)

    assert not alice_graph.edges


def test_include_global_false_returns_only_personal(storage, directory):
    alice = directory.ensure("Алиса")
    add_fact(KnowledgeGraph(storage), "трава", RelationType.IS_A, "растение")

    personal_only = KnowledgeGraph(
        storage, owner_id=alice.id, include_global=False
    )

    assert personal_only.find_node("трава") is None


def test_dialogue_writes_personal_facts(storage, directory):
    alice = directory.ensure("Алиса")
    parser = PerceptionParser()
    graph = directory.graph_for(alice)
    dialogue = Dialogue(graph, learning=False, owner_id=alice.id)

    dialogue.turn("Алиса любит кофе.")
    dialogue.turn("Трава — это растение.")

    for edge in graph.edges.values():
        assert edge.owner_id == alice.id
    for node in graph.nodes.values():
        if node.name in {"алиса", "кофе", "трава", "растение"}:
            assert node.owner_id == alice.id


def test_dialogue_isolated_between_users(storage, directory):
    alice = directory.ensure("Алиса")
    bob = directory.ensure("Боб")

    alice_dialogue = Dialogue(
        directory.graph_for(alice), learning=False, owner_id=alice.id
    )
    alice_dialogue.turn("Алиса любит кофе.")

    bob_graph = directory.graph_for(bob)
    bob_dialogue = Dialogue(bob_graph, learning=False, owner_id=bob.id)
    turn = bob_dialogue.turn("Что такое кофе?")

    assert bob_graph.find_node("кофе") is None
    assert turn.intent == "признать_незнание"


def test_global_fact_visible_to_every_user(storage, directory):
    alice = directory.ensure("Алиса")
    bob = directory.ensure("Боб")
    parser = PerceptionParser()
    apply_parse(parser.parse("Трава — это растение."), KnowledgeGraph(storage))

    for user in (alice, bob):
        graph = directory.graph_for(user)
        assert graph.find_node("трава") is not None
        assert graph.find_node("растение") is not None


def test_scoped_find_node_prefers_personal_then_global(storage, directory):
    alice = directory.ensure("Алиса")
    add_fact(KnowledgeGraph(storage), "трава", RelationType.IS_A, "растение")
    alice_graph = directory.graph_for(alice)
    add_fact(
        alice_graph, "трава", RelationType.HAS_PROPERTY, "зелёная", alice.id
    )

    graph = directory.graph_for(alice)

    personal = graph.find_node("трава")
    assert personal.owner_id == alice.id
    assert graph.find_node("растение").owner_id is None
    assert graph.find_visible_node("растение").owner_id is None


def test_get_user_by_id(directory):
    alice = directory.ensure("Алиса")

    assert directory.get(alice.id).name == "Алиса"
    assert directory.get(uuid.uuid4()) is None

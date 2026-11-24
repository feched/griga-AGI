"""Демонстрация личных подграфов и изоляции (ADR-014).

Общий граф видят все, личные факты — только владелец. Демо работает
в памяти процесса и не требует PostgreSQL.
"""

from __future__ import annotations

import sys

from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph
from griga.memory import UserDirectory


class ScopedStorage:
    """Память с фильтрацией по owner_id, как в PostgreSQL."""

    def __init__(self) -> None:
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


def say(dialogue: Dialogue, text: str) -> None:
    turn = dialogue.turn(text)
    print(f"  Вы: {text}")
    print(f"  Гриша: {turn.response}")


def describe(user, graph: KnowledgeGraph) -> None:
    personal = [
        node.name for node in graph.nodes.values() if node.owner_id == user.id
    ]
    global_names = [
        node.name for node in graph.nodes.values() if node.owner_id is None
    ]
    print(f"\n{user.name}")
    print(f"  общий слой: {', '.join(sorted(global_names)) or '—'}")
    print(f"  личное:     {', '.join(sorted(personal)) or '—'}")


def main(argv: list[str]) -> int:
    storage = ScopedStorage()
    directory = UserDirectory(storage)
    alice = directory.ensure("Алиса")
    bob = directory.ensure("Боб")

    print("1. Общий факт пишется без owner_id\n")
    global_graph = KnowledgeGraph(storage)
    say(Dialogue(global_graph, learning=False), "Трава — это растение.")

    print("\n2. Личные факты каждого пользователя\n")
    alice_graph = directory.graph_for(alice)
    alice_dialogue = Dialogue(
        alice_graph, learning=False, owner_id=alice.id
    )
    say(alice_dialogue, "Алиса любит кофе.")

    bob_graph = directory.graph_for(bob)
    bob_dialogue = Dialogue(bob_graph, learning=False, owner_id=bob.id)
    say(bob_dialogue, "Боб любит чай.")

    describe(alice, directory.graph_for(alice))
    describe(bob, directory.graph_for(bob))

    print("\n3. Изоляция: один и тот же вопрос\n")
    alice_graph = directory.graph_for(alice)
    alice_dialogue = Dialogue(
        alice_graph, learning=False, owner_id=alice.id
    )
    say(alice_dialogue, "Что такое кофе?")

    bob_graph = directory.graph_for(bob)
    bob_dialogue = Dialogue(bob_graph, learning=False, owner_id=bob.id)
    say(bob_dialogue, "Что такое кофе?")

    print("\n4. Общий факт виден обоим\n")
    say(alice_dialogue, "Что такое трава?")
    say(bob_dialogue, "Что такое трава?")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

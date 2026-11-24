"""Демонстрация обучения v0.1: Хебб, коррекция, забывание (ADR-005).

Сценарий показывает, как повторение факта усиливает связь, как
подтверждение/опровержение меняет вес и как затухание возвращает его
к минимуму. По умолчанию всё происходит в памяти процесса.
"""

from __future__ import annotations

import sys

from griga.config import LearningConfig, load_config
from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph
from griga.learning import Forgetting, SupervisedLearner


class MemoryStorage:
    """Пустая память процесса: демо не трогает базу."""

    def __init__(self) -> None:
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


def main(argv: list[str]) -> int:
    config = load_config()
    graph = KnowledgeGraph(MemoryStorage())
    dialogue = Dialogue(graph, config)

    print("1. Повторяем факт: Хебб усиливает связь\n")
    for index in range(4):
        turn = dialogue.turn("Трава — это растение.")
        edge = next(iter(graph.edges.values()))
        learned = ", ".join(
            f"{change.source_name}->{change.target_name} "
            f"{change.before}->{change.after}"
            for change in turn.learned
        )
        print(f"  ход {index + 1}: w={edge.weight:.4f}  {learned or '—'}")

    edge = next(iter(graph.edges.values()))
    print("\n2. Обучение с учителем\n")
    supervised = SupervisedLearner(graph, config)
    change = supervised.deny(edge)
    print(
        f"  опровергли: {change.before:.4f} -> {change.after:.4f} "
        f"({change.reason})"
    )
    change = supervised.confirm(edge)
    print(
        f"  подтвердили: {change.before:.4f} -> {change.after:.4f} "
        f"({change.reason})"
    )

    print("\n3. Забывание: 5 циклов затухания\n")
    fast = Forgetting(
        graph,
        LearningConfig(forgetting_factor=0.9, min_weight=0.05),
    )
    for index in range(5):
        fast.decay()
        print(f"  цикл {index + 1}: w={edge.weight:.4f}")

    print(f"\nитог: {len(graph.nodes)} узлов, {len(graph.edges)} рёбер")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

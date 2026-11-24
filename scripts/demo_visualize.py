"""Демонстрация визуализатора: граф в браузере (ADR-015 §5).

Поднимает локальный сервер на 127.0.0.1 и открывает страницу с D3.
По умолчанию строит граф в памяти процесса, чтобы демо работало без БД.
"""

from __future__ import annotations

import sys

from griga.config import load_config
from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph
from griga.visualization import VisualizerServer


FACTS = (
    "Трава — это растение.",
    "Трава зелёная.",
    "Трава растёт на газоне.",
    "Газон — это участок земли.",
    "Растение — это живой организм.",
)


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
    port = 8765
    open_browser = "--no-browser" not in argv
    for index, arg in enumerate(argv):
        if arg == "--port" and index + 1 < len(argv):
            port = int(argv[index + 1])

    config = load_config()
    graph = KnowledgeGraph(MemoryStorage())
    dialogue = Dialogue(graph, config, learning=False)
    for fact in FACTS:
        dialogue.turn(fact)

    server = VisualizerServer(graph, config, port=port)
    server.activate("трава")
    server.serve_forever(open_browser=open_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

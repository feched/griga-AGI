"""Демонстрация диалогового цикла v0.1 (ADR-004).

Реплика проходит полный путь: восприятие → граф → активация → ответ.
По умолчанию используется пустая память в процессе; с ``--db`` — рабочая
PostgreSQL из ``.env``. Сценарий можно переопределить своими репликами.
"""

from __future__ import annotations

import sys

from griga.config import load_config
from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph


DEFAULT_SCRIPT = (
    "Привет!",
    "Трава — это растение.",
    "Трава зелёная.",
    "Трава растёт на газоне.",
    "Трава не синяя.",
    "Что такое трава?",
    "Трава зелёная?",
    "Трава синяя?",
    "Где растёт трава?",
    "Что такое квазар?",
    "Мне грустно.",
    "Расскажи анекдот.",
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


def run_script(dialogue: Dialogue, script: list[str]) -> None:
    for text in script:
        turn = dialogue.turn(text)
        print(f"Вы: {text}")
        print(f"Гриша: {turn.response}")
        print(
            f"    intent={turn.intent} construction={turn.construction_id} "
            f"attempts={turn.attempts} memory={turn.memory.names()}"
        )


def main(argv: list[str]) -> int:
    use_db = "--db" in argv
    script = [part for part in argv if part != "--db"] or list(DEFAULT_SCRIPT)

    config = load_config()

    if use_db:
        from griga.env import load_dotenv
        from griga.storage.postgres import PostgresStorage

        load_dotenv()
        with PostgresStorage() as storage:
            storage.init_schema()
            graph = KnowledgeGraph(storage)
            print(f"DB: {len(graph.nodes)} nodes, {len(graph.edges)} edges\n")
            run_script(Dialogue(graph, config), script)
        return 0

    graph = KnowledgeGraph(MemoryStorage())
    print("(in-memory; добавь --db, чтобы писать в PostgreSQL)\n")
    run_script(Dialogue(graph, config), script)
    print(f"\nnodes: {len(graph.nodes)} edges: {len(graph.edges)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

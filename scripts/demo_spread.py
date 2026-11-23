"""Демонстрация волны активации на графе из PostgreSQL."""

from __future__ import annotations

from griga.config import load_config
from griga.env import load_dotenv
from griga.graph.graph import KnowledgeGraph
from griga.storage.postgres import PostgresStorage
from griga.thinking.spreader import Spreader


def main() -> int:
    load_dotenv()
    cfg = load_config()

    with PostgresStorage() as storage:
        graph = KnowledgeGraph(storage)
        grass = graph.find_node("Трава")
        if grass is None:
            print("В графе нет узла «Трава». Сначала запусти scripts.demo_roundtrip.")
            return 1

        memory = Spreader(graph, cfg).activate([grass])

        print(f"threshold={cfg.activation.threshold}, top_k={cfg.memory.top_k}")
        for item in memory:
            print(f"{item.name}: {item.activation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

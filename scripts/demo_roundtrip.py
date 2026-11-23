"""Ручная проверка шага 5: Трава --IS_A--> Растение в PostgreSQL."""

from __future__ import annotations

from griga.env import load_dotenv
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node
from griga.graph.relations import RelationType
from griga.storage.postgres import PostgresStorage


def main() -> int:
    load_dotenv()
    with PostgresStorage() as storage:
        storage.init_schema()

        graph = KnowledgeGraph(storage)
        grass = graph.add_node(Node(name="Трава"))
        plant = graph.add_node(Node(name="Растение"))
        edge = graph.add_edge(
            Edge(
                source_id=grass.id,
                target_id=plant.id,
                relation_type=RelationType.IS_A,
                weight=0.7,
            )
        )

        reloaded = KnowledgeGraph(storage)
        print(f"nodes in DB: {reloaded.node_count}")
        print(f"edges in DB: {reloaded.edge_count}")
        print(
            "edge: "
            f"{reloaded.get_node(grass.id).name} "
            f"--{edge.relation_type.value}--> "
            f"{reloaded.get_node(plant.id).name} "
            f"(w={edge.weight})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

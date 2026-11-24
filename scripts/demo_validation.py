"""Демонстрация валидации графа и аудита изменений (ADR-008).

Первый факт записывается с обычным весом, противоречащий — с низкой
уверенностью и меткой ``validation=conflict``. Каждое изменение попадает
в журнал событий. Демо работает в памяти и не требует PostgreSQL.
"""

from __future__ import annotations

import sys
import uuid

from griga.graph.graph import KnowledgeGraph
from griga.graph.relations import RelationType
from griga.perception import PerceptionParser, apply_parse


class MemoryStorage:
    """Память с audit-log, как у PostgresStorage."""

    def __init__(self) -> None:
        self.nodes = {}
        self.edges = {}
        self.events: list[dict] = []

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

    def log_event(
        self,
        entity_type,
        entity_id,
        action,
        *,
        before=None,
        after=None,
        source=None,
    ):
        self.events.append(
            {
                "id": len(self.events) + 1,
                "entity_type": entity_type,
                "entity_id": uuid.UUID(str(entity_id)),
                "action": action,
                "before": before,
                "after": after,
                "source": source,
            }
        )
        return len(self.events)

    def load_events(self, limit: int = 100):
        return list(reversed(self.events))[:limit]


def show_facts(graph: KnowledgeGraph) -> None:
    print("  Факты в графе:")
    for edge in graph.edges.values():
        source = graph.nodes[edge.source_id].name
        target = graph.nodes[edge.target_id].name
        marker = edge.metadata.get("validation")
        suffix = f"  [{marker}]" if marker else ""
        print(
            f"    {source} —{edge.relation_type.value}→ {target} "
            f"(вес {edge.weight:.2f}){suffix}"
        )


def say(dialogue_text: str, parser: PerceptionParser, graph: KnowledgeGraph):
    applied = apply_parse(parser.parse(dialogue_text), graph)
    print(f"  Вы: {dialogue_text}")
    print(
        f"       рёбер: {applied.edge_count}, "
        f"конфликтов: {applied.conflicting_edges}"
    )


def main(argv: list[str]) -> int:
    storage = MemoryStorage()
    graph = KnowledgeGraph(storage)
    parser = PerceptionParser()

    print("1. Обычный факт\n")
    say("Трава — это растение.", parser, graph)

    print("\n2. Противоречащий факт\n")
    say("Трава — это животное.", parser, graph)
    show_facts(graph)

    print("\n3. Аудит изменений\n")
    for event in storage.load_events():
        source = event["source"] or ""
        print(
            f"  {event['action']:<14} {event['entity_type']:<5} "
            f"{event['entity_id']}  {source}"
        )

    print("\n4. Свойство не конфликтует с is_a\n")
    say("Трава зелёная.", parser, graph)
    show_facts(graph)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

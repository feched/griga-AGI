"""Хранилище графа в памяти процесса (тесты, eval, демо).

Реализует тот же контракт, что и ``PostgresStorage``: узлы, рёбра и
audit-события. Данные живут только до конца процесса — PostgreSQL не
нужен. Используется многоходовыми сценариями (M11), чтобы каждый сценарий
начинался с чистого графа.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from griga.graph.edge import Edge
from griga.graph.node import Node


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class MemoryStorage:
    """Минимальное in-memory хранилище с тем же API, что у PostgreSQL."""

    def __init__(self) -> None:
        self.nodes: dict[uuid.UUID, Node] = {}
        self.edges: dict[uuid.UUID, Edge] = {}
        self.events: list[dict[str, Any]] = []
        self._events_seq = 0

    # --- nodes ---------------------------------------------------------

    def save_node(self, node: Node) -> uuid.UUID:
        self.nodes[node.id] = node
        return node.id

    def load_all_nodes(
        self,
        owner_id: uuid.UUID | str | None = None,
        *,
        include_global: bool = True,
    ) -> list[Node]:
        nodes = list(self.nodes.values())
        if owner_id is None:
            return nodes

        owner = _as_uuid(owner_id)
        if include_global:
            return [
                node
                for node in nodes
                if node.owner_id is None or node.owner_id == owner
            ]
        return [node for node in nodes if node.owner_id == owner]

    # --- edges ---------------------------------------------------------

    def save_edge(self, edge: Edge) -> uuid.UUID:
        self.edges[edge.id] = edge
        return edge.id

    def load_all_edges(
        self,
        owner_id: uuid.UUID | str | None = None,
        *,
        include_global: bool = True,
    ) -> list[Edge]:
        edges = list(self.edges.values())
        if owner_id is None:
            return edges

        owner = _as_uuid(owner_id)
        if include_global:
            return [
                edge
                for edge in edges
                if edge.owner_id is None or edge.owner_id == owner
            ]
        return [edge for edge in edges if edge.owner_id == owner]

    # --- audit ---------------------------------------------------------

    def log_event(
        self,
        entity_type: str,
        entity_id: uuid.UUID | str,
        action: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> int:
        self._events_seq += 1
        self.events.append(
            {
                "id": self._events_seq,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "action": action,
                "before": before,
                "after": after,
                "source": source,
                "created_at": datetime.now(),
            }
        )
        return self._events_seq

    def load_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return list(reversed(self.events[-limit:]))

    # --- helpers -------------------------------------------------------

    def truncate_all(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self.events.clear()
        self._events_seq = 0

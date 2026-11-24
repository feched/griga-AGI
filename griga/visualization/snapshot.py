"""Снимок графа для визуализатора (ADR-015 §5).

Снимок — чистые данные без зависимостей от D3: узлы, рёбра, активация.
Его можно отдать в JSON, сохранить в файл или использовать в тестах.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node
from griga.thinking.spreader import WorkingMemory


@dataclass(frozen=True)
class NodeView:
    id: str
    name: str
    type: str
    owner_id: str | None
    confidence: float
    activation: float = 0.0
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "owner_id": self.owner_id,
            "confidence": round(self.confidence, 4),
            "activation": round(self.activation, 4),
            "active": self.active,
        }


@dataclass(frozen=True)
class EdgeView:
    id: str
    source: str
    target: str
    relation: str
    weight: float
    label: str | None = None
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "weight": round(self.weight, 4),
            "label": self.label,
            "active": self.active,
        }


@dataclass(frozen=True)
class GraphSnapshot:
    nodes: tuple[NodeView, ...] = ()
    edges: tuple[EdgeView, ...] = ()
    threshold: float = 0.0
    top_k: int = 0
    generated_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def active_nodes(self) -> tuple[NodeView, ...]:
        return tuple(node for node in self.nodes if node.active)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "threshold": round(self.threshold, 4),
            "top_k": self.top_k,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "meta": {
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "active_count": len(self.active_nodes),
                **self.meta,
            },
        }


def _node_view(node: Node, activation: float | None) -> NodeView:
    return NodeView(
        id=str(node.id),
        name=node.name,
        type=node.node_type.value,
        owner_id=str(node.owner_id) if node.owner_id is not None else None,
        confidence=node.confidence,
        activation=activation or 0.0,
        active=activation is not None,
    )


def _edge_view(edge: Edge, active_ids: set[uuid.UUID]) -> EdgeView:
    label = edge.metadata.get("label")
    return EdgeView(
        id=str(edge.id),
        source=str(edge.source_id),
        target=str(edge.target_id),
        relation=edge.relation_type.value,
        weight=edge.weight,
        label=str(label) if label else None,
        active=(
            edge.source_id in active_ids and edge.target_id in active_ids
        ),
    )


def build_snapshot(
    graph: KnowledgeGraph,
    memory: WorkingMemory | None = None,
    *,
    meta: dict[str, Any] | None = None,
) -> GraphSnapshot:
    """Собирает снимок; активация берётся из рабочей памяти, если она есть."""
    activation = memory.as_dict() if memory is not None else {}
    active_ids = set(activation)
    nodes = tuple(
        _node_view(node, activation.get(node.id))
        for node in sorted(graph.nodes.values(), key=lambda item: item.name.casefold())
    )
    edges = tuple(
        _edge_view(edge, active_ids)
        for edge in sorted(graph.edges.values(), key=lambda item: str(item.id))
    )
    return GraphSnapshot(
        nodes=nodes,
        edges=edges,
        threshold=memory.threshold if memory is not None else 0.0,
        top_k=memory.top_k if memory is not None else 0,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        meta=dict(meta or {}),
    )


def snapshot_for_node(
    graph: KnowledgeGraph,
    name: str,
    *,
    owner_id: uuid.UUID | None = None,
) -> Node | None:
    """Ищет узел по имени для ручной активации из UI."""
    return graph.find_visible_node(name, None, owner_id)

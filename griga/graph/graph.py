"""Граф знаний в памяти с записью в PostgreSQL (ADR-006, шаг 4)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Iterable

from griga.graph.edge import Edge
from griga.graph.node import Node, NodeType
from griga.graph.relations import RelationType
from griga.storage.postgres import PostgresStorage


class KnowledgeGraph:
    """Двухуровневый граф: PostgreSQL — истина, память — быстрый доступ.

    Инвариант: новый узел/ребро сначала сохраняется в БД, и только после
    успешной записи попадает в память. Если save упал — память не меняется.
    """

    def __init__(
        self,
        storage: PostgresStorage,
        *,
        owner_id: uuid.UUID | None = None,
        include_global: bool = True,
    ) -> None:
        self.storage = storage
        self.owner_id = owner_id
        self.include_global = include_global
        self.nodes: dict[uuid.UUID, Node] = {}
        self.edges: dict[uuid.UUID, Edge] = {}
        self._by_key: dict[tuple[str, NodeType, uuid.UUID | None], Node] = {}
        self._by_name: dict[tuple[str, uuid.UUID | None], list[Node]] = defaultdict(
            list
        )
        self._out_edges: dict[uuid.UUID, list[Edge]] = defaultdict(list)
        self._in_edges: dict[uuid.UUID, list[Edge]] = defaultdict(list)
        self.reload()

    # --- loading / indexes --------------------------------------------

    def reload(self) -> "KnowledgeGraph":
        nodes = self.storage.load_all_nodes(
            self.owner_id, include_global=self.include_global
        )
        edges = self.storage.load_all_edges(
            self.owner_id, include_global=self.include_global
        )
        self.clear()
        for node in nodes:
            self._index_node(node)
        for edge in edges:
            self._index_edge(edge)
        return self

    def for_owner(self, owner_id: uuid.UUID) -> "KnowledgeGraph":
        """Новое представление графа: общий слой + подграф пользователя."""
        return KnowledgeGraph(self.storage, owner_id=owner_id)

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self._by_key.clear()
        self._by_name.clear()
        self._out_edges.clear()
        self._in_edges.clear()

    @staticmethod
    def _key(
        name: str, node_type: NodeType, owner_id: uuid.UUID | None
    ) -> tuple[str, NodeType, uuid.UUID | None]:
        return (name.strip().casefold(), node_type, owner_id)

    def _index_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self._by_key[self._key(node.name, node.node_type, node.owner_id)] = node
        self._by_name[(node.name.strip().casefold(), node.owner_id)].append(node)

    def _index_edge(self, edge: Edge) -> None:
        self.edges[edge.id] = edge
        self._out_edges[edge.source_id].append(edge)
        self._in_edges[edge.target_id].append(edge)

    # --- lookup --------------------------------------------------------

    def get_node(self, node_id: uuid.UUID | str) -> Node | None:
        node_uuid = (
            node_id if isinstance(node_id, uuid.UUID) else uuid.UUID(str(node_id))
        )
        return self.nodes.get(node_uuid)

    def find_node(
        self,
        name: str,
        node_type: NodeType | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> Node | None:
        if node_type is not None and not isinstance(node_type, NodeType):
            node_type = NodeType(node_type)

        # В графе пользователя личный узел важнее глобального.
        if owner_id is None and self.owner_id is not None:
            node = self._find_exact(name, node_type, self.owner_id)
            if node is not None:
                return node
        return self._find_exact(name, node_type, owner_id)

    def _find_exact(
        self,
        name: str,
        node_type: NodeType | None,
        owner_id: uuid.UUID | None,
    ) -> Node | None:
        if node_type is not None:
            return self._by_key.get(self._key(name, node_type, owner_id))
        candidates = self._by_name.get((name.strip().casefold(), owner_id), [])
        return candidates[0] if candidates else None

    def find_visible_node(
        self,
        name: str,
        node_type: NodeType | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> Node | None:
        """Личный узел, иначе глобальный (ADR-014)."""
        node = self.find_node(name, node_type, owner_id)
        if node is None and owner_id is not None:
            node = self.find_node(name, node_type, None)
        return node

    def find_edge(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: RelationType | str,
    ) -> Edge | None:
        if not isinstance(relation_type, RelationType):
            relation_type = RelationType(relation_type)

        for edge in self._out_edges.get(source_id, []):
            if edge.target_id == target_id and edge.relation_type == relation_type:
                return edge
        return None

    def get_out_edges(self, node_id: uuid.UUID) -> list[Edge]:
        return list(self._out_edges.get(node_id, []))

    def get_in_edges(self, node_id: uuid.UUID) -> list[Edge]:
        return list(self._in_edges.get(node_id, []))

    def neighbors(self, node_id: uuid.UUID) -> set[uuid.UUID]:
        result = {edge.target_id for edge in self._out_edges.get(node_id, [])}
        result.update(edge.source_id for edge in self._in_edges.get(node_id, []))
        return result

    # --- writes --------------------------------------------------------

    def add_node(self, node: Node) -> Node:
        """Сохраняет узел в БД и добавляет в память.

        Если такой же (имя+тип+владелец) уже есть — возвращает существующий:
        дедупликация важнее, чем создание второго «Растения».
        """
        existing = self.find_node(node.name, node.node_type, node.owner_id)
        if existing is not None:
            return existing

        node.id = self.storage.save_node(node)
        self._index_node(node)
        self._audit(
            "node",
            node.id,
            "create",
            after=node.to_row(),
            source=node.metadata.get("source"),
        )
        return node

    def add_edge(self, edge: Edge) -> Edge:
        source = self.nodes.get(edge.source_id)
        target = self.nodes.get(edge.target_id)
        if source is None or target is None:
            raise ValueError("Both edge endpoints must exist in the graph")

        if (
            source.owner_id is not None
            and target.owner_id is not None
            and source.owner_id != target.owner_id
        ):
            raise ValueError("Edge cannot connect nodes of different owners")

        if edge.owner_id is None:
            edge.owner_id = source.owner_id or target.owner_id

        existing = self.find_edge(
            edge.source_id, edge.target_id, edge.relation_type
        )
        if existing is not None:
            return existing

        edge.id = self.storage.save_edge(edge)
        self._index_edge(edge)
        self._audit(
            "edge",
            edge.id,
            "create",
            after=edge.to_row(),
            source=edge.metadata.get("source"),
        )
        return edge

    def update_edge_weight(
        self,
        edge: Edge | uuid.UUID | str,
        weight: float,
    ) -> Edge:
        """Меняет вес ребра с записью в БД (ADR-005, §5.1).

        Сначала сохраняем новое значение, и только после успешной записи
        обновляем память. Вес зажимается в допустимый схемой диапазон.
        """
        target = self._resolve_edge(edge)
        new_weight = round(
            min(Edge.MAX_WEIGHT, max(Edge.MIN_WEIGHT, float(weight))), 6
        )
        if new_weight == target.weight:
            return target

        previous = target.weight
        target.weight = new_weight
        try:
            self.storage.save_edge(target)
        except Exception:
            target.weight = previous
            raise
        self._audit(
            "edge",
            target.id,
            "update_weight",
            before={"weight": previous},
            after={"weight": target.weight},
            source=target.metadata.get("source"),
        )
        return target

    def negate_edge(
        self,
        edge: Edge | uuid.UUID | str,
        *,
        source: str | None = None,
    ) -> Edge:
        """Гасит ребро, не удаляя его (DEBT-209).

        Вес уходит в минимум схемы (0.05), в метаданные пишется
        ``status = "negated"``. Ребро остаётся в графе как история, но
        поиск/генерация его не используют.
        """
        target = self._resolve_edge(edge)
        previous_weight = target.weight
        previous_metadata = dict(target.metadata)

        target.weight = Edge.MIN_WEIGHT
        target.metadata = {**previous_metadata, "status": "negated"}
        if source:
            target.metadata["negated_by"] = source

        try:
            self.storage.save_edge(target)
        except Exception:
            target.weight = previous_weight
            target.metadata = previous_metadata
            raise
        self._audit(
            "edge",
            target.id,
            "negate",
            before={
                "weight": previous_weight,
                "status": previous_metadata.get("status"),
            },
            after={"weight": target.weight, "status": "negated"},
            source=source,
        )
        return target

    def _resolve_edge(self, edge: Edge | uuid.UUID | str) -> Edge:
        if isinstance(edge, Edge):
            found = self.edges.get(edge.id)
            if found is None:
                raise KeyError(f"Edge {edge.id} is not in the graph")
            return found
        edge_uuid = (
            edge if isinstance(edge, uuid.UUID) else uuid.UUID(str(edge))
        )
        found = self.edges.get(edge_uuid)
        if found is None:
            raise KeyError(f"Edge {edge_uuid} is not in the graph")
        return found

    # --- audit ---------------------------------------------------------

    def _audit(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
        source: str | None = None,
    ) -> None:
        """Пишет событие в audit-log, если хранилище это умеет."""
        logger = getattr(self.storage, "log_event", None)
        if logger is None:
            return
        logger(
            entity_type,
            entity_id,
            action,
            before=self._jsonable(before),
            after=self._jsonable(after),
            source=source,
        )

    @classmethod
    def _jsonable(cls, value):
        if isinstance(value, dict):
            return {key: cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._jsonable(item) for item in value]
        if isinstance(value, uuid.UUID):
            return str(value)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    # --- introspection -------------------------------------------------

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def iter_nodes(self) -> Iterable[Node]:
        return self.nodes.values()

    def __len__(self) -> int:
        return len(self.nodes)

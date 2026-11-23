"""Распространение активации по графу (ADR-003).

Четыре шага:
1. initialize — узлы реплики получают A = 1.0.
2. spread     — волна по исходящим и входящим рёбрам.
3. clamp      — после каждого шага A <= clamp (по умолчанию 1.0).
4. working_memory — сортировка, отсечение A < T, топ-K.

Формула передачи (ADR-003):
    transfer = A(current) * W(edge) * D / max(2, log(1 + degree))

Активация текущего узла сохраняется: узел остаётся «в фокусе», пока волна
идёт. Именно поэтому источник не исчезает из рабочей памяти после шага 1.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Iterable, Iterator

from griga.config import ActivationConfig, Config, load_config
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node


@dataclass(frozen=True)
class ActivatedNode:
    """Пара «узел + его активация» для рабочей памяти."""

    node: Node
    activation: float

    @property
    def id(self) -> uuid.UUID:
        return self.node.id

    @property
    def name(self) -> str:
        return self.node.name


@dataclass(frozen=True)
class WorkingMemory:
    """Топ-K активных узлов текущего хода."""

    items: tuple[ActivatedNode, ...]
    threshold: float
    top_k: int

    def __iter__(self) -> Iterator[ActivatedNode]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> ActivatedNode:
        return self.items[index]

    def node_ids(self) -> list[uuid.UUID]:
        return [item.id for item in self.items]

    def names(self) -> list[str]:
        return [item.name for item in self.items]

    def as_dict(self) -> dict[uuid.UUID, float]:
        return {item.id: item.activation for item in self.items}

    @property
    def is_empty(self) -> bool:
        return not self.items


class Spreader:
    """Волна активации по KnowledgeGraph."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        config: Config | ActivationConfig | None = None,
        *,
        top_k: int | None = None,
    ) -> None:
        if config is None:
            config = load_config()

        if isinstance(config, Config):
            self.config = config.activation
            default_top_k = config.memory.top_k
        else:
            self.config = config
            default_top_k = 5

        self.graph = graph
        self.top_k = top_k if top_k is not None else default_top_k
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")

    # --- шаг 1: инициализация -----------------------------------------

    def initialize(
        self, nodes: Iterable[Node | uuid.UUID | str]
    ) -> dict[uuid.UUID, float]:
        """Выдаёт стартовым узлам A = clamp (1.0). Неизвестные узлы игнорирует."""
        activation: dict[uuid.UUID, float] = {}
        for item in nodes:
            node = self._resolve_node(item)
            if node is None:
                continue
            activation[node.id] = self.config.clamp
        return activation

    # --- шаг 2: волна -------------------------------------------------

    def spread(
        self,
        nodes: Iterable[Node | uuid.UUID | str],
        *,
        max_depth: int | None = None,
    ) -> dict[uuid.UUID, float]:
        """Запускает волну и возвращает активацию всех затронутых узлов."""
        activation = self.initialize(nodes)
        if not activation:
            return activation

        depth_limit = self.config.max_depth if max_depth is None else max_depth
        if depth_limit < 0:
            raise ValueError("max_depth must be >= 0")

        for _ in range(depth_limit):
            activation = self._step(activation)
            if not self._has_active(activation):
                break

        return activation

    def _step(self, activation: dict[uuid.UUID, float]) -> dict[uuid.UUID, float]:
        next_activation = dict(activation)

        for node_id, level in activation.items():
            if level < self.config.threshold:
                continue

            node = self.graph.nodes.get(node_id)
            if node is None:
                continue

            outgoing = self.graph.get_out_edges(node_id)
            incoming = self.graph.get_in_edges(node_id)
            fan = self._fan_factor(len(outgoing) + len(incoming))

            for edge in outgoing:
                self._deliver(
                    next_activation,
                    target_id=edge.target_id,
                    level=level,
                    weight=edge.weight,
                    fan=fan,
                )
            for edge in incoming:
                self._deliver(
                    next_activation,
                    target_id=edge.source_id,
                    level=level,
                    weight=edge.weight,
                    fan=fan,
                )

        # Шаг 3: жёсткий clamp после каждого шага.
        for node_id, level in next_activation.items():
            next_activation[node_id] = min(
                self.config.clamp, max(0.0, level)
            )

        return next_activation

    def _deliver(
        self,
        activation: dict[uuid.UUID, float],
        *,
        target_id: uuid.UUID,
        level: float,
        weight: float,
        fan: float,
    ) -> None:
        if target_id not in self.graph.nodes:
            return

        transfer = level * weight * self.config.decay / fan
        if transfer <= 0.0:
            return

        current = activation.get(target_id, 0.0)
        activation[target_id] = min(self.config.clamp, current + transfer)

    def _fan_factor(self, degree: int) -> float:
        if not self.config.fan_effect:
            return 1.0
        return max(2.0, math.log1p(degree))

    def _has_active(self, activation: dict[uuid.UUID, float]) -> bool:
        return any(
            level >= self.config.threshold for level in activation.values()
        )

    # --- шаг 4: рабочая память ---------------------------------------

    def working_memory(
        self,
        activation: dict[uuid.UUID, float],
        *,
        top_k: int | None = None,
    ) -> WorkingMemory:
        """Сортирует активные узлы, отсекает A < T и берёт топ-K."""
        limit = top_k if top_k is not None else self.top_k
        if limit < 1:
            raise ValueError("top_k must be >= 1")

        active: list[tuple[uuid.UUID, float]] = [
            (node_id, level)
            for node_id, level in activation.items()
            if level >= self.config.threshold and node_id in self.graph.nodes
        ]
        active.sort(
            key=lambda item: (
                -item[1],
                self.graph.nodes[item[0]].name.casefold(),
                str(item[0]),
            )
        )

        items = tuple(
            ActivatedNode(
                node=self.graph.nodes[node_id],
                activation=round(level, 4),
            )
            for node_id, level in active[:limit]
        )
        return WorkingMemory(
            items=items,
            threshold=self.config.threshold,
            top_k=limit,
        )

    def activate(
        self,
        nodes: Iterable[Node | uuid.UUID | str],
        *,
        max_depth: int | None = None,
        top_k: int | None = None,
    ) -> WorkingMemory:
        """Удобный полный цикл: initialize -> spread -> working_memory."""
        activation = self.spread(nodes, max_depth=max_depth)
        return self.working_memory(activation, top_k=top_k)

    # --- helpers -------------------------------------------------------

    def _resolve_node(
        self, item: Node | uuid.UUID | str
    ) -> Node | None:
        if isinstance(item, Node):
            return self.graph.nodes.get(item.id)
        if isinstance(item, uuid.UUID):
            return self.graph.nodes.get(item)
        return self.graph.get_node(uuid.UUID(str(item)))

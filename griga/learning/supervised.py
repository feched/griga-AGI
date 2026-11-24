"""Обучение с учителем: подтверждение и опровержение факта (ADR-005 §5.2).

Пользователь может усилить или ослабить конкретное ребро. Шаг фиксирован
параметром ``learning.supervised_delta``; вес зажимается в [0.05, 1.0].
"""

from __future__ import annotations

import uuid

from griga.config import Config, LearningConfig
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph

from griga.learning.hebb import EdgeChange, _learning_config


class SupervisedLearner:
    """Ручная коррекция веса ребра по обратной связи."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        config: Config | LearningConfig | None = None,
    ) -> None:
        self.graph = graph
        self.config = _learning_config(config)

    def confirm(
        self,
        edge: Edge | uuid.UUID | str,
        *,
        delta: float | None = None,
    ) -> EdgeChange:
        return self._adjust(edge, +1.0, delta, reason="confirm")

    def deny(
        self,
        edge: Edge | uuid.UUID | str,
        *,
        delta: float | None = None,
    ) -> EdgeChange:
        return self._adjust(edge, -1.0, delta, reason="deny")

    def _adjust(
        self,
        edge: Edge | uuid.UUID | str,
        direction: float,
        delta: float | None,
        *,
        reason: str,
    ) -> EdgeChange:
        step = self.config.supervised_delta if delta is None else abs(delta)
        target = self.graph._resolve_edge(edge)
        before = target.weight
        after = target.weight + direction * step
        self.graph.update_edge_weight(target, after)

        source = self.graph.nodes.get(target.source_id)
        dest = self.graph.nodes.get(target.target_id)
        return EdgeChange(
            edge_id=target.id,
            source_name=source.name if source is not None else "?",
            target_name=dest.name if dest is not None else "?",
            relation=target.relation_type,
            before=round(before, 6),
            after=round(target.weight, 6),
            reason=reason,
        )

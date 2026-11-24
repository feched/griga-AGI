"""Обучение по Хеббу: одновременная активация усиливает связь (ADR-005 §5.1).

Формула: ``Δw = η × x_A × x_B``, где ``x`` — активация узлов в рабочей
памяти. Меняются только уже существующие рёбра; новые создаёт парсер.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from griga.config import Config, LearningConfig, load_config
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.relations import RelationType
from griga.thinking.spreader import WorkingMemory


@dataclass(frozen=True)
class EdgeChange:
    """Одно изменение веса ребра — для логов и тестов."""

    edge_id: uuid.UUID
    source_name: str
    target_name: str
    relation: RelationType
    before: float
    after: float
    reason: str = "hebb"

    @property
    def delta(self) -> float:
        return round(self.after - self.before, 6)


def _learning_config(
    config: Config | LearningConfig | None,
) -> LearningConfig:
    if config is None:
        return load_config().learning
    if isinstance(config, Config):
        return config.learning
    return config


class HebbLearner:
    """Усиливает рёбра между узлами, активными в одном такте."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        config: Config | LearningConfig | None = None,
    ) -> None:
        self.graph = graph
        self.config = _learning_config(config)

    def reinforce(self, memory: WorkingMemory) -> tuple[EdgeChange, ...]:
        activations = memory.as_dict()
        if len(activations) < 2:
            return ()

        changes: list[EdgeChange] = []
        for edge in sorted(self.graph.edges.values(), key=lambda item: str(item.id)):
            source_activation = activations.get(edge.source_id)
            target_activation = activations.get(edge.target_id)
            if source_activation is None or target_activation is None:
                continue

            delta = self.config.eta * source_activation * target_activation
            if delta <= 0.0:
                continue

            after = min(self.config.max_weight, edge.weight + delta)
            if after <= edge.weight:
                continue

            before = edge.weight
            self.graph.update_edge_weight(edge, after)
            changes.append(self._change(edge, before, edge.weight))

        return tuple(changes)

    def _change(self, edge: Edge, before: float, after: float) -> EdgeChange:
        source = self.graph.nodes.get(edge.source_id)
        target = self.graph.nodes.get(edge.target_id)
        return EdgeChange(
            edge_id=edge.id,
            source_name=source.name if source is not None else "?",
            target_name=target.name if target is not None else "?",
            relation=edge.relation_type,
            before=round(before, 6),
            after=round(after, 6),
            reason="hebb",
        )

"""Забывание: периодическое затухание весов рёбер (ADR-005 §5.3).

Каждые ``learning.forgetting_every_turns`` ходов все веса умножаются на
``learning.forgetting_factor``. Слабые связи не удаляются, а опускаются
до ``min_weight`` — так граф не теряет структуру, но перестаёт «залипать»
на редких связях.
"""

from __future__ import annotations

from dataclasses import dataclass

from griga.config import Config, LearningConfig
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph

from griga.learning.hebb import EdgeChange, _learning_config


@dataclass(frozen=True)
class ForgettingResult:
    turn_index: int
    applied: bool
    changes: tuple[EdgeChange, ...] = ()

    @property
    def edge_count(self) -> int:
        return len(self.changes)


class Forgetting:
    """Считает, когда пора забывать, и применяет затухание."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        config: Config | LearningConfig | None = None,
    ) -> None:
        self.graph = graph
        self.config = _learning_config(config)

    def due(self, turn_index: int) -> bool:
        every = self.config.forgetting_every_turns
        if every <= 0:
            return False
        return turn_index > 0 and turn_index % every == 0

    def decay(self) -> tuple[EdgeChange, ...]:
        changes: list[EdgeChange] = []
        for edge in sorted(self.graph.edges.values(), key=lambda item: str(item.id)):
            before = edge.weight
            after = before * self.config.forgetting_factor
            if after < self.config.min_weight:
                after = self.config.min_weight
            if after >= before:
                continue

            self.graph.update_edge_weight(edge, after)
            source = self.graph.nodes.get(edge.source_id)
            target = self.graph.nodes.get(edge.target_id)
            changes.append(
                EdgeChange(
                    edge_id=edge.id,
                    source_name=source.name if source is not None else "?",
                    target_name=target.name if target is not None else "?",
                    relation=edge.relation_type,
                    before=round(before, 6),
                    after=round(edge.weight, 6),
                    reason="forgetting",
                )
            )
        return tuple(changes)

    def tick(self, turn_index: int) -> ForgettingResult:
        if not self.due(turn_index):
            return ForgettingResult(turn_index=turn_index, applied=False)
        return ForgettingResult(
            turn_index=turn_index,
            applied=True,
            changes=self.decay(),
        )

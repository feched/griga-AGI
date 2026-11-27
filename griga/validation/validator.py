"""Валидация графа: защита от противоречий (ADR-008).

В v0.1 проверяются функциональные отношения: у концепта может быть только
один ``is_a`` и один ``part_of``. Противоречащий факт не отбрасывается
молча — он записывается с низкой уверенностью, чтобы старый факт остался
сильнее.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from griga.graph.graph import KnowledgeGraph
from griga.graph.relations import RelationType
from griga.perception.models import Statement


FUNCTIONAL_RELATIONS = frozenset(
    {RelationType.IS_A, RelationType.PART_OF}
)


@dataclass(frozen=True)
class Conflict:
    relation: RelationType
    existing_edge_id: uuid.UUID
    existing_object: str
    new_object: str

    @property
    def reason(self) -> str:
        return (
            f"{self.relation.value}: уже есть {self.existing_object!r}, "
            f"а не {self.new_object!r}"
        )


@dataclass(frozen=True)
class ValidationDecision:
    accepted: bool
    confidence: float
    conflicts: tuple[Conflict, ...] = ()
    reason: str = ""

    @property
    def is_conflict(self) -> bool:
        return bool(self.conflicts)


class GraphValidator:
    """Проверяет утверждение перед записью в граф."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        *,
        conflict_confidence: float = 0.15,
    ) -> None:
        if not 0.05 <= conflict_confidence <= 1.0:
            raise ValueError("conflict_confidence must be in [0.05, 1.0]")
        self.graph = graph
        self.conflict_confidence = conflict_confidence

    def check(
        self,
        statement: Statement,
        owner_id: uuid.UUID | None = None,
    ) -> ValidationDecision:
        if not statement.is_fact:
            return ValidationDecision(
                accepted=False,
                confidence=0.0,
                reason="not a fact",
            )

        if statement.relation not in FUNCTIONAL_RELATIONS:
            return ValidationDecision(
                accepted=True,
                confidence=statement.weight,
                reason="not functional",
            )

        subject = self.graph.find_visible_node(
            statement.subject.lemma,
            statement.subject.node_type,
            owner_id,
        )
        if subject is None:
            return ValidationDecision(
                accepted=True,
                confidence=statement.weight,
                reason="new subject",
            )

        conflicts = self._conflicts(subject.id, statement)
        if not conflicts:
            return ValidationDecision(
                accepted=True,
                confidence=statement.weight,
                reason="no conflict",
            )

        return ValidationDecision(
            accepted=False,
            confidence=self.conflict_confidence,
            conflicts=conflicts,
            reason="; ".join(conflict.reason for conflict in conflicts),
        )

    def _conflicts(
        self,
        subject_id: uuid.UUID,
        statement: Statement,
    ) -> tuple[Conflict, ...]:
        wanted = statement.object.lemma.strip().casefold()
        found: list[Conflict] = []

        for edge in self.graph.get_out_edges(subject_id):
            if edge.relation_type is not statement.relation:
                continue
            if edge.is_negated:
                continue
            target = self.graph.nodes.get(edge.target_id)
            if target is None:
                continue
            if target.name.strip().casefold() == wanted:
                continue
            found.append(
                Conflict(
                    relation=edge.relation_type,
                    existing_edge_id=edge.id,
                    existing_object=target.name,
                    new_object=statement.object.lemma,
                )
            )
        return tuple(found)

"""Запись результата Perception в граф (ADR-002 → ADR-001).

В долговременный граф попадают только факты: ``statement.is_fact`` (не
вопросы, не отрицания, не «наверное»). Узлы создаются для концов фактов,
чтобы вопросы и болтовня не засоряли граф.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node
from griga.graph.relations import RelationType, label_matches
from griga.perception.models import (
    Mention,
    ParseResult,
    Polarity,
    Statement,
)
from griga.validation import GraphValidator


@dataclass(frozen=True)
class AppliedParse:
    """Что реально добавилось в граф после одной реплики."""

    created_nodes: tuple[Node, ...] = ()
    created_edges: tuple[Edge, ...] = ()
    skipped_statements: int = 0
    duplicate_edges: int = 0
    conflicting_edges: int = 0
    negated_edges: tuple[Edge, ...] = ()

    @property
    def node_count(self) -> int:
        return len(self.created_nodes)

    @property
    def edge_count(self) -> int:
        return len(self.created_edges)


def _ensure_node(
    graph: KnowledgeGraph,
    mention: Mention,
    owner_id: uuid.UUID | None,
    confidence: float,
    *,
    source: str | None = None,
) -> tuple[Node | None, bool]:
    existing = graph.find_node(mention.lemma, mention.node_type, owner_id)
    if existing is not None:
        return existing, False

    metadata = {"pos": mention.pos, "form": mention.form}
    if source:
        metadata["source"] = source

    node = Node(
        name=mention.lemma,
        node_type=mention.node_type,
        owner_id=owner_id,
        confidence=confidence,
        metadata=metadata,
    )
    graph.add_node(node)
    return node, True


def _apply_statement(
    graph: KnowledgeGraph,
    statement: Statement,
    owner_id: uuid.UUID | None,
    *,
    weight: float | None = None,
    metadata_extra: dict | None = None,
) -> tuple[Node | None, Node | None, Edge | None, bool]:
    subject, subject_created = _ensure_node(
        graph,
        statement.subject,
        owner_id,
        statement.confidence,
        source=statement.source_text,
    )
    obj, object_created = _ensure_node(
        graph,
        statement.object,
        owner_id,
        statement.confidence,
        source=statement.source_text,
    )
    if subject is None or obj is None or subject.id == obj.id:
        return subject, obj, None, False

    existing = graph.find_edge(subject.id, obj.id, statement.relation)
    if existing is not None:
        return subject, obj, None, False

    metadata = {
        "label": statement.label,
        "source": statement.source_text,
        "pos_subject": statement.subject.pos,
        "pos_object": statement.object.pos,
    }
    if metadata_extra:
        metadata.update(metadata_extra)

    edge = Edge(
        source_id=subject.id,
        target_id=obj.id,
        relation_type=statement.relation,
        weight=max(0.05, min(1.0, statement.weight if weight is None else weight)),
        owner_id=owner_id,
        metadata=metadata,
    )
    graph.add_edge(edge)
    return subject, obj, edge, subject_created or object_created


def _negate_for_statement(
    graph: KnowledgeGraph,
    statement: Statement,
    owner_id: uuid.UUID | None,
) -> list[Edge]:
    """Гасит рёбра, которые опровергает коррекция (DEBT-209).

    «Нет, трава зелёная» отменяет прежние свойства того же субъекта.
    Ограничение v0.1: измерения свойств не различаются, поэтому гасятся
    все рёбра того же отношения, кроме нового объекта.
    """
    subject = graph.find_visible_node(
        statement.subject.lemma,
        statement.subject.node_type,
        owner_id,
    )
    if subject is None:
        return []

    wanted = statement.object.lemma.strip().casefold()
    negated: list[Edge] = []

    def same_relation(edge: Edge) -> bool:
        if edge.relation_type is not statement.relation:
            return False
        # «Нет, я люблю чай» не должно гасить «имя» или «жить_в».
        if statement.relation is RelationType.RELATED_TO:
            return label_matches(
                statement.label, edge.metadata.get("label")
            )
        return True

    if statement.polarity is Polarity.NEGATED:
        # «Трава не синяя» гасит именно ребро к синему.
        candidates = [
            edge
            for edge in graph.get_out_edges(subject.id)
            if same_relation(edge)
            and not edge.is_negated
            and (target := graph.nodes.get(edge.target_id)) is not None
            and target.name.strip().casefold() == wanted
        ]
    else:
        candidates = [
            edge
            for edge in graph.get_out_edges(subject.id)
            if same_relation(edge)
            and not edge.is_negated
            and (target := graph.nodes.get(edge.target_id)) is not None
            and target.name.strip().casefold() != wanted
        ]

    for edge in candidates:
        if owner_id is not None and edge.owner_id not in (None, owner_id):
            continue
        negated.append(
            graph.negate_edge(edge, source=statement.source_text)
        )
    return negated


def apply_parse(
    result: ParseResult,
    graph: KnowledgeGraph,
    *,
    owner_id: uuid.UUID | None = None,
    include_all_mentions: bool = False,
    validator: GraphValidator | None = None,
    validate: bool = True,
) -> AppliedParse:
    """Переносит факты из ``ParseResult`` в ``KnowledgeGraph``.

    ``include_all_mentions=True`` дополнительно создаёт узлы для всех
    упоминаний, включая те, что не попали в факты (например, из вопроса).
    По умолчанию граф не засоряется.

    ``validator`` проверяет противоречия (ADR-008): конфликтующий факт
    пишется с низкой уверенностью, а не затирает старый.
    """
    if validator is None and validate:
        validator = GraphValidator(graph)

    created_nodes: list[Node] = []
    created_edges: list[Edge] = []
    seen_nodes: set[uuid.UUID] = set()
    skipped = 0
    duplicates = 0
    conflicts = 0

    def remember(node: Node | None) -> None:
        if node is not None and node.id not in seen_nodes:
            seen_nodes.add(node.id)
            created_nodes.append(node)

    if include_all_mentions:
        for mention in result.nodes:
            node, created = _ensure_node(
                graph,
                mention,
                owner_id,
                confidence=0.5,
                source=result.text,
            )
            if created:
                remember(node)

    negated_edges: list[Edge] = []

    for statement in result.statements:
        if statement.is_question:
            skipped += 1
            continue

        # Коррекция и отрицание гасят старые рёбра (DEBT-209).
        if statement.correction or statement.polarity is Polarity.NEGATED:
            negated_edges.extend(
                _negate_for_statement(graph, statement, owner_id)
            )
            if not statement.is_fact:
                skipped += 1
                continue

        if not statement.is_fact:
            skipped += 1
            continue

        weight = None
        metadata_extra = None
        if validator is not None:
            decision = validator.check(statement, owner_id)
            if decision.is_conflict:
                weight = decision.confidence
                metadata_extra = {
                    "validation": "conflict",
                    "conflicts_with": [
                        str(conflict.existing_edge_id)
                        for conflict in decision.conflicts
                    ],
                    "conflict_reason": decision.reason,
                }
                conflicts += 1

        subject, obj, edge, _ = _apply_statement(
            graph,
            statement,
            owner_id,
            weight=weight,
            metadata_extra=metadata_extra,
        )
        if edge is None:
            duplicates += 1
            continue

        remember(subject)
        remember(obj)
        created_edges.append(edge)

    return AppliedParse(
        created_nodes=tuple(created_nodes),
        created_edges=tuple(created_edges),
        skipped_statements=skipped,
        duplicate_edges=duplicates,
        conflicting_edges=conflicts,
        negated_edges=tuple(negated_edges),
    )

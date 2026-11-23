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
from griga.perception.models import Mention, ParseResult, Statement


@dataclass(frozen=True)
class AppliedParse:
    """Что реально добавилось в граф после одной реплики."""

    created_nodes: tuple[Node, ...] = ()
    created_edges: tuple[Edge, ...] = ()
    skipped_statements: int = 0
    duplicate_edges: int = 0

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
) -> tuple[Node | None, bool]:
    existing = graph.find_node(mention.lemma, mention.node_type, owner_id)
    if existing is not None:
        return existing, False

    node = Node(
        name=mention.lemma,
        node_type=mention.node_type,
        owner_id=owner_id,
        confidence=confidence,
        metadata={"pos": mention.pos, "form": mention.form},
    )
    graph.add_node(node)
    return node, True


def _apply_statement(
    graph: KnowledgeGraph,
    statement: Statement,
    owner_id: uuid.UUID | None,
) -> tuple[Node | None, Node | None, Edge | None, bool]:
    subject, subject_created = _ensure_node(
        graph, statement.subject, owner_id, statement.confidence
    )
    obj, object_created = _ensure_node(
        graph, statement.object, owner_id, statement.confidence
    )
    if subject is None or obj is None or subject.id == obj.id:
        return subject, obj, None, False

    existing = graph.find_edge(subject.id, obj.id, statement.relation)
    if existing is not None:
        return subject, obj, None, False

    edge = Edge(
        source_id=subject.id,
        target_id=obj.id,
        relation_type=statement.relation,
        weight=max(0.05, min(1.0, statement.weight)),
        owner_id=owner_id,
        metadata={
            "label": statement.label,
            "source": statement.source_text,
            "pos_subject": statement.subject.pos,
            "pos_object": statement.object.pos,
        },
    )
    graph.add_edge(edge)
    return subject, obj, edge, subject_created or object_created


def apply_parse(
    result: ParseResult,
    graph: KnowledgeGraph,
    *,
    owner_id: uuid.UUID | None = None,
    include_all_mentions: bool = False,
) -> AppliedParse:
    """Переносит факты из ``ParseResult`` в ``KnowledgeGraph``.

    ``include_all_mentions=True`` дополнительно создаёт узлы для всех
    упоминаний, включая те, что не попали в факты (например, из вопроса).
    По умолчанию граф не засоряется.
    """
    created_nodes: list[Node] = []
    created_edges: list[Edge] = []
    seen_nodes: set[uuid.UUID] = set()
    skipped = 0
    duplicates = 0

    def remember(node: Node | None) -> None:
        if node is not None and node.id not in seen_nodes:
            seen_nodes.add(node.id)
            created_nodes.append(node)

    if include_all_mentions:
        for mention in result.nodes:
            node, created = _ensure_node(
                graph, mention, owner_id, confidence=0.5
            )
            if created:
                remember(node)

    for statement in result.statements:
        if not statement.is_fact:
            skipped += 1
            continue

        subject, obj, edge, _ = _apply_statement(graph, statement, owner_id)
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
    )

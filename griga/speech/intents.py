"""Выбор коммуникативного намерения (ADR-004, шаг 1).

Намерение — функция ответа, а не слово. Правила разрешения:

- приветствие → поздороваться;
- эмоция → выразить эмпатию;
- команда → отказать (v0.1 не выполняет действий);
- вопрос с найденным фактом → ответить прямо/с оговоркой;
- вопрос без факта → признать незнание;
- новая информация → запомнить факт;
- непонятная реплика → уточнить.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node, NodeType
from griga.graph.relations import RelationType, label_matches
from griga.perception.models import ParseResult, Polarity, SpeechAct, Statement
from griga.thinking.spreader import WorkingMemory


class Intent(str, Enum):
    """Стартовый набор ADR-004 + служебные намерения v0.1."""

    GREET = "поздороваться"
    EMPATHIZE = "выразить_эмпатию"
    ANSWER_DIRECTLY = "ответить_прямо"
    ANSWER_WITH_HEDGE = "ответить_с_оговоркой"
    ADMIT_IGNORANCE = "признать_незнание"
    ACKNOWLEDGE = "запомнить_факт"
    CLARIFY = "уточнить"
    REFUSE = "отказать"


@dataclass(frozen=True)
class IntentDecision:
    intent: Intent
    confidence: float = 1.0
    topic: Node | None = None
    reason: str = ""


def question_statements(result: ParseResult):
    return tuple(
        statement for statement in result.statements if statement.is_question
    )


def topic_node(
    result: ParseResult,
    graph: KnowledgeGraph,
    memory: WorkingMemory,
    owner_id: uuid.UUID | None = None,
) -> Node | None:
    """Первый концепт реплики, который реально есть в графе."""
    for mention in result.concepts():
        node = graph.find_visible_node(
            mention.lemma, mention.node_type, owner_id
        )
        if node is not None:
            return node

    for item in memory:
        if item.node.node_type is NodeType.CONCEPT:
            return item.node
    return None


def visible_edges(
    graph: KnowledgeGraph,
    node: Node,
    owner_id: uuid.UUID | None = None,
):
    """Исходящие и входящие рёбра, доступные этому пользователю."""
    edges = graph.get_out_edges(node.id) + graph.get_in_edges(node.id)
    edges = [edge for edge in edges if not edge.is_negated]
    if owner_id is None:
        return edges
    return [
        edge
        for edge in edges
        if edge.owner_id is None or edge.owner_id == owner_id
    ]


def open_question_edges(
    graph: KnowledgeGraph,
    subject: Node,
    statement: Statement,
    owner_id: uuid.UUID | None = None,
):
    """Рёбра субъекта, подходящие под открытый вопрос (DEBT-207)."""
    edges = graph.get_out_edges(subject.id)
    if owner_id is not None:
        edges = [
            edge
            for edge in edges
            if edge.owner_id is None or edge.owner_id == owner_id
        ]
    edges = [edge for edge in edges if not edge.is_negated]

    if statement.relation is RelationType.RELATED_TO:
        return [
            edge
            for edge in edges
            if edge.relation_type is RelationType.RELATED_TO
            and label_matches(
                statement.label, edge.metadata.get("label")
            )
        ]
    return [
        edge
        for edge in edges
        if edge.relation_type is statement.relation
    ]


def definition_edges(
    graph: KnowledgeGraph,
    node: Node,
    owner_id: uuid.UUID | None = None,
):
    """Рёбра, которые годятся для ответа «Что такое X?» (DEBT-215).

    Сначала исходящие определения (is_a, part_of), потом прочие
    исходящие связи. Входящие is_a не годятся: «квазар → галактика» не
    делает галактику квазаром. Входящие прочие связи допустимы как
    слабый ответ («Что такое свет?» → «Солнце даёт свет»).
    """
    def allowed(edge) -> bool:
        return not edge.is_negated and (
            owner_id is None or edge.owner_id in (None, owner_id)
        )

    out = [edge for edge in graph.get_out_edges(node.id) if allowed(edge)]
    definitional = [
        edge
        for edge in out
        if edge.relation_type in {RelationType.IS_A, RelationType.PART_OF}
    ]
    if definitional:
        return definitional
    if out:
        return out
    return [
        edge
        for edge in graph.get_in_edges(node.id)
        if allowed(edge) and edge.relation_type is not RelationType.IS_A
    ]


def choose_intent(
    result: ParseResult,
    graph: KnowledgeGraph,
    memory: WorkingMemory,
    owner_id: uuid.UUID | None = None,
) -> IntentDecision:
    markers = result.markers
    topic = topic_node(result, graph, memory, owner_id)

    if markers.is_greeting:
        return IntentDecision(Intent.GREET, reason="greeting")

    if markers.speech_act is SpeechAct.COMMAND:
        return IntentDecision(Intent.REFUSE, reason="command")

    if markers.emotion is not None:
        return IntentDecision(Intent.EMPATHIZE, reason="emotion")

    if markers.is_question:
        # «Что такое X?» — определение ищется только по исходящим is_a:
        # входящее «квазар → галактика» не делает галактику квазаром
        # (DEBT-215).
        if markers.definition:
            if topic is None:
                return IntentDecision(
                    Intent.ADMIT_IGNORANCE,
                    confidence=0.0,
                    reason="definition topic is unknown",
                )
            edges = definition_edges(graph, topic, owner_id)
            if not edges:
                return IntentDecision(
                    Intent.ADMIT_IGNORANCE,
                    confidence=0.0,
                    topic=topic,
                    reason="definition not found",
                )
            best = max(edge.weight for edge in edges)
            intent = (
                Intent.ANSWER_DIRECTLY
                if best >= 0.5
                else Intent.ANSWER_WITH_HEDGE
            )
            return IntentDecision(
                intent,
                confidence=best,
                topic=topic,
                reason="definition found",
            )

        asked = question_statements(result)
        if asked:
            statement = asked[0]
            subject = graph.find_visible_node(
                statement.subject.lemma,
                statement.subject.node_type,
                owner_id,
            )
            obj = graph.find_visible_node(
                statement.object.lemma,
                statement.object.node_type,
                owner_id,
            )

            if (
                subject is not None
                and obj is None
                and statement.is_open_question
            ):
                edges = open_question_edges(
                    graph, subject, statement, owner_id
                )
                if not edges:
                    return IntentDecision(
                        Intent.ADMIT_IGNORANCE,
                        confidence=0.0,
                        topic=topic or subject,
                        reason="open question fact not found",
                    )
                best = max(edge.weight for edge in edges)
                intent = (
                    Intent.ANSWER_DIRECTLY
                    if best >= 0.5
                    else Intent.ANSWER_WITH_HEDGE
                )
                return IntentDecision(
                    intent,
                    confidence=best,
                    topic=topic or subject,
                    reason="open question fact found",
                )
            edge = None
            if subject is not None and obj is not None:
                edge = graph.find_edge(
                    subject.id, obj.id, statement.relation
                )

            if edge is not None and not edge.is_negated:
                intent = (
                    Intent.ANSWER_DIRECTLY
                    if edge.weight >= 0.5
                    else Intent.ANSWER_WITH_HEDGE
                )
                return IntentDecision(
                    intent,
                    confidence=edge.weight,
                    topic=topic or subject,
                    reason="yes/no fact found",
                )
            return IntentDecision(
                Intent.ADMIT_IGNORANCE,
                confidence=0.0,
                topic=topic,
                reason="yes/no fact not found",
            )

        if topic is None:
            return IntentDecision(
                Intent.ADMIT_IGNORANCE,
                confidence=0.0,
                reason="question topic is unknown",
            )

        edges = visible_edges(graph, topic, owner_id)
        if not edges:
            return IntentDecision(
                Intent.ADMIT_IGNORANCE,
                confidence=0.0,
                topic=topic,
                reason="no edges around topic",
            )

        best = max(edge.weight for edge in edges)
        intent = (
            Intent.ANSWER_DIRECTLY
            if best >= 0.5
            else Intent.ANSWER_WITH_HEDGE
        )
        return IntentDecision(
            intent,
            confidence=best,
            topic=topic,
            reason="question fact found",
        )

    if result.facts():
        return IntentDecision(
            Intent.ACKNOWLEDGE,
            confidence=max(item.confidence for item in result.facts()),
            topic=topic,
            reason="new facts",
        )

    if any(
        item.polarity is not Polarity.ASSERTED
        for item in result.statements
    ):
        return IntentDecision(
            Intent.ACKNOWLEDGE,
            confidence=0.4,
            topic=topic,
            reason="non-asserted statement",
        )

    return IntentDecision(Intent.CLARIFY, topic=topic, reason="no facts")

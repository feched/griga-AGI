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
from griga.perception.models import ParseResult, Polarity, SpeechAct
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
    if owner_id is None:
        return edges
    return [
        edge
        for edge in edges
        if edge.owner_id is None or edge.owner_id == owner_id
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
            edge = None
            if subject is not None and obj is not None:
                edge = graph.find_edge(
                    subject.id, obj.id, statement.relation
                )

            if edge is not None:
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

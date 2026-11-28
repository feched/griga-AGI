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


def contradiction_edges(
    graph: KnowledgeGraph,
    subject: Node,
    asked_target_id: uuid.UUID | None,
    owner_id: uuid.UUID | None = None,
):
    """Сильные альтернативы для is_a: «трава → растение» при вопросе
    «трава — животное?» (DEBT-210)."""
    result = []
    for edge in graph.get_out_edges(subject.id):
        if edge.relation_type is not RelationType.IS_A:
            continue
        if edge.is_negated or edge.target_id == asked_target_id:
            continue
        if edge.weight < 0.5:
            continue
        if owner_id is not None and edge.owner_id not in (None, owner_id):
            continue
        result.append(edge)
    return result


def transitive_edges(
    graph: KnowledgeGraph,
    subject: Node,
    statement: Statement,
    owner_id: uuid.UUID | None = None,
):
    """Путь A -[глагол]-> B -[is_a]-> C (DEBT-213).

    v0.1: «Саша живёт в Москве» + «Москва — город» даёт ответ на
    «Саша живёт в городе?». Правило работает только для related_to с
    совпадающей меткой глагола и is_a.
    """
    if statement.relation is not RelationType.RELATED_TO:
        return []

    paths = []
    for first in graph.get_out_edges(subject.id):
        if first.relation_type is not RelationType.RELATED_TO:
            continue
        if first.is_negated or first.weight < 0.5:
            continue
        if owner_id is not None and first.owner_id not in (None, owner_id):
            continue
        if not label_matches(statement.label, first.metadata.get("label")):
            continue
        middle = graph.nodes.get(first.target_id)
        if middle is None:
            continue
        for second in graph.get_out_edges(middle.id):
            if second.relation_type is not RelationType.IS_A:
                continue
            if second.is_negated or second.weight < 0.5:
                continue
            if owner_id is not None and second.owner_id not in (None, owner_id):
                continue
            target = graph.nodes.get(second.target_id)
            if target is None:
                continue
            if target.name.casefold() != statement.object.lemma.casefold():
                continue
            paths.append((first, middle, second, target, subject))
    return paths


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

            if edge is not None and edge.is_negated:
                # Факт был отвергнут коррекцией — спокойно говорим «нет»
                # (DEBT-210).
                return IntentDecision(
                    Intent.ANSWER_DIRECTLY,
                    confidence=1.0,
                    topic=topic or subject,
                    reason="yes/no fact is negated",
                )

            if (
                subject is not None
                and obj is not None
                and statement.relation is RelationType.IS_A
            ):
                alternatives = contradiction_edges(
                    graph, subject, obj.id, owner_id
                )
                if alternatives and (
                    edge is None or edge.weight < 0.5
                ):
                    # «Трава — животное?», а в графе «трава → растение».
                    return IntentDecision(
                        Intent.ANSWER_DIRECTLY,
                        confidence=1.0,
                        topic=topic or subject,
                        reason="yes/no contradicts is_a",
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

            if subject is not None:
                paths = transitive_edges(
                    graph, subject, statement, owner_id
                )
                if paths:
                    # «Саша живёт в Москве» + «Москва — город».
                    return IntentDecision(
                        Intent.ANSWER_DIRECTLY,
                        confidence=max(
                            min(first.weight, second.weight)
                            for first, _, second, _, _ in paths
                        ),
                        topic=topic or subject,
                        reason="transitive fact",
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

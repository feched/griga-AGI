"""Генерация ответа: намерение → конструкция → мониторинг (ADR-004).

Гарантия Grounded Generation: слоты заполняются только узлами и рёбрами,
которые реально есть в графе. Если подходящей конструкции нет — намерение
меняется на «признать незнание», а не выдумывается факт.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from griga.config import Config, load_config
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node, NodeType
from griga.graph.relations import RelationType, label_matches
from griga.perception.models import (
    USER_LEMMA,
    USER_NAME_LABEL,
    ParseResult,
    Statement,
)
from griga.perception.morphology import (
    Morphology,
    case_for_preposition,
    normalize_word,
)
from griga.speech.constructions import (
    Construction,
    GraphPattern,
    SlotSpec,
    by_intent,
    load_constructions,
)
from griga.speech.intents import (
    Intent,
    IntentDecision,
    choose_intent,
    contradiction_edges,
    definition_edges,
    open_question_edges,
    question_statements,
    topic_node,
    transitive_edges,
    visible_edges,
)
from griga.thinking.spreader import WorkingMemory


_EMOTION_ADVERBS = {
    "радость": "радостно",
    "грусть": "грустно",
    "агрессия": "тяжело",
    "тревога": "тревожно",
    "обида": "обидно",
    "усталость": "тяжело",
    "благодарность": "приятно",
}

_FALLBACK_TEXT = "Я запутался, давай переформулируем."

# Личные местоимения для узла «пользователь» (DEBT-217).
_USER_PRONOUNS = {
    "nominative": "ты",
    "genitive": "тебя",
    "accusative": "тебя",
    "dative": "тебе",
    "instrumental": "тобой",
    "prepositional": "тебе",
}


@dataclass(frozen=True)
class TurnContext:
    last_response: str | None = None
    turn_index: int = 0


@dataclass(frozen=True)
class GeneratedResponse:
    text: str
    intent: Intent
    construction_id: str
    attempts: int = 1
    confidence: float = 1.0
    used_node_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class SlotValue:
    lemma: str
    node_type: NodeType = NodeType.CONCEPT
    node_id: uuid.UUID | None = None
    pos: str = "NOUN"
    is_user: bool = False
    proper: bool = False
    text: str | None = None


@dataclass(frozen=True)
class _Candidate:
    construction: Construction
    values: dict[str, SlotValue] = field(default_factory=dict)
    verb_lemma: str | None = None
    preposition: str | None = None
    emotion_adv: str | None = None
    confidence: float = 1.0

    @property
    def used_node_ids(self) -> tuple[uuid.UUID, ...]:
        ids = {
            value.node_id
            for value in self.values.values()
            if value.node_id is not None
        }
        return tuple(ids)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_word(text)).strip()


class Generator:
    """Собирает ответ из активных узлов и банка конструкций."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        config: Config | None = None,
        *,
        morph: Morphology | None = None,
        constructions: tuple[Construction, ...] | None = None,
    ) -> None:
        self.graph = graph
        self.config = config or load_config()
        self.morph = morph or Morphology()
        self.constructions = constructions or load_constructions()
        self.max_attempts = self.config.generation.max_attempts

    # --- публичный вход ------------------------------------------------

    def generate(
        self,
        result: ParseResult,
        memory: WorkingMemory,
        context: TurnContext | None = None,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> GeneratedResponse:
        context = context or TurnContext()
        decision = choose_intent(result, self.graph, memory, owner_id)
        candidates = self._candidates(
            result, memory, decision, context, owner_id
        )

        attempts = 0
        for candidate in candidates:
            text = self.render(candidate)
            if not text:
                continue
            attempts += 1
            if self._monitor(text, candidate, decision, context):
                return GeneratedResponse(
                    text=text,
                    intent=candidate.construction.intent,
                    construction_id=candidate.construction.id,
                    attempts=attempts,
                    confidence=candidate.confidence,
                    used_node_ids=candidate.used_node_ids,
                )
            if attempts >= self.max_attempts:
                break

        return GeneratedResponse(
            text=_FALLBACK_TEXT,
            intent=decision.intent,
            construction_id="fallback",
            attempts=max(1, attempts),
            confidence=0.0,
            used_node_ids=(decision.topic.id,) if decision.topic else (),
        )

    # --- выбор кандидатов ---------------------------------------------

    def _candidates(
        self,
        result: ParseResult,
        memory: WorkingMemory,
        decision: IntentDecision,
        context: TurnContext,
        owner_id: uuid.UUID | None,
    ) -> list[_Candidate]:
        if decision.intent is Intent.GREET:
            return self._greet_candidates(owner_id)

        if decision.intent is Intent.REFUSE:
            return self._simple_candidates(Intent.REFUSE)

        if decision.intent is Intent.EMPATHIZE:
            emotion = result.markers.emotion
            return self._simple_candidates(
                Intent.EMPATHIZE,
                emotion=emotion,
                emotion_adv=_EMOTION_ADVERBS.get(emotion or ""),
            )

        if decision.intent is Intent.ACKNOWLEDGE:
            return self._acknowledge_candidates(result, owner_id)

        if decision.intent is Intent.CLARIFY:
            values: dict[str, SlotValue] = {}
            if decision.topic is not None:
                values["X"] = self._slot_from_node(decision.topic)
            return self._simple_candidates(Intent.CLARIFY, values=values)

        if decision.intent is Intent.ADMIT_IGNORANCE:
            return self._ignorance_candidates(result, decision)

        if decision.intent in {
            Intent.ANSWER_DIRECTLY,
            Intent.ANSWER_WITH_HEDGE,
        }:
            return self._question_candidates(
                result, decision, memory, owner_id
            )

        return self._simple_candidates(Intent.CLARIFY)

    def _simple_candidates(
        self,
        intent: Intent,
        *,
        values: dict[str, SlotValue] | None = None,
        emotion: str | None = None,
        emotion_adv: str | None = None,
    ) -> list[_Candidate]:
        values = values or {}
        result: list[_Candidate] = []

        for construction in by_intent(self.constructions, intent):
            if construction.emotion and construction.emotion != emotion:
                continue
            if not construction.slot_names.issubset(values):
                continue
            result.append(
                _Candidate(
                    construction=construction,
                    values=values,
                    emotion_adv=emotion_adv,
                )
            )

        return sorted(
            result,
            key=lambda item: (
                bool(
                    item.construction.emotion
                    and item.construction.emotion == emotion
                ),
                item.construction.weight,
            ),
            reverse=True,
        )

    def _greet_candidates(
        self,
        owner_id: uuid.UUID | None,
    ) -> list[_Candidate]:
        """Приветствие по имени, если имя уже есть в графе (DEBT-207)."""
        values: dict[str, SlotValue] = {}
        name = self._user_name_node(owner_id)
        if name is not None:
            values["X"] = self._slot_from_node(name)
        return self._simple_candidates(Intent.GREET, values=values)

    def _user_name_node(
        self,
        owner_id: uuid.UUID | None,
    ) -> Node | None:
        user = self.graph.find_visible_node(
            USER_LEMMA, NodeType.CONCEPT, owner_id
        )
        if user is None:
            return None
        for edge in self.graph.get_out_edges(user.id):
            if edge.is_negated:
                continue
            if edge.metadata.get("label") != USER_NAME_LABEL:
                continue
            target = self.graph.nodes.get(edge.target_id)
            if target is not None:
                return target
        return None

    def _ignorance_candidates(
        self,
        result: ParseResult,
        decision: IntentDecision,
    ) -> list[_Candidate]:
        values: dict[str, SlotValue] = {}
        if decision.topic is not None:
            values["X"] = self._slot_from_node(decision.topic)

        candidates = self._simple_candidates(
            Intent.ADMIT_IGNORANCE, values=values
        )

        if decision.reason == "yes/no fact not found":
            order = ["unknown_yesno", "unknown_generic", "unknown_empty"]
        elif decision.topic is not None:
            order = ["unknown_topic", "unknown_generic", "unknown_empty"]
        else:
            order = ["unknown_generic", "unknown_empty", "unknown_yesno"]

        priority = {name: index for index, name in enumerate(order)}
        candidates.sort(
            key=lambda item: (
                priority.get(item.construction.id, 99),
                -item.construction.weight,
            )
        )
        return candidates

    def _acknowledge_candidates(
        self,
        result: ParseResult,
        owner_id: uuid.UUID | None,
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        facts = sorted(
            result.facts(), key=lambda item: item.confidence, reverse=True
        )

        if not facts:
            # Отрицание/«наверное» — честно подтверждаем, но в граф не пишем.
            for construction in by_intent(
                self.constructions, Intent.ACKNOWLEDGE
            ):
                if construction.graph_pattern.relation is not None:
                    continue
                if construction.slot_names:
                    continue
                candidates.append(
                    _Candidate(
                        construction=construction,
                        confidence=0.4,
                    )
                )
            candidates.sort(
                key=lambda item: (
                    item.construction.id == "ack_negation",
                    item.construction.weight,
                ),
                reverse=True,
            )
            return candidates

        for statement in facts:
            subject = self.graph.find_visible_node(
                statement.subject.lemma,
                statement.subject.node_type,
                owner_id,
            )
            obj = self.graph.find_visible_node(
                statement.object.lemma,
                statement.object.node_type,
                owner_id,
            )
            values = {
                "X": self._slot_from_statement(
                    statement, 0, subject
                ),
                "Y": self._slot_from_statement(
                    statement, 1, obj
                ),
            }
            verb, preposition = self._verb_parts(statement)

            for construction in by_intent(
                self.constructions, Intent.ACKNOWLEDGE
            ):
                if construction.label and not label_matches(
                    construction.label, statement.label
                ):
                    continue
                if construction.user_only and not values["X"].is_user:
                    continue
                pattern = construction.graph_pattern
                if pattern.relation is not None and (
                    pattern.relation is not statement.relation
                ):
                    continue
                if pattern.relation is not None and not pattern.is_forward:
                    continue
                if not self._vocabulary_matches(
                    construction, verb, preposition
                ):
                    continue
                if not construction.slot_names.issubset(values):
                    continue
                candidates.append(
                    _Candidate(
                        construction=construction,
                        values=values,
                        verb_lemma=verb,
                        preposition=preposition,
                        confidence=statement.confidence,
                    )
                )

        return sorted(
            candidates,
            key=lambda item: item.construction.weight,
            reverse=True,
        )

    def _question_candidates(
        self,
        result: ParseResult,
        decision: IntentDecision,
        memory: WorkingMemory,
        owner_id: uuid.UUID | None,
    ) -> list[_Candidate]:
        intents = [decision.intent]
        if decision.intent is Intent.ANSWER_DIRECTLY:
            intents.append(Intent.ANSWER_WITH_HEDGE)

        asked = question_statements(result)
        if asked:
            statement = asked[0]
            subject = self.graph.find_visible_node(
                statement.subject.lemma,
                statement.subject.node_type,
                owner_id,
            )
            obj = self.graph.find_visible_node(
                statement.object.lemma,
                statement.object.node_type,
                owner_id,
            )
            if subject is None:
                return []
            if obj is None:
                if not statement.is_open_question:
                    return []
                return self._open_question_candidates(
                    result, statement, subject, intents, owner_id
                )
            edge = self.graph.find_edge(
                subject.id, obj.id, statement.relation
            )
            if decision.reason == "yes/no contradicts is_a":
                return self._contradiction_candidates(
                    statement, subject, obj, intents, owner_id
                )
            if edge is not None and not edge.is_negated:
                return self._edge_candidates(
                    edge,
                    subject,
                    obj,
                    direction="forward",
                    intents=intents,
                    yes_no=True,
                )
            if edge is not None and edge.is_negated:
                return self._negative_candidates(
                    statement, subject, obj, intents
                )
            if decision.reason == "transitive fact":
                return self._transitive_candidates(
                    statement, subject, intents, owner_id
                )
            return []

        topic = decision.topic or topic_node(
            result, self.graph, memory, owner_id
        )
        if topic is None:
            return []

        candidates: list[_Candidate] = []
        # «Какая трава?» — все свойства сразу: «Трава — зелёная и мягкая»
        # (DEBT-208).
        if (
            not result.markers.definition
            and result.markers.question_word
            in {"какой", "какая", "какое", "какие", "чей"}
        ):
            candidates.extend(
                self._aggregate_property_candidates(topic, intents)
            )
        if result.markers.definition:
            # «Что такое X?» — только исходящие определения (DEBT-215).
            edges = definition_edges(self.graph, topic, owner_id)
        else:
            edges = visible_edges(self.graph, topic, owner_id)
        edges = sorted(
            edges,
            key=lambda item: item.weight,
            reverse=True,
        )
        for edge in edges[:8]:
            forward = edge.source_id == topic.id
            other_id = edge.target_id if forward else edge.source_id
            other = self.graph.nodes.get(other_id)
            if other is None:
                continue
            if forward:
                candidates.extend(
                    self._edge_candidates(
                        edge,
                        topic,
                        other,
                        direction="forward",
                        intents=intents,
                        yes_no=False,
                    )
                )
            else:
                candidates.extend(
                    self._edge_candidates(
                        edge,
                        topic,
                        other,
                        direction="reverse",
                        intents=intents,
                        yes_no=False,
                    )
                )

        # Сначала прямые ответы, затем оговорки; внутри — релевантность
        # типу вопроса («что такое» → is_a, «где» → глагольная связь).
        order = {intent: index for index, intent in enumerate(intents)}
        question_word = result.markers.question_word
        return sorted(
            candidates,
            key=lambda item: (
                order.get(item.construction.intent, 99),
                self._relation_priority(
                    item.construction.graph_pattern.relation,
                    question_word,
                ),
                -item.confidence,
                -item.construction.weight,
            ),
        )

    def _open_question_candidates(
        self,
        result: ParseResult,
        statement: Statement,
        subject: Node,
        intents: list[Intent],
        owner_id: uuid.UUID | None,
    ) -> list[_Candidate]:
        """«Что я люблю?» → рёбра субъекта, отобранные по глаголу вопроса."""
        edges = sorted(
            open_question_edges(self.graph, subject, statement, owner_id),
            key=lambda item: item.weight,
            reverse=True,
        )
        candidates: list[_Candidate] = []
        for edge in edges[:8]:
            other = self.graph.nodes.get(edge.target_id)
            if other is None:
                continue
            candidates.extend(
                self._edge_candidates(
                    edge,
                    subject,
                    other,
                    direction="forward",
                    intents=intents,
                    yes_no=False,
                )
            )

        order = {intent: index for index, intent in enumerate(intents)}
        question_word = result.markers.question_word
        return sorted(
            candidates,
            key=lambda item: (
                order.get(item.construction.intent, 99),
                self._relation_priority(
                    item.construction.graph_pattern.relation,
                    question_word,
                ),
                -item.confidence,
                -item.construction.weight,
            ),
        )

    @staticmethod
    def _relation_priority(
        relation: RelationType | None,
        question_word: str | None,
    ) -> int:
        if question_word in {"где", "куда", "откуда"}:
            order = [
                RelationType.RELATED_TO,
                RelationType.PART_OF,
                RelationType.IS_A,
                RelationType.HAS_PROPERTY,
            ]
        elif question_word in {"какой", "какая", "какие", "чей"}:
            order = [
                RelationType.HAS_PROPERTY,
                RelationType.IS_A,
                RelationType.PART_OF,
                RelationType.RELATED_TO,
            ]
        else:
            order = [
                RelationType.IS_A,
                RelationType.HAS_PROPERTY,
                RelationType.PART_OF,
                RelationType.RELATED_TO,
            ]
        if relation not in order:
            return 99
        return order.index(relation)

    def _edge_candidates(
        self,
        edge,
        topic: Node,
        other: Node,
        *,
        direction: str,
        intents: list[Intent],
        yes_no: bool | None = None,
    ) -> list[_Candidate]:
        if direction == "forward":
            subject, obj = topic, other
        else:
            subject, obj = other, topic

        values = {
            "X": self._slot_from_node(subject),
            "Y": self._slot_from_node(obj),
        }
        verb: str | None = None
        preposition: str | None = None
        if edge.relation_type is RelationType.RELATED_TO and direction == "forward":
            verb, preposition = self._verb_parts_from_label(edge.metadata.get("label"))

        candidates: list[_Candidate] = []
        for intent in intents:
            for construction in by_intent(self.constructions, intent):
                pattern = construction.graph_pattern

                if construction.id.startswith("no_"):
                    # Отрицательные ответы собирает _negative_candidates.
                    continue
                if pattern.relation is None:
                    continue
                if pattern.relation is not edge.relation_type:
                    continue
                if pattern.direction != direction:
                    continue
                if yes_no is not None and construction.yes_no != yes_no:
                    continue
                if construction.label and not label_matches(
                    construction.label, edge.metadata.get("label")
                ):
                    continue
                if construction.user_only and not values["X"].is_user:
                    continue
                if not self._vocabulary_matches(
                    construction, verb, preposition
                ):
                    continue
                if not construction.slot_names.issubset(values):
                    continue

                candidates.append(
                    _Candidate(
                        construction=construction,
                        values=values,
                        verb_lemma=verb,
                        preposition=preposition,
                        confidence=min(edge.weight, 1.0),
                    )
                )
        return candidates

    # --- ответы на yes/no и вывод --------------------------------------

    def _property_adjective(self, node: Node, topic: Node) -> str:
        return self.morph.inflect_adjective(
            node.name,
            case="nominative",
            gender=self.morph.gender(topic.name),
        )

    def _aggregate_property_candidates(
        self,
        topic: Node,
        intents: list[Intent],
    ) -> list[_Candidate]:
        """Все свойства сразу: «Трава — зелёная и мягкая» (DEBT-208)."""
        if Intent.ANSWER_DIRECTLY not in intents:
            return []

        edges = [
            edge
            for edge in self.graph.get_out_edges(topic.id)
            if edge.relation_type is RelationType.HAS_PROPERTY
            and not edge.is_negated
            and edge.weight >= 0.5
        ]
        if len(edges) < 2:
            return []

        edges.sort(key=lambda item: item.weight, reverse=True)
        adjectives = [
            self._property_adjective(node, topic)
            for edge in edges
            if (node := self.graph.nodes.get(edge.target_id)) is not None
        ]
        if len(adjectives) < 2:
            return []

        primary = " и ".join(adjectives)
        secondary = " и ".join(reversed(adjectives))
        variants = [primary]
        if secondary != primary:
            variants.append(secondary)

        candidates: list[_Candidate] = []
        for variant in variants:
            for construction in by_intent(
                self.constructions, Intent.ANSWER_DIRECTLY
            ):
                if construction.id != "answer_properties":
                    continue
                values = {
                    "X": self._slot_from_node(topic),
                    "Y": SlotValue(
                        lemma=variant,
                        node_type=NodeType.PROPERTY,
                        text=variant,
                    ),
                }
                candidates.append(
                    _Candidate(
                        construction=construction,
                        values=values,
                        confidence=min(
                            edge.weight for edge in edges[: len(adjectives)]
                        ),
                    )
                )
        return candidates

    def _negative_candidates(
        self,
        statement: Statement,
        subject: Node,
        obj: Node,
        intents: list[Intent],
    ) -> list[_Candidate]:
        """«Нет, трава не синяя» после коррекции (DEBT-210)."""
        values = {
            "X": self._slot_from_node(subject),
            "Y": self._slot_from_node(obj),
        }
        by_relation = {
            RelationType.HAS_PROPERTY: "no_property",
            RelationType.IS_A: "no_is_a",
        }
        wanted_id = by_relation.get(statement.relation, "no_generic")

        candidates: list[_Candidate] = []
        for intent in intents:
            for construction in by_intent(self.constructions, intent):
                if construction.id != wanted_id:
                    continue
                if not construction.slot_names.issubset(values):
                    continue
                candidates.append(
                    _Candidate(
                        construction=construction,
                        values=values,
                        confidence=1.0,
                    )
                )
        return candidates

    def _contradiction_candidates(
        self,
        statement: Statement,
        subject: Node,
        obj: Node | None,
        intents: list[Intent],
        owner_id: uuid.UUID | None,
    ) -> list[_Candidate]:
        """«Трава — животное?» → «Нет, трава — это растение» (DEBT-210)."""
        alternatives = contradiction_edges(
            self.graph, subject, obj.id if obj is not None else None, owner_id
        )
        if not alternatives:
            return []
        best = max(alternatives, key=lambda item: item.weight)
        true_node = self.graph.nodes.get(best.target_id)
        if true_node is None:
            return []

        values = {
            "X": self._slot_from_node(subject),
            "Y": (
                self._slot_from_node(obj)
                if obj is not None
                else SlotValue(
                    lemma=statement.object.lemma,
                    node_type=statement.object.node_type,
                    pos=statement.object.pos,
                )
            ),
            "Z": self._slot_from_node(true_node),
        }

        candidates: list[_Candidate] = []
        for intent in intents:
            for construction in by_intent(self.constructions, intent):
                if construction.id != "no_is_a_conflict":
                    continue
                if not construction.slot_names.issubset(values):
                    continue
                candidates.append(
                    _Candidate(
                        construction=construction,
                        values=values,
                        confidence=best.weight,
                    )
                )
        return candidates

    def _transitive_candidates(
        self,
        statement: Statement,
        subject: Node,
        intents: list[Intent],
        owner_id: uuid.UUID | None,
    ) -> list[_Candidate]:
        """«Саша живёт в городе?» → «Да, Саша живёт в Москве (город)»."""
        paths = transitive_edges(
            self.graph, subject, statement, owner_id
        )
        candidates: list[_Candidate] = []
        for first, middle, second, target, _ in paths:
            verb, preposition = self._verb_parts_from_label(
                first.metadata.get("label")
            )
            values = {
                "X": self._slot_from_node(subject),
                "Y": self._slot_from_node(middle),
                "Z": self._slot_from_node(target),
            }
            for intent in intents:
                for construction in by_intent(self.constructions, intent):
                    if construction.id != "yes_transitive":
                        continue
                    if not self._vocabulary_matches(
                        construction, verb, preposition
                    ):
                        continue
                    if not construction.slot_names.issubset(values):
                        continue
                    candidates.append(
                        _Candidate(
                            construction=construction,
                            values=values,
                            verb_lemma=verb,
                            preposition=preposition,
                            confidence=min(first.weight, second.weight),
                        )
                    )
        return candidates

    # --- служебные преобразования -------------------------------------

    def _slot_from_node(self, node: Node) -> SlotValue:
        return SlotValue(
            lemma=node.name,
            node_type=node.node_type,
            node_id=node.id,
            pos=str(node.metadata.get("pos") or "NOUN"),
            is_user=node.name.casefold() == USER_LEMMA,
            proper=self._is_proper_name(node),
        )

    def _is_proper_name(self, node: Node) -> bool:
        """Имя собственное: PROPN, ребро «имя» или pymorphy2 (DEBT-218)."""
        if str(node.metadata.get("pos") or "") == "PROPN":
            return True
        if node.name.casefold() == USER_LEMMA:
            return False
        if self.morph.is_proper_word(node.name):
            return True
        return any(
            edge.metadata.get("label") == USER_NAME_LABEL
            and not edge.is_negated
            for edge in self.graph.get_in_edges(node.id)
        )

    def _slot_from_statement(
        self,
        statement: Statement,
        index: int,
        node: Node | None,
    ) -> SlotValue:
        mention = statement.subject if index == 0 else statement.object
        is_user = mention.lemma.casefold() == USER_LEMMA
        if node is not None:
            proper = self._is_proper_name(node)
        else:
            proper = str(mention.pos) == "PROPN" or (
                index == 1 and statement.label == USER_NAME_LABEL
            )
        return SlotValue(
            lemma=node.name if node is not None else mention.lemma,
            node_type=mention.node_type,
            node_id=node.id if node is not None else None,
            pos=mention.pos,
            is_user=is_user,
            proper=proper,
        )

    def _verb_parts(
        self, statement: Statement
    ) -> tuple[str | None, str | None]:
        if statement.relation is not RelationType.RELATED_TO:
            return None, None
        return self._verb_parts_from_label(statement.label)

    def _verb_parts_from_label(
        self, label: str | None
    ) -> tuple[str | None, str | None]:
        if not label:
            return None, None
        if "_" in label:
            verb, preposition = label.split("_", 1)
            return verb, preposition
        if self.morph.is_verb(label):
            return label, None
        return None, None

    @staticmethod
    def _vocabulary_matches(
        construction: Construction,
        verb: str | None,
        preposition: str | None,
    ) -> bool:
        template = construction.template
        needs_verb = "{VERB_PRES}" in template
        needs_prep = "{PREP}" in template

        if needs_verb and verb is None:
            return False
        if needs_prep and not preposition:
            return False
        if needs_verb and not needs_prep and preposition:
            # «трава расти газон» вместо «расти на газоне».
            return False
        return True

    # --- рендеринг -----------------------------------------------------

    def render(self, candidate: _Candidate) -> str:
        construction = candidate.construction
        text = construction.template

        for name, value in candidate.values.items():
            placeholder = f"{{{name}}}"
            if placeholder not in text:
                continue
            spec: SlotSpec = construction.slots[name]
            text = text.replace(
                placeholder, self._render_slot(value, spec, candidate)
            )

        if "{VERB_PRES}" in text:
            if not candidate.verb_lemma:
                return ""
            subject = candidate.values.get("X")
            person = (
                "2per"
                if subject is not None and subject.is_user
                else "3per"
            )
            text = text.replace(
                "{VERB_PRES}",
                self.morph.conjugate_present(
                    candidate.verb_lemma, person=person
                ),
            )

        if "{PREP}" in text:
            text = text.replace("{PREP}", candidate.preposition or "")

        if "{EMOTION_ADV}" in text:
            text = text.replace(
                "{EMOTION_ADV}", candidate.emotion_adv or "непросто"
            )

        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\s+([.,!?;:])", r"\1", text)
        if text:
            text = text[0].upper() + text[1:]
        return text

    def _render_slot(
        self,
        value: SlotValue,
        spec: SlotSpec,
        candidate: _Candidate,
    ) -> str:
        case = spec.case
        if case == "auto":
            case = case_for_preposition(candidate.preposition)

        if value.text is not None:
            return value.text

        if value.is_user and value.node_type is NodeType.CONCEPT:
            return _USER_PRONOUNS.get(case, "ты")

        if value.node_type is NodeType.PROPERTY or spec.pos == "adjective":
            gender = None
            if spec.agree_with:
                agreement = candidate.values.get(spec.agree_with)
                if agreement is not None:
                    gender = self.morph.gender(agreement.lemma)
            return self.morph.inflect_adjective(
                value.lemma,
                case="nominative" if case == "auto" else case,
                gender=gender,
            )

        text = self._inflect_phrase(value.lemma, case)
        if value.proper:
            text = text[:1].upper() + text[1:]
        return text

    def _inflect_phrase(self, lemma: str, case: str) -> str:
        """Склоняет слово или составной термин «чёрная дыра» (DEBT-211)."""
        words = lemma.split()
        if len(words) <= 1:
            return self.morph.inflect_noun(lemma, case)

        head = words[-1]
        gender = self.morph.gender(head)
        inflected = [
            self.morph.inflect_adjective(
                word, case=case, gender=gender
            )
            for word in words[:-1]
        ]
        inflected.append(self.morph.inflect_noun(head, case))
        return " ".join(inflected)

    # --- мониторинг ----------------------------------------------------

    def _monitor(
        self,
        text: str,
        candidate: _Candidate,
        decision: IntentDecision,
        context: TurnContext,
    ) -> bool:
        if not text or len(text) > 300:
            return False

        if context.last_response and _normalize_text(
            text
        ) == _normalize_text(context.last_response):
            return False

        if (
            candidate.construction.intent is Intent.ANSWER_DIRECTLY
            and candidate.confidence < 0.5
        ):
            return False

        # Адекватность: ответ на вопрос обязан содержать тему вопроса.
        if decision.intent in {
            Intent.ANSWER_DIRECTLY,
            Intent.ANSWER_WITH_HEDGE,
        }:
            if decision.topic is None:
                return False
            if decision.topic.id not in candidate.used_node_ids:
                return False

        return True

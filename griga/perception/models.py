"""Структуры выхода Perception (ADR-002).

Парсер возвращает три потока:

- ``nodes``      — упоминания концептов и свойств;
- ``statements`` — что записать в граф (рёбра);
- ``markers``    — тип реплики: вопрос, приветствие, эмоция, атрибуция.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from griga.graph.node import NodeType
from griga.graph.relations import RelationType


# Узел, которым обозначается сам говорящий. «Я люблю кофе» пишется как
# ``пользователь -[любить]-> кофе`` (DEBT-207).
USER_LEMMA = "пользователь"
USER_NAME_LABEL = "имя"


class SpeechAct(str, Enum):
    """Тип реплики пользователя (ADR-002, маркеры)."""

    STATEMENT = "statement"
    QUESTION = "question"
    GREETING = "greeting"
    EMOTION = "emotion"
    COMMAND = "command"
    UNKNOWN = "unknown"


class Polarity(str, Enum):
    """Модальность утверждения (ADR-002).

    В долговременный граф попадают только ``ASSERTED`` и не-вопросы.
    """

    ASSERTED = "asserted"
    NEGATED = "negated"
    UNSURE = "unsure"


@dataclass(frozen=True)
class Mention:
    """Упоминание узла в тексте.

    ``lemma`` — каноническая форма (pymorphy2), ``form`` — как в тексте.
    ``node_type`` отделяет концепт (существительное) от свойства
    (прилагательное).
    """

    lemma: str
    form: str
    pos: str
    node_type: NodeType = NodeType.CONCEPT
    features: dict[str, str] = field(default_factory=dict)

    @property
    def is_concept(self) -> bool:
        return self.node_type is NodeType.CONCEPT

    @property
    def is_property(self) -> bool:
        return self.node_type is NodeType.PROPERTY


@dataclass(frozen=True)
class Statement:
    """Утверждение «субъект — отношение ——> объект»."""

    subject: Mention
    relation: RelationType
    object: Mention
    label: str
    polarity: Polarity = Polarity.ASSERTED
    confidence: float = 0.55
    is_question: bool = False
    source_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    correction: bool = False

    @property
    def is_fact(self) -> bool:
        """Можно ли писать в долговременный граф (ADR-002)."""
        return self.polarity is Polarity.ASSERTED and not self.is_question

    @property
    def is_open_question(self) -> bool:
        """Вопрос «что/где/как …?», где искомый объект ещё не назван."""
        return (
            self.is_question
            and self.object.features.get("open_question") == "true"
        )

    @property
    def weight(self) -> float:
        return self.confidence

    def mentions(self) -> tuple[Mention, Mention]:
        return (self.subject, self.object)


@dataclass(frozen=True)
class Markers:
    """Диалоговые маркеры реплики (ADR-002)."""

    speech_act: SpeechAct = SpeechAct.STATEMENT
    is_question: bool = False
    has_negation: bool = False
    emotion: str | None = None
    attribution: str | None = None
    question_word: str | None = None
    greeting: str | None = None
    modality: str | None = None
    correction: bool = False

    @property
    def is_greeting(self) -> bool:
        return self.speech_act is SpeechAct.GREETING

    @property
    def is_emotional(self) -> bool:
        return self.speech_act is SpeechAct.EMOTION


@dataclass(frozen=True)
class ParseResult:
    """Полный результат разбора одной реплики."""

    text: str
    nodes: tuple[Mention, ...] = ()
    statements: tuple[Statement, ...] = ()
    markers: Markers = Markers()
    sentences: tuple[str, ...] = ()

    # --- удобные срезы ------------------------------------------------

    def concepts(self) -> tuple[Mention, ...]:
        return tuple(item for item in self.nodes if item.is_concept)

    def properties(self) -> tuple[Mention, ...]:
        return tuple(item for item in self.nodes if item.is_property)

    def node_names(self) -> list[str]:
        return [item.lemma for item in self.nodes]

    def concept_names(self) -> list[str]:
        return [item.lemma for item in self.concepts()]

    def facts(self) -> tuple[Statement, ...]:
        return tuple(item for item in self.statements if item.is_fact)

    def find_statement(
        self,
        subject: str,
        relation: RelationType | str,
        obj: str,
    ) -> Statement | None:
        if not isinstance(relation, RelationType):
            relation = RelationType(relation)
        for statement in self.statements:
            if (
                statement.subject.lemma.casefold() == subject.casefold()
                and statement.relation is relation
                and statement.object.lemma.casefold() == obj.casefold()
            ):
                return statement
        return None

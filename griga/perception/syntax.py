"""Синтаксис через UDPipe (ADR-002).

Модель русская, SynTagRus. Грузится один раз на процесс. Если модель
или библиотека недоступна, ``DependencyParser.parse`` возвращает ``None``,
и PerceptionParser переходит на эвристический fallback по pymorphy2.

UDPipe даёт структуру (подлежащее/дополнение/обстоятельство), тип связи
выводит PerceptionParser из структуры, а не из списка слов.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


_OBJECT_DEPRELS = frozenset({"obj", "obl", "nmod", "iobj"})
_SUBJECT_DEPRELS = frozenset({"nsubj", "nsubj:pass"})

_model_lock = threading.Lock()
_models: dict[str, object] = {}
_pipelines: dict[str, object] = {}


@dataclass
class SyntaxToken:
    """Один токен CoNLL-U."""

    id: int
    form: str
    lemma: str
    upos: str
    xpos: str
    feats: dict[str, str]
    head: int
    deprel: str
    children: list["SyntaxToken"] = field(default_factory=list)

    @property
    def is_noun(self) -> bool:
        return self.upos in {"NOUN", "PROPN"}

    @property
    def is_proper_noun(self) -> bool:
        return self.upos == "PROPN"

    @property
    def is_adjective(self) -> bool:
        return self.upos in {"ADJ", "ADJS"}

    @property
    def is_verb(self) -> bool:
        return self.upos in {"VERB", "AUX"}

    @property
    def is_pronoun(self) -> bool:
        return self.upos == "PRON"

    @property
    def is_punctuation(self) -> bool:
        return self.upos == "PUNCT"

    @property
    def negated(self) -> bool:
        """Есть ли зависимая частица «не» (UDPipe: PART/advmod)."""
        for child in self.children:
            if child.form.lower() in {"не", "нет", "ни"}:
                return True
        return False

    @property
    def preposition(self) -> str | None:
        for child in self.children:
            if child.deprel == "case":
                return child.form.lower()
        return None

    @property
    def has_preposition(self) -> bool:
        return self.preposition is not None

    @property
    def case(self) -> str | None:
        return self.feats.get("Case")


class SyntaxTree:
    """Дерево зависимостей одного предложения."""

    def __init__(self, tokens: list[SyntaxToken]) -> None:
        self.tokens = tokens
        self.root: SyntaxToken | None = None
        self._by_id = {token.id: token for token in tokens}
        for token in tokens:
            if token.head == 0:
                self.root = token
            else:
                parent = self._by_id.get(token.head)
                if parent is not None:
                    parent.children.append(token)

    def token(self, token_id: int) -> SyntaxToken | None:
        return self._by_id.get(token_id)

    @property
    def verbs(self) -> list[SyntaxToken]:
        return [token for token in self.tokens if token.is_verb]

    @property
    def nouns(self) -> list[SyntaxToken]:
        return [token for token in self.tokens if token.is_noun]

    @property
    def adjectives(self) -> list[SyntaxToken]:
        return [token for token in self.tokens if token.is_adjective]

    def subject_of(self, verb: SyntaxToken) -> SyntaxToken | None:
        for child in verb.children:
            if child.deprel in _SUBJECT_DEPRELS:
                return child
        return None

    def object_of(self, verb: SyntaxToken) -> SyntaxToken | None:
        """Прямой объект без предлога (UDPipe нестабильно даёт obj/obl)."""
        candidates = [
            child
            for child in verb.children
            if child.deprel in _OBJECT_DEPRELS
            and child.is_noun
            and not child.has_preposition
        ]
        if not candidates:
            return None
        for child in candidates:
            if child.deprel == "obj":
                return child
        return candidates[0]

    def objects_of(self, verb: SyntaxToken) -> list[SyntaxToken]:
        """Прямые объекты, включая однородные через conj."""
        result: list[SyntaxToken] = []
        for child in verb.children:
            if (
                child.deprel in _OBJECT_DEPRELS
                and child.is_noun
                and not child.has_preposition
            ):
                result.append(child)
                for nested in child.children:
                    if nested.deprel == "conj" and nested.is_noun:
                        result.append(nested)
        return result

    def prepositional_objects_of(self, verb: SyntaxToken) -> list[SyntaxToken]:
        """Объекты с предлогом: «растёт НА газоне», «состоит ИЗ кирпича»."""
        result: list[SyntaxToken] = []
        for child in verb.children:
            if (
                child.deprel in _OBJECT_DEPRELS
                and child.is_noun
                and child.has_preposition
            ):
                result.append(child)
        return result

    def adjectives_of(self, noun: SyntaxToken) -> list[SyntaxToken]:
        return [
            child
            for child in noun.children
            if child.is_adjective or child.deprel == "amod"
        ]


def parse_conllu(conllu: str) -> SyntaxTree | None:
    tokens: list[SyntaxToken] = []
    for raw_line in conllu.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 8:
            continue
        try:
            token_id = int(fields[0])
        except ValueError:
            # Многословные токены (1-2) в v0.1 пропускаем.
            continue

        feats: dict[str, str] = {}
        for pair in fields[5].split("|"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                feats[key] = value

        head = int(fields[6]) if fields[6].isdigit() else 0
        tokens.append(
            SyntaxToken(
                id=token_id,
                form=fields[1],
                lemma=fields[2],
                upos=fields[3],
                xpos=fields[4],
                feats=feats,
                head=head,
                deprel=fields[7],
            )
        )

    if not tokens:
        return None
    return SyntaxTree(tokens)


class DependencyParser:
    """Обёртка над ufal.udpipe. Модель кэшируется на процесс."""

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path

    def available(self) -> bool:
        return self._ensure_loaded() is not None

    def parse(self, text: str) -> SyntaxTree | None:
        if not text or not text.strip():
            return None
        pipeline = self._ensure_loaded()
        if pipeline is None:
            return None
        try:
            conllu = pipeline.process(text)
        except Exception:
            return None
        return parse_conllu(conllu)

    def _ensure_loaded(self):
        pipeline = _pipelines.get(self.model_path)
        if pipeline is not None:
            return pipeline

        with _model_lock:
            pipeline = _pipelines.get(self.model_path)
            if pipeline is not None:
                return pipeline

            try:
                from ufal.udpipe import Model, Pipeline
            except Exception:
                return None

            try:
                model = Model.load(str(self.model_path))
            except Exception:
                return None
            if model is None:
                return None

            try:
                pipeline = Pipeline(
                    model,
                    "tokenize",
                    Pipeline.DEFAULT,
                    Pipeline.DEFAULT,
                    "conllu",
                )
            except Exception:
                return None

            _models[self.model_path] = model
            _pipelines[self.model_path] = pipeline
            return pipeline

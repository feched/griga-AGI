"""Морфологический слой Perception: pymorphy2, офлайн (ADR-002).

Используется для лемматизации, части речи и морфологических признаков.
Синтаксис берётся из UDPipe (``griga/perception/syntax.py``), но леммы
pymorphy2 точнее для русских глаголов (UDPipe иногда даёт «раствать»
вместо «расти»).
"""

from __future__ import annotations

from typing import Any

import pymorphy2


_NOUN_POS = frozenset({"NOUN"})
_PROPERTY_POS = frozenset({"ADJF", "ADJS", "COMP", "PRTF", "PRTS"})
_VERB_POS = frozenset({"VERB", "INFN", "GRND"})
_PRONOUN_POS = frozenset({"NPRO"})
_FUNCTION_POS = frozenset(
    {"PREP", "CONJ", "PRCL", "INTJ", "NPRO", "NUMR", "PRED", "NPRO"}
)


def normalize_word(word: str) -> str:
    """Нижний регистр, ё → е, обрезка. Единая форма для ключей графа."""
    return word.strip().lower().replace("ё", "е")


class Morphology:
    """Тонкая обёртка над pymorphy2 с кэшем разборов."""

    def __init__(self) -> None:
        self._morph = pymorphy2.MorphAnalyzer()
        self._cache: dict[str, Any] = {}

    def parse(self, word: str):
        key = normalize_word(word)
        cached = self._cache.get(key)
        if cached is None:
            cached = self._morph.parse(key)[0]
            self._cache[key] = cached
        return cached

    def normal_form(self, word: str) -> str:
        return normalize_word(self.parse(word).normal_form)

    def pos(self, word: str) -> str | None:
        return self.parse(word).tag.POS

    def tag(self, word: str) -> Any:
        return self.parse(word).tag

    def feature(self, word: str, name: str) -> str | None:
        return getattr(self.tag(word), name, None)

    def is_noun(self, word: str) -> bool:
        return self.pos(word) in _NOUN_POS

    def is_property(self, word: str) -> bool:
        return self.pos(word) in _PROPERTY_POS

    def is_verb(self, word: str) -> bool:
        return self.pos(word) in _VERB_POS

    def is_pronoun(self, word: str) -> bool:
        return self.pos(word) in _PRONOUN_POS

    def is_preposition(self, word: str) -> bool:
        return self.pos(word) == "PREP"

    def is_function(self, word: str) -> bool:
        return self.pos(word) in _FUNCTION_POS

    def is_imperative(self, word: str) -> bool:
        tag = self.tag(word)
        return getattr(tag, "mood", None) == "impr" and self.pos(word) in {
            "VERB",
            "INFN",
        }

    def case(self, word: str) -> str | None:
        return self.feature(word, "case")

    def number(self, word: str) -> str | None:
        return self.feature(word, "number")

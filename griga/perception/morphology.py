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
# Граммемы имён собственных в pymorphy2 (DEBT-218). «Саша» → Name,
# «Москва» → Geox. Обычные существительные этих граммем не имеют.
_PROPER_GRAMMEMES = frozenset({"Name", "Surn", "Patr", "Orgn", "Geox", "Trad"})
_FUNCTION_POS = frozenset(
    {"PREP", "CONJ", "PRCL", "INTJ", "NPRO", "NUMR", "PRED", "NPRO"}
)

_CASE_GRAMMEMES = {
    "nominative": "nomn",
    "genitive": "gent",
    "dative": "datv",
    "accusative": "accs",
    "instrumental": "ablt",
    "prepositional": "loct",
}
_NUMBER_GRAMMEMES = {"singular": "sing", "plural": "plur"}
_GENDER_GRAMMEMES = {
    "masculine": "masc",
    "feminine": "femn",
    "neuter": "neut",
    # pymorphy-значения тоже принимаем: Morphology.gender() возвращает их.
    "masc": "masc",
    "femn": "femn",
    "neut": "neut",
}

# Предлог → падеж, которого он требует. Нужен для глагольных рёбер
# «расти_на» → «на газоне», «состоять_из» → «из кирпича».
_PREPOSITION_CASE = {
    "на": "prepositional",
    "в": "prepositional",
    "во": "prepositional",
    "о": "prepositional",
    "об": "prepositional",
    "при": "prepositional",
    "из": "genitive",
    "от": "genitive",
    "у": "genitive",
    "без": "genitive",
    "для": "genitive",
    "до": "genitive",
    "с": "instrumental",
    "со": "instrumental",
    "над": "instrumental",
    "под": "instrumental",
    "за": "accusative",
    "про": "accusative",
    "через": "accusative",
    "к": "dative",
    "ко": "dative",
    "по": "dative",
}


def case_for_preposition(preposition: str | None) -> str:
    if not preposition:
        return "accusative"
    return _PREPOSITION_CASE.get(normalize_word(preposition), "accusative")


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

    def is_proper_word(self, word: str) -> bool:
        """Имя собственное по pymorphy2, без опоры на UDPipe.

        Нужно для капитализации имён, которые UDPipe пометил как NOUN
        (DEBT-218). Составные термины («черная дыра») сюда не относятся.
        """
        if " " in word.strip():
            return False
        grammemes = set(self.tag(word).grammemes)
        return bool(grammemes & _PROPER_GRAMMEMES)

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

    def gender(self, word: str) -> str | None:
        return self.feature(word, "gender")

    def inflect_noun(
        self,
        word: str,
        case: str = "nominative",
        number: str = "singular",
    ) -> str:
        """Склоняет существительное; при неудаче возвращает исходную лемму."""
        parse = self.parse(word)
        grammemes = {"NOUN"}
        if case in _CASE_GRAMMEMES:
            grammemes.add(_CASE_GRAMMEMES[case])
        if number in _NUMBER_GRAMMEMES:
            grammemes.add(_NUMBER_GRAMMEMES[number])
        result = parse.inflect(grammemes)
        return result.word if result else normalize_word(word)

    def inflect_adjective(
        self,
        word: str,
        case: str = "nominative",
        gender: str | None = None,
        number: str = "singular",
    ) -> str:
        """Склоняет прилагательное и согласует его по роду."""
        parse = self.parse(word)
        grammemes = {"ADJF"}
        if case in _CASE_GRAMMEMES:
            grammemes.add(_CASE_GRAMMEMES[case])
        if number in _NUMBER_GRAMMEMES:
            grammemes.add(_NUMBER_GRAMMEMES[number])
        if gender in _GENDER_GRAMMEMES:
            grammemes.add(_GENDER_GRAMMEMES[gender])
        result = parse.inflect(grammemes)
        return result.word if result else normalize_word(word)

    def conjugate_present(
        self,
        verb: str,
        person: str = "3per",
        number: str = "singular",
    ) -> str:
        """«расти» → «растёт», «любить» → «любит» (настоящее время)."""
        parse = self.parse(verb)
        grammemes = {"VERB", person}
        if number in _NUMBER_GRAMMEMES:
            grammemes.add(_NUMBER_GRAMMEMES[number])
        result = parse.inflect(grammemes)
        return result.word if result else normalize_word(verb)


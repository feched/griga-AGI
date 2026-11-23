"""Базовые типы связей (ADR-001).

В коде и БД используем стабильные английские имена, а ``label_ru`` даёт
каноническую русскую метку для документации и UI.
"""

from __future__ import annotations

from enum import Enum


class RelationType(str, Enum):
    IS_A = "is_a"
    PART_OF = "part_of"
    HAS_PROPERTY = "has_property"
    RELATED_TO = "related_to"

    @property
    def label_ru(self) -> str:
        return _LABELS_RU[self]


_LABELS_RU: dict[RelationType, str] = {
    RelationType.IS_A: "это",
    RelationType.PART_OF: "часть",
    RelationType.HAS_PROPERTY: "свойство",
    RelationType.RELATED_TO: "связано_с",
}

BASE_RELATION_TYPES = frozenset(RelationType)

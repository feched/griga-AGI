"""Классы действий для safety shell (ADR-010).

v0.1 не выполняет опасных действий: shell нужен как явная точка, через
которую пройдут будущие интерфейсы (Telegram/VK/web) и инструменты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ActionClass(str, Enum):
    """Насколько действие безопасно."""

    # Чтение графа, генерация ответа, расчёт активации.
    SAFE = "safe"
    # Запись факта в граф, обучение, забывание — разрешено, но аудируется.
    GUARDED = "guarded"
    # Действие можно выполнить только после подтверждения создателя.
    APPROVAL = "approval"
    # Действие запрещено в v0.1 (ADR-015).
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class Action:
    """Одно действие, которое кто-то просит выполнить."""

    name: str
    action_class: ActionClass
    payload: Mapping[str, Any] = field(default_factory=dict)
    actor: str = "griga"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Action.name must be non-empty")
        if not isinstance(self.action_class, ActionClass):
            object.__setattr__(
                self, "action_class", ActionClass(self.action_class)
            )


# Готовые классы действий для v0.1 и ближайшего будущего.
SAFE = ActionClass.SAFE
GUARDED = ActionClass.GUARDED
APPROVAL = ActionClass.APPROVAL
FORBIDDEN = ActionClass.FORBIDDEN

READ_GRAPH = ActionClass.SAFE
GENERATE_REPLY = ActionClass.SAFE
WRITE_FACT = ActionClass.GUARDED
UPDATE_WEIGHT = ActionClass.GUARDED
DELETE_FACT = ActionClass.APPROVAL
SEND_MESSAGE = ActionClass.APPROVAL
RUN_CODE = ActionClass.FORBIDDEN
WEB_SEARCH = ActionClass.FORBIDDEN
WRITE_FILE = ActionClass.FORBIDDEN
SELF_MODIFY = ActionClass.FORBIDDEN

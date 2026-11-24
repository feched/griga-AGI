"""Safety shell v0.1: approval-gate, пороги аномалий, аудит (ADR-010).

В v0.1 опасных действий нет, поэтому shell — это политика и журнал:

- ``SAFE`` и ``GUARDED`` действия разрешены (запись факта — GUARDED);
- ``APPROVAL`` требует подтверждения создателя, которого в CLI пока нет,
  поэтому по умолчанию запрещено;
- ``FORBIDDEN`` (код, веб, файлы, самоизменение) запрещено всегда;
- аномалии волны (слишком много новых рёбер/узлов/конфликтов за ход)
  фиксируются в audit-log.

Принцип ARCHITECTURE §7: safety, который агент может изменить — не safety.
Поэтому shell не читает граф и не зависит от Perception/Speech.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from griga.config import SafetyConfig
from griga.shell.actions import Action, ActionClass


@dataclass(frozen=True)
class SafetyVerdict:
    allowed: bool
    action: Action
    reason: str

    @property
    def action_class(self) -> ActionClass:
        return self.action.action_class

    @property
    def label(self) -> str:
        if self.allowed:
            return "allow"
        return "deny"


@dataclass(frozen=True)
class Anomaly:
    kind: str
    count: int
    limit: int
    detail: str = ""

    @property
    def reason(self) -> str:
        return f"{self.kind}: {self.count} > {self.limit}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "count": self.count,
            "limit": self.limit,
            "detail": self.detail,
        }


class SafetyShell:
    """Единая точка проверки действий и порогов аномалий."""

    def __init__(
        self,
        config: SafetyConfig | None = None,
        *,
        storage: Any | None = None,
        approved: bool = False,
    ) -> None:
        self.config = config or SafetyConfig()
        self.storage = storage
        self.approved = approved

        self.verdicts: list[SafetyVerdict] = []
        self.anomalies: list[Anomaly] = []
        self.forbidden_attempts = 0

    # --- action gate ---------------------------------------------------

    @property
    def is_locked(self) -> bool:
        """После N запрещённых попыток shell закрывается до перезапуска."""
        return self.forbidden_attempts >= self.config.max_forbidden_attempts

    def check(self, action: Action) -> SafetyVerdict:
        """Проверяет действие; в журнал попадают только отказы."""
        return self._apply(action, audit_all=False)

    def enforce(self, action: Action) -> SafetyVerdict:
        """Проверяет действие и в любом случае пишет решение в audit-log."""
        return self._apply(action, audit_all=True)

    def _apply(self, action: Action, *, audit_all: bool) -> SafetyVerdict:
        verdict = self._decide(action)
        self.verdicts.append(verdict)

        if verdict.action_class is ActionClass.FORBIDDEN and not verdict.allowed:
            self.forbidden_attempts += 1

        if audit_all or not verdict.allowed:
            self._audit(
                "safety",
                verdict.label,
                {
                    "action": action.name,
                    "class": verdict.action_class.value,
                    "reason": verdict.reason,
                    "actor": action.actor,
                    "payload": dict(action.payload),
                },
            )
        return verdict

    def _decide(self, action: Action) -> SafetyVerdict:
        if self.is_locked:
            return SafetyVerdict(
                False,
                action,
                "shell is locked after too many forbidden attempts",
            )

        if action.action_class is ActionClass.FORBIDDEN:
            return SafetyVerdict(
                False,
                action,
                "forbidden in v0.1 (ADR-015): no code, web, files or self-modification",
            )

        if action.action_class is ActionClass.APPROVAL:
            if self.approved:
                return SafetyVerdict(True, action, "approved by the creator")
            return SafetyVerdict(
                False, action, "approval required: no approver in CLI"
            )

        if action.action_class is ActionClass.GUARDED:
            return SafetyVerdict(True, action, "guarded action is audited")

        return SafetyVerdict(True, action, "safe")

    # --- anomaly thresholds --------------------------------------------

    def observe_turn(
        self,
        *,
        new_nodes: int = 0,
        new_edges: int = 0,
        conflicts: int = 0,
        turn_index: int | None = None,
    ) -> tuple[Anomaly, ...]:
        """Проверяет, не вышла ли волна одного хода за пороги."""
        found: list[Anomaly] = []

        def check(kind: str, count: int, limit: int) -> None:
            if count > limit:
                found.append(Anomaly(kind, count, limit))

        check(
            "new_nodes_per_turn",
            new_nodes,
            self.config.max_new_nodes_per_turn,
        )
        check(
            "new_edges_per_turn",
            new_edges,
            self.config.max_new_edges_per_turn,
        )
        check(
            "conflicts_per_turn",
            conflicts,
            self.config.max_conflicts_per_turn,
        )

        for anomaly in found:
            self._audit(
                "safety",
                "anomaly",
                {
                    **anomaly.to_dict(),
                    "turn_index": turn_index,
                },
            )

        self.anomalies.extend(found)
        return tuple(found)

    # --- audit ---------------------------------------------------------

    def _audit(
        self,
        entity_type: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> None:
        logger = getattr(self.storage, "log_event", None)
        if logger is None:
            return
        logger(
            entity_type,
            _SAFETY_ENTITY_ID,
            action,
            after=dict(payload),
            source="safety_shell",
        )


_SAFETY_ENTITY_ID = uuid.UUID("00000000-0000-0000-0000-0000000005af")

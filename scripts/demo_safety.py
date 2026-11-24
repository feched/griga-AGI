"""Демонстрация safety shell (ADR-010).

Показывает классы действий, approval-gate, блокировку после запрещённых
попыток, пороги аномалий и audit-log. Работает в памяти.
"""

from __future__ import annotations

import sys
import uuid

from griga.config import SafetyConfig
from griga.shell import Action, ActionClass, SafetyShell


class MemoryStorage:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def log_event(
        self,
        entity_type,
        entity_id,
        action,
        *,
        before=None,
        after=None,
        source=None,
    ):
        self.events.append(
            {
                "entity_type": entity_type,
                "entity_id": uuid.UUID(str(entity_id)),
                "action": action,
                "before": before,
                "after": after,
                "source": source,
            }
        )
        return len(self.events)


def show(action: Action, shell: SafetyShell) -> None:
    verdict = shell.enforce(action)
    mark = "OK " if verdict.allowed else "DENY"
    print(f"  [{mark}] {action.name:<12} ({action.action_class.value}): {verdict.reason}")


def main(argv: list[str]) -> int:
    storage = MemoryStorage()
    shell = SafetyShell(SafetyConfig(), storage=storage)

    print("1. Классы действий\n")
    show(Action("read_graph", ActionClass.SAFE), shell)
    show(Action("write_fact", ActionClass.GUARDED, payload={"edges": 1}), shell)
    show(Action("delete_fact", ActionClass.APPROVAL), shell)
    show(Action("run_code", ActionClass.FORBIDDEN), shell)
    show(Action("web_search", ActionClass.FORBIDDEN), shell)

    print("\n2. Пороги аномалий\n")
    anomalies = shell.observe_turn(
        new_nodes=5, new_edges=25, conflicts=2, turn_index=12
    )
    if not anomalies:
        print("  аномалий нет")
    for anomaly in anomalies:
        print(f"  ! {anomaly.reason}")

    print("\n3. Блокировка после запрещённых попыток\n")
    show(Action("write_file", ActionClass.FORBIDDEN), shell)
    show(Action("read_graph", ActionClass.SAFE), shell)

    print("\n4. Audit-log\n")
    for event in storage.events:
        payload = event["after"] or {}
        print(
            f"  {event['action']:<8} {payload.get('action', payload.get('kind', '')):<12} "
            f"{event['source']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

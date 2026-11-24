import uuid
from dataclasses import replace

import pytest

from griga.config import SafetyConfig, load_config
from griga.dialogue import Dialogue
from griga.graph.graph import KnowledgeGraph
from griga.shell import (
    Action,
    ActionClass,
    Anomaly,
    SafetyShell,
)


class MemoryStorage:
    """Память с audit-log: shell проверяется без PostgreSQL."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.events = []

    def load_all_nodes(self, owner_id=None, *, include_global=True):
        return list(self.nodes.values())

    def load_all_edges(self, owner_id=None, *, include_global=True):
        return list(self.edges.values())

    def save_node(self, node):
        self.nodes[node.id] = node
        return node.id

    def save_edge(self, edge):
        self.edges[edge.id] = edge
        return edge.id

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


@pytest.fixture()
def storage():
    return MemoryStorage()


@pytest.fixture()
def shell(storage):
    return SafetyShell(SafetyConfig(), storage=storage)


def action(name, action_class, **payload):
    return Action(name, action_class, payload=payload)


def test_safe_action_is_allowed(shell):
    verdict = shell.check(action("read_graph", ActionClass.SAFE))

    assert verdict.allowed
    assert verdict.reason == "safe"
    assert verdict.label == "allow"


def test_guarded_action_is_allowed(shell):
    verdict = shell.check(action("write_fact", ActionClass.GUARDED))

    assert verdict.allowed
    assert "audited" in verdict.reason


def test_approval_requires_approver(shell):
    verdict = shell.check(action("delete_fact", ActionClass.APPROVAL))

    assert not verdict.allowed
    assert "approval" in verdict.reason
    assert verdict.label == "deny"


def test_approval_is_allowed_with_explicit_approval(storage):
    shell = SafetyShell(SafetyConfig(), storage=storage, approved=True)

    assert shell.check(action("delete_fact", ActionClass.APPROVAL)).allowed


def test_forbidden_action_is_denied(shell):
    verdict = shell.check(action("run_code", ActionClass.FORBIDDEN))

    assert not verdict.allowed
    assert "ADR-015" in verdict.reason
    assert shell.forbidden_attempts == 1
    assert not shell.is_locked


def test_shell_locks_after_forbidden_attempts(shell):
    for _ in range(shell.config.max_forbidden_attempts):
        shell.check(action("run_code", ActionClass.FORBIDDEN))

    assert shell.is_locked
    verdict = shell.check(action("read_graph", ActionClass.SAFE))

    assert not verdict.allowed
    assert "locked" in verdict.reason


def test_denied_action_is_audited(shell, storage):
    shell.check(action("web_search", ActionClass.FORBIDDEN, query="погода"))

    assert len(storage.events) == 1
    event = storage.events[0]
    assert event["entity_type"] == "safety"
    assert event["action"] == "deny"
    assert event["after"]["action"] == "web_search"
    assert event["after"]["payload"]["query"] == "погода"
    assert event["source"] == "safety_shell"


def test_enforce_audits_allowed_actions(shell, storage):
    shell.enforce(action("write_fact", ActionClass.GUARDED, edges=1))

    assert len(storage.events) == 1
    assert storage.events[0]["action"] == "allow"


def test_check_does_not_audit_allowed_actions(shell, storage):
    shell.check(action("read_graph", ActionClass.SAFE))

    assert storage.events == []


def test_observe_turn_returns_anomalies(shell):
    anomalies = shell.observe_turn(
        new_nodes=50,
        new_edges=25,
        conflicts=2,
        turn_index=7,
    )

    kinds = {anomaly.kind for anomaly in anomalies}
    assert kinds == {
        "new_nodes_per_turn",
        "new_edges_per_turn",
        "conflicts_per_turn",
    }
    assert all(isinstance(anomaly, Anomaly) for anomaly in anomalies)
    assert shell.anomalies == list(anomalies)


def test_observe_turn_is_quiet_within_limits(shell, storage):
    anomalies = shell.observe_turn(new_nodes=3, new_edges=2, conflicts=0)

    assert anomalies == ()
    assert storage.events == []


def test_observe_turn_audits_anomalies(shell, storage):
    shell.observe_turn(new_edges=21, turn_index=3)

    event = storage.events[0]
    assert event["action"] == "anomaly"
    assert event["after"]["kind"] == "new_edges_per_turn"
    assert event["after"]["turn_index"] == 3


def test_dialogue_passes_safety_events_to_audit(storage):
    graph = KnowledgeGraph(storage)
    dialogue = Dialogue(graph, learning=False)

    turn = dialogue.turn("Трава — это растение.")

    assert turn.anomalies == ()
    actions = [event["action"] for event in storage.events]
    assert "allow" in actions
    assert "create" in actions


def test_dialogue_reports_anomaly_with_strict_thresholds(storage):
    cfg = load_config()
    cfg = replace(
        cfg,
        safety=replace(
            cfg.safety,
            max_new_edges_per_turn=0,
            max_new_nodes_per_turn=1,
        ),
    )
    graph = KnowledgeGraph(storage)
    dialogue = Dialogue(graph, cfg, learning=False)

    turn = dialogue.turn("Трава — это растение.")

    kinds = {anomaly.kind for anomaly in turn.anomalies}
    assert "new_edges_per_turn" in kinds
    assert "new_nodes_per_turn" in kinds


def test_action_rejects_empty_name():
    with pytest.raises(ValueError, match="non-empty"):
        Action("  ", ActionClass.SAFE)

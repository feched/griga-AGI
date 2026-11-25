import json
from datetime import datetime
from types import SimpleNamespace

from griga.graph.graph import KnowledgeGraph
from griga.interfaces.agent import (
    build_parser,
    format_banner,
    format_history,
    format_status,
    format_trace,
    parse_command,
    _export_snapshot,
)


class MemoryStorage:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

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


def test_parse_command_reads_name_and_argument():
    command = parse_command("  /user Алиса ")

    assert command.name == "/user"
    assert command.argument == "Алиса"


def test_parse_command_returns_none_for_plain_text():
    assert parse_command("Трава — это растение.") is None
    assert parse_command("") is None


def test_parse_command_supports_bare_command():
    command = parse_command("/quit")

    assert command.name == "/quit"
    assert command.argument == ""


def test_format_banner_contains_user_and_counts():
    banner = format_banner("Алиса", 12, 7)

    assert "Гриша v" in banner
    assert "Алиса" in banner
    assert "12" in banner and "7" in banner
    assert "/help" in banner


def test_format_status_lists_session_state():
    text = format_status(
        node_count=10,
        edge_count=4,
        turn_index=3,
        user_name="Боб",
        last_intent="ответить_прямо",
        learning=True,
        conflicts=1,
        anomalies=2,
    )

    assert "Боб" in text
    assert "10 / 4" in text
    assert "ответить_прямо" in text
    assert "1 / 2" in text


def test_format_history_renders_events():
    events = [
        {
            "created_at": datetime(2026, 11, 25, 12, 30, 5),
            "action": "create",
            "entity_type": "edge",
            "entity_id": "abc",
            "source": "Трава — это растение.",
        }
    ]

    text = format_history(events)

    assert "2026-11-25 12:30:05" in text
    assert "create" in text
    assert "Трава — это растение." in text


def test_format_history_handles_empty_list():
    assert format_history([]) == "История изменений пуста."


def test_format_trace_mentions_intent_and_construction():
    turn = SimpleNamespace(
        intent="ответить_прямо",
        construction_id="answer_is_a",
        attempts=1,
        conflicts=0,
        anomalies=(),
    )

    trace = format_trace(turn)

    assert "ответить_прямо" in trace
    assert "answer_is_a" in trace
    assert "попыток: 1" in trace


def test_format_trace_marks_conflicts_and_anomalies():
    turn = SimpleNamespace(
        intent="запомнить_факт",
        construction_id="ack_fact",
        attempts=1,
        conflicts=1,
        anomalies=(object(),),
    )

    trace = format_trace(turn)

    assert "конфликтов: 1" in trace
    assert "аномалий: 1" in trace


def test_agent_parser_defaults():
    args = build_parser().parse_args([])

    assert args.user is None
    assert args.no_learning is False


def test_export_snapshot_writes_json(tmp_path):
    graph = KnowledgeGraph(MemoryStorage())
    target = tmp_path / "snapshot.json"

    written = _export_snapshot(graph, str(target))

    assert written == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["meta"]["node_count"] == 0
    assert payload["nodes"] == []

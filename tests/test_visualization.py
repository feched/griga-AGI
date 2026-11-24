import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from griga.config import Config, MemoryConfig
from griga.dialogue import Dialogue
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node
from griga.graph.relations import RelationType
from griga.visualization import (
    VisualizerServer,
    build_snapshot,
    snapshot_for_node,
)
from griga.visualization.snapshot import EdgeView
from griga.thinking.spreader import Spreader


class MemoryStorage:
    """Хранилище-заглушка: визуализатору не нужен PostgreSQL."""

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


def make_graph():
    graph = KnowledgeGraph(MemoryStorage())
    grass = graph.add_node(Node("трава"))
    plant = graph.add_node(Node("растение"))
    edge = graph.add_edge(
        Edge(
            source_id=grass.id,
            target_id=plant.id,
            relation_type=RelationType.IS_A,
            weight=0.7,
            metadata={"label": "это"},
        )
    )
    return graph, grass, plant, edge


def test_empty_snapshot_has_zero_counts():
    graph = KnowledgeGraph(MemoryStorage())
    snapshot = build_snapshot(graph)

    assert snapshot.nodes == ()
    assert snapshot.edges == ()
    payload = snapshot.to_dict()
    assert payload["meta"]["node_count"] == 0
    assert payload["meta"]["active_count"] == 0


def test_snapshot_marks_active_nodes_and_edges():
    graph, grass, plant, edge = make_graph()
    spreader = Spreader(graph)
    memory = spreader.activate([grass])
    snapshot = build_snapshot(graph, memory)

    payload = snapshot.to_dict()
    by_name = {node["name"]: node for node in payload["nodes"]}
    assert by_name["трава"]["active"] is True
    assert by_name["трава"]["activation"] > 0
    assert by_name["растение"]["active"] is True
    assert payload["edges"][0]["active"] is True
    assert payload["meta"]["active_count"] == 2


def test_snapshot_keeps_relation_and_label():
    graph, grass, plant, edge = make_graph()
    snapshot = build_snapshot(graph)

    edge_view = snapshot.edges[0]
    assert isinstance(edge_view, EdgeView)
    assert edge_view.relation == "is_a"
    assert edge_view.label == "это"
    assert edge_view.weight == pytest.approx(0.7)
    assert edge_view.active is False


def test_snapshot_for_node_finds_by_name():
    graph, grass, plant, edge = make_graph()

    assert snapshot_for_node(graph, "трава").id == grass.id
    assert snapshot_for_node(graph, "нет такого") is None


@pytest.fixture()
def running_server():
    graph, grass, plant, edge = make_graph()
    config = Config(memory=MemoryConfig(top_k=5))
    server = VisualizerServer(graph, config, port=0)
    httpd, thread = server.start_background()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield server, base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_server_health_and_graph(running_server):
    _, base = running_server

    status, payload = get_json(f"{base}/api/health")
    assert status == 200
    assert payload == {"status": "ok"}

    status, payload = get_json(f"{base}/api/graph")
    assert status == 200
    assert payload["meta"]["node_count"] == 2
    assert payload["meta"]["active_count"] == 0


def test_server_activate_endpoint(running_server):
    _, base = running_server
    node = urllib.parse.quote("трава")

    status, payload = get_json(f"{base}/api/activate?node={node}")
    assert status == 200
    assert payload["meta"]["active_count"] == 2
    assert payload["meta"]["last_query"] == "трава"
    assert any(edge["active"] for edge in payload["edges"])


def test_server_unknown_node_returns_404(running_server):
    _, base = running_server
    node = urllib.parse.quote("квазар")

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get_json(f"{base}/api/activate?node={node}")
    assert excinfo.value.code == 404


def test_server_reset_clears_activation(running_server):
    _, base = running_server
    get_json(f"{base}/api/activate?node={urllib.parse.quote('трава')}")

    request = urllib.request.Request(f"{base}/api/reset", method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    assert payload["meta"]["active_count"] == 0
    assert payload["meta"].get("last_query") is None


def test_server_serves_index_and_assets(running_server):
    _, base = running_server

    with urllib.request.urlopen(f"{base}/", timeout=5) as response:
        html = response.read().decode("utf-8")
    assert "Griga" in html
    assert "/app.js" in html

    with urllib.request.urlopen(f"{base}/app.js", timeout=5) as response:
        assert response.status == 200
        assert b"forceSimulation" in response.read()

    with urllib.request.urlopen(
        f"{base}/vendor/d3.min.js", timeout=5
    ) as response:
        assert response.status == 200
        assert len(response.read()) > 1000


def test_snapshot_from_dialogue_marks_working_memory():
    graph = KnowledgeGraph(MemoryStorage())
    dialogue = Dialogue(graph, learning=False)
    dialogue.turn("Трава — это растение.")
    turn = dialogue.turn("Трава зелёная?")

    snapshot = build_snapshot(graph, turn.memory)
    active = [node.name for node in snapshot.nodes if node.active]

    assert "трава" in active

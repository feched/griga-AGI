import math

import pytest

from griga.config import ActivationConfig
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node
from griga.graph.relations import RelationType
from griga.thinking.spreader import Spreader


class MemoryStorage:
    """Хранилище-заглушка: тесты spreader не требуют PostgreSQL."""

    def __init__(self):
        self.nodes = []
        self.edges = []

    def load_all_nodes(self, owner_id=None, *, include_global=True):
        return list(self.nodes)

    def load_all_edges(self, owner_id=None, *, include_global=True):
        return list(self.edges)

    def save_node(self, node):
        self.nodes.append(node)
        return node.id

    def save_edge(self, edge):
        self.edges.append(edge)
        return edge.id


def make_graph() -> KnowledgeGraph:
    return KnowledgeGraph(MemoryStorage())


def link(
    graph: KnowledgeGraph,
    source: Node,
    target: Node,
    weight: float = 0.5,
) -> Edge:
    return graph.add_edge(
        Edge(
            source_id=source.id,
            target_id=target.id,
            relation_type=RelationType.IS_A,
            weight=weight,
        )
    )


def cfg(**overrides) -> ActivationConfig:
    base = dict(decay=0.85, threshold=0.1, max_depth=3, clamp=1.0, fan_effect=True)
    base.update(overrides)
    return ActivationConfig(**base)


def test_initialize_sets_one_and_ignores_unknown():
    graph = make_graph()
    a = graph.add_node(Node(name="A"))
    b = graph.add_node(Node(name="B"))
    unknown = Node(name="unknown")
    spreader = Spreader(graph, cfg())

    activation = spreader.initialize([a, b.id, str(unknown.id)])

    assert activation == {a.id: 1.0, b.id: 1.0}
    assert unknown.id not in activation


def test_single_edge_transfer_uses_weight_decay_and_fan():
    graph = make_graph()
    a = graph.add_node(Node(name="A"))
    b = graph.add_node(Node(name="B"))
    link(graph, a, b, weight=0.5)
    spreader = Spreader(graph, cfg())

    activation = spreader.spread([a], max_depth=1)

    # degree(A)=1 -> fan=max(2, ln(2))=2
    expected = 1.0 * 0.5 * 0.85 / 2.0
    assert activation[a.id] == pytest.approx(1.0)
    assert activation[b.id] == pytest.approx(expected)


def test_clamp_never_exceeds_one():
    graph = make_graph()
    a = graph.add_node(Node(name="A"))
    b = graph.add_node(Node(name="B"))
    link(graph, a, b, weight=1.0)
    spreader = Spreader(graph, cfg())

    activation = spreader.spread([a], max_depth=3)

    assert activation[b.id] == pytest.approx(1.0)
    assert max(activation.values()) <= 1.0


def test_fan_effect_reduces_hub_transfer():
    graph = make_graph()
    hub = graph.add_node(Node(name="Hub"))
    leaves = [graph.add_node(Node(name=f"L{i}")) for i in range(10)]
    for leaf in leaves:
        link(graph, hub, leaf, weight=1.0)

    a = graph.add_node(Node(name="A"))
    b = graph.add_node(Node(name="B"))
    link(graph, a, b, weight=1.0)

    spreader = Spreader(graph, cfg())

    hub_activation = spreader.spread([hub], max_depth=1)[leaves[0].id]
    leaf_activation = spreader.spread([a], max_depth=1)[b.id]

    # hub: fan=max(2, ln(11)) ~= 2.398; leaf: fan=2
    assert hub_activation == pytest.approx(1.0 * 1.0 * 0.85 / math.log1p(10))
    assert leaf_activation == pytest.approx(1.0 * 1.0 * 0.85 / 2.0)
    assert hub_activation < leaf_activation


def test_threshold_drops_weak_nodes_from_working_memory():
    graph = make_graph()
    a = graph.add_node(Node(name="A"))
    b = graph.add_node(Node(name="B"))
    link(graph, a, b, weight=0.1)
    spreader = Spreader(graph, cfg())

    memory = spreader.activate([a], max_depth=1)

    assert memory.names() == ["A"]
    assert b.name not in memory.names()


def test_working_memory_sorted_and_limited_to_top5():
    graph = make_graph()
    root = graph.add_node(Node(name="A"))
    leaves = [graph.add_node(Node(name=f"L{i}")) for i in range(7)]
    for leaf in leaves:
        link(graph, root, leaf, weight=0.5)

    spreader = Spreader(graph, cfg())
    memory = spreader.activate([root], max_depth=3)

    assert len(memory) == 5
    assert memory[0].name == "A"
    assert all(item.activation >= 0.1 for item in memory)
    values = [item.activation for item in memory]
    assert values == sorted(values, reverse=True)


def test_depth_limit_controls_reachability():
    graph = make_graph()
    a = graph.add_node(Node(name="A"))
    b = graph.add_node(Node(name="B"))
    c = graph.add_node(Node(name="C"))
    link(graph, a, b, weight=1.0)
    link(graph, b, c, weight=1.0)
    spreader = Spreader(graph, cfg())

    depth0 = spreader.working_memory(spreader.spread([a], max_depth=0))
    depth1 = spreader.working_memory(spreader.spread([a], max_depth=1))
    depth2 = spreader.working_memory(spreader.spread([a], max_depth=2))

    assert depth0.names() == ["A"]
    assert set(depth1.names()) == {"A", "B"}
    assert set(depth2.names()) == {"A", "B", "C"}


def test_fan_effect_can_be_disabled():
    graph = make_graph()
    hub = graph.add_node(Node(name="Hub"))
    leaves = [graph.add_node(Node(name=f"L{i}")) for i in range(10)]
    for leaf in leaves:
        link(graph, hub, leaf, weight=1.0)

    spreader = Spreader(graph, cfg(fan_effect=False))
    activation = spreader.spread([hub], max_depth=1)

    assert activation[leaves[0].id] == pytest.approx(0.85)

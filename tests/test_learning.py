import pytest

from griga.config import Config, LearningConfig
from griga.dialogue import Dialogue
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node
from griga.graph.relations import RelationType
from griga.learning import Forgetting, HebbLearner, SupervisedLearner
from griga.thinking.spreader import ActivatedNode, WorkingMemory


class MemoryStorage:
    """Хранилище-заглушка: обучению не нужен PostgreSQL."""

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
    lawn = graph.add_node(Node("газон"))
    is_a = graph.add_edge(
        Edge(
            source_id=grass.id,
            target_id=plant.id,
            relation_type=RelationType.IS_A,
            weight=0.5,
        )
    )
    related = graph.add_edge(
        Edge(
            source_id=plant.id,
            target_id=lawn.id,
            relation_type=RelationType.RELATED_TO,
            weight=0.5,
        )
    )
    return graph, grass, plant, lawn, is_a, related


def memory(*pairs) -> WorkingMemory:
    return WorkingMemory(
        items=tuple(
            ActivatedNode(node=node, activation=activation)
            for node, activation in pairs
        ),
        threshold=0.1,
        top_k=5,
    )


def test_hebb_reinforces_only_coactive_edge():
    graph, grass, plant, lawn, is_a, related = make_graph()
    learner = HebbLearner(graph, LearningConfig(eta=0.05))

    changes = learner.reinforce(memory((grass, 1.0), (plant, 0.5)))

    assert is_a.weight == pytest.approx(0.525)
    assert related.weight == pytest.approx(0.5)
    assert len(changes) == 1
    assert changes[0].edge_id == is_a.id
    assert changes[0].delta == pytest.approx(0.025)


def test_hebb_needs_two_active_nodes():
    graph, grass, plant, lawn, is_a, related = make_graph()
    learner = HebbLearner(graph, LearningConfig())

    assert learner.reinforce(memory((grass, 1.0))) == ()
    assert is_a.weight == pytest.approx(0.5)


def test_hebb_clamps_weight_at_max():
    graph, grass, plant, lawn, is_a, related = make_graph()
    is_a.weight = 0.99
    learner = HebbLearner(graph, LearningConfig(eta=0.05))

    changes = learner.reinforce(memory((grass, 1.0), (plant, 1.0)))

    assert is_a.weight == pytest.approx(1.0)
    assert changes[0].delta == pytest.approx(0.01)


def test_hebb_does_not_create_new_edges():
    graph, grass, plant, lawn, is_a, related = make_graph()
    learner = HebbLearner(graph, LearningConfig())

    learner.reinforce(memory((grass, 1.0), (lawn, 1.0)))

    assert len(graph.edges) == 2


def test_supervised_confirm_and_deny():
    graph, grass, plant, lawn, is_a, related = make_graph()
    learner = SupervisedLearner(graph, LearningConfig(supervised_delta=0.2))

    confirmed = learner.confirm(is_a)
    assert is_a.weight == pytest.approx(0.7)
    assert confirmed.reason == "confirm"

    denied = learner.deny(is_a)
    assert is_a.weight == pytest.approx(0.5)
    assert denied.reason == "deny"


def test_supervised_respects_edge_bounds():
    graph, grass, plant, lawn, is_a, related = make_graph()
    learner = SupervisedLearner(graph, LearningConfig(supervised_delta=0.9))

    learner.confirm(is_a)
    assert is_a.weight == pytest.approx(1.0)

    learner.deny(is_a)
    learner.deny(is_a)
    assert is_a.weight == pytest.approx(Edge.MIN_WEIGHT)


def test_forgetting_due_schedule():
    graph, *_ = make_graph()
    forgetting = Forgetting(graph, LearningConfig(forgetting_every_turns=3))

    assert not forgetting.due(0)
    assert not forgetting.due(2)
    assert forgetting.due(3)
    assert forgetting.due(6)


def test_forgetting_decays_weights_to_floor():
    graph, grass, plant, lawn, is_a, related = make_graph()
    forgetting = Forgetting(
        graph,
        LearningConfig(forgetting_factor=0.99, min_weight=0.05),
    )

    changes = forgetting.decay()
    assert len(changes) == 2
    assert is_a.weight == pytest.approx(0.495)

    for _ in range(500):
        forgetting.decay()
    assert is_a.weight == pytest.approx(0.05)


def test_graph_update_edge_weight_clamps_and_persists():
    graph, grass, plant, lawn, is_a, related = make_graph()

    graph.update_edge_weight(is_a, 5.0)
    assert is_a.weight == pytest.approx(1.0)
    assert graph.storage.edges[is_a.id].weight == pytest.approx(1.0)

    graph.update_edge_weight(is_a, -1.0)
    assert is_a.weight == pytest.approx(Edge.MIN_WEIGHT)


def test_dialogue_reinforces_edge_after_fact():
    graph = KnowledgeGraph(MemoryStorage())
    dialogue = Dialogue(graph)

    turn = dialogue.turn("Трава — это растение.")

    assert turn.learned
    edge = next(iter(graph.edges.values()))
    assert edge.weight > 0.5
    assert dialogue.learning_log


def test_dialogue_learning_can_be_disabled():
    graph = KnowledgeGraph(MemoryStorage())
    dialogue = Dialogue(graph, learning=False)

    turn = dialogue.turn("Трава — это растение.")

    assert turn.learned == ()
    edge = next(iter(graph.edges.values()))
    assert edge.weight == pytest.approx(0.55)


def test_dialogue_forgets_every_configured_turn():
    graph = KnowledgeGraph(MemoryStorage())
    config = Config(learning=LearningConfig(forgetting_every_turns=1))
    dialogue = Dialogue(graph, config)

    turn = dialogue.turn("Трава — это растение.")

    assert turn.forgotten
    assert all(change.reason == "forgetting" for change in turn.forgotten)

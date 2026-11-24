import pytest

from griga.graph.graph import KnowledgeGraph
from griga.graph.relations import RelationType
from griga.perception import PerceptionParser, apply_parse
from griga.perception.models import Mention, ParseResult, Polarity, Statement
from griga.validation import GraphValidator


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


@pytest.fixture(scope="module")
def parser():
    return PerceptionParser()


@pytest.fixture()
def graph():
    return KnowledgeGraph(MemoryStorage())


def mention(lemma):
    return Mention(lemma=lemma, form=lemma, pos="NOUN")


def statement(subject, relation, obj):
    return Statement(
        subject=mention(subject),
        object=mention(obj),
        relation=relation,
        label=relation.value,
        source_text=f"{subject} {relation.value} {obj}",
        confidence=0.55,
    )


def test_validator_accepts_new_subject(graph):
    decision = GraphValidator(graph).check(
        statement("трава", RelationType.IS_A, "растение")
    )

    assert decision.accepted
    assert not decision.is_conflict
    assert decision.reason == "new subject"


def test_validator_accepts_same_fact(graph, parser):
    apply_parse(parser.parse("Трава — это растение."), graph)

    decision = GraphValidator(graph).check(
        statement("трава", RelationType.IS_A, "растение")
    )

    assert decision.accepted
    assert not decision.is_conflict


def test_validator_flags_contradicting_is_a(graph, parser):
    apply_parse(parser.parse("Трава — это растение."), graph)

    decision = GraphValidator(graph).check(
        statement("трава", RelationType.IS_A, "животное"),
    )

    assert not decision.accepted
    assert decision.confidence == pytest.approx(0.15)
    assert decision.is_conflict
    assert decision.conflicts[0].existing_object == "растение"
    assert decision.conflicts[0].new_object == "животное"


def test_validator_ignores_non_functional_relations(graph, parser):
    apply_parse(parser.parse("Трава — это растение."), graph)

    decision = GraphValidator(graph).check(
        statement("трава", RelationType.HAS_PROPERTY, "зелёная")
    )

    assert decision.accepted
    assert decision.reason == "not functional"


def test_validator_rejects_non_facts(graph):
    fact = statement("трава", RelationType.IS_A, "растение")
    question = Statement(
        subject=fact.subject,
        object=fact.object,
        relation=fact.relation,
        label=fact.label,
        source_text="Трава — это растение?",
        is_question=True,
    )

    decision = GraphValidator(graph).check(question)

    assert not decision.accepted
    assert decision.confidence == 0.0
    assert decision.reason == "not a fact"


def test_validator_rejects_invalid_confidence(graph):
    with pytest.raises(ValueError, match="conflict_confidence"):
        GraphValidator(graph, conflict_confidence=0)


def test_apply_parse_writes_conflict_with_low_weight(graph, parser):
    apply_parse(parser.parse("Трава — это растение."), graph)

    applied = apply_parse(parser.parse("Трава — это животное."), graph)

    assert applied.conflicting_edges == 1
    grass = graph.find_node("трава")
    plant = graph.find_node("растение")
    animal = graph.find_node("животное")

    old = graph.find_edge(grass.id, plant.id, RelationType.IS_A)
    new = graph.find_edge(grass.id, animal.id, RelationType.IS_A)

    assert old.weight == pytest.approx(0.6, abs=0.3)
    assert new.weight == pytest.approx(0.15)
    assert new.metadata["validation"] == "conflict"
    assert new.metadata["conflict_reason"]
    assert old.metadata.get("validation") is None


def test_apply_parse_validate_false_keeps_normal_weight(graph, parser):
    apply_parse(parser.parse("Трава — это растение."), graph)

    applied = apply_parse(
        parser.parse("Трава — это животное."), graph, validate=False
    )

    assert applied.conflicting_edges == 0
    grass = graph.find_node("трава")
    animal = graph.find_node("животное")
    new = graph.find_edge(grass.id, animal.id, RelationType.IS_A)

    assert new.metadata.get("validation") is None
    assert new.weight > 0.15


def test_question_does_not_touch_graph(graph, parser):
    result: ParseResult = parser.parse("Что такое трава?")
    applied = apply_parse(result, graph)

    assert applied.created_edges == ()
    assert applied.created_nodes == ()
    assert graph.node_count == 0

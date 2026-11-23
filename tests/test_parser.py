import pytest

from griga.config import Config, PerceptionConfig
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import NodeType
from griga.graph.relations import RelationType
from griga.perception import PerceptionParser, apply_parse
from griga.perception.models import Polarity, SpeechAct


class MemoryStorage:
    """Хранилище-заглушка: тесты парсера не требуют PostgreSQL."""

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


def test_dash_copula_gives_is_a(parser):
    result = parser.parse("Трава — это растение.")

    assert set(result.concept_names()) == {"трава", "растение"}
    statement = result.find_statement("трава", RelationType.IS_A, "растение")
    assert statement is not None
    assert statement.label == "это"
    assert statement.is_fact
    assert result.markers.speech_act is SpeechAct.STATEMENT


def test_copula_without_dash_gives_is_a(parser):
    result = parser.parse("Трава это растение.")

    statement = result.find_statement("трава", RelationType.IS_A, "растение")
    assert statement is not None
    assert statement.is_fact


def test_adjective_becomes_property(parser):
    result = parser.parse("Трава зелёная.")

    assert "трава" in result.concept_names()
    assert "зеленый" in [item.lemma for item in result.properties()]
    statement = result.find_statement(
        "трава", RelationType.HAS_PROPERTY, "зеленый"
    )
    assert statement is not None
    assert statement.label == "свойство"


def test_verb_with_preposition_becomes_related_to(parser):
    result = parser.parse("Трава растёт на газоне.")

    statement = result.find_statement(
        "трава", RelationType.RELATED_TO, "газон"
    )
    assert statement is not None
    assert statement.label == "расти_на"
    assert statement.is_fact


def test_part_of_from_dash(parser):
    result = parser.parse("Собака — часть семьи.")

    statement = result.find_statement(
        "собака", RelationType.PART_OF, "семья"
    )
    assert statement is not None
    assert statement.label == "часть"
    # «часть» — служебное слово, а не концепт.
    assert "часть" not in result.concept_names()


def test_part_of_is_reversed_for_consists_of(parser):
    result = parser.parse("Дом состоит из кирпича.")

    statement = result.find_statement(
        "кирпич", RelationType.PART_OF, "дом"
    )
    assert statement is not None


def test_negation_is_not_a_fact(parser):
    result = parser.parse("Трава не синяя.")

    statement = result.find_statement(
        "трава", RelationType.HAS_PROPERTY, "синий"
    )
    assert statement is not None
    assert statement.polarity is Polarity.NEGATED
    assert not statement.is_fact
    assert result.markers.has_negation


def test_question_is_not_a_fact(parser):
    result = parser.parse("Трава зелёная?")

    assert result.markers.is_question
    assert result.markers.speech_act is SpeechAct.QUESTION
    assert result.statements
    assert all(not statement.is_fact for statement in result.statements)


def test_greeting_marker_and_no_nodes(parser):
    result = parser.parse("Привет!")

    assert result.markers.speech_act is SpeechAct.GREETING
    assert result.markers.greeting == "привет"
    assert result.nodes == ()


def test_emotion_marker(parser):
    result = parser.parse("Мне грустно.")

    assert result.markers.speech_act is SpeechAct.EMOTION
    assert result.markers.emotion == "грусть"


def test_attribution_is_not_a_statement(parser):
    result = parser.parse("Вася сказал, что трава зелёная.")

    assert result.markers.attribution == "Вася"
    statement = result.find_statement(
        "трава", RelationType.HAS_PROPERTY, "зеленый"
    )
    assert statement is not None
    assert statement.is_fact
    assert all(item.subject.lemma != "вася" for item in result.statements)


def test_uncertainty_is_not_a_fact(parser):
    result = parser.parse("Наверное, трава зелёная.")

    assert result.markers.modality == "наверное"
    statement = result.find_statement(
        "трава", RelationType.HAS_PROPERTY, "зеленый"
    )
    assert statement is not None
    assert statement.polarity is Polarity.UNSURE
    assert not statement.is_fact


def test_heuristic_fallback_without_udpipe():
    fallback = PerceptionParser(
        Config(perception=PerceptionConfig(use_syntax=False))
    )

    copula = fallback.parse("Трава — это растение.")
    assert copula.find_statement("трава", RelationType.IS_A, "растение")

    property_result = fallback.parse("Трава зелёная.")
    assert property_result.find_statement(
        "трава", RelationType.HAS_PROPERTY, "зеленый"
    )

    verb_result = fallback.parse("Трава растёт на газоне.")
    statement = verb_result.find_statement(
        "трава", RelationType.RELATED_TO, "газон"
    )
    assert statement is not None
    assert statement.label == "расти_на"


def test_apply_parse_writes_only_facts(parser):
    graph = KnowledgeGraph(MemoryStorage())
    result = parser.parse(
        "Трава — это растение. Трава зелёная. Трава не синяя. "
        "Трава растёт на газоне?"
    )

    applied = apply_parse(result, graph)

    assert applied.node_count == 3
    assert applied.edge_count == 2
    assert applied.skipped_statements == 2

    grass = graph.find_node("трава", NodeType.CONCEPT)
    plant = graph.find_node("растение", NodeType.CONCEPT)
    green = graph.find_node("зеленый", NodeType.PROPERTY)
    assert grass is not None and plant is not None and green is not None
    assert graph.find_node("синий", NodeType.PROPERTY) is None
    assert graph.find_node("газон", NodeType.CONCEPT) is None

    assert graph.find_edge(grass.id, plant.id, RelationType.IS_A)
    assert graph.find_edge(grass.id, green.id, RelationType.HAS_PROPERTY)


def test_apply_parse_is_idempotent(parser):
    graph = KnowledgeGraph(MemoryStorage())
    result = parser.parse("Трава — это растение. Трава растёт на газоне.")

    first = apply_parse(result, graph)
    second = apply_parse(result, graph)

    assert first.edge_count == 2
    assert second.edge_count == 0
    assert second.duplicate_edges == 2
    assert graph.node_count == 3
    assert graph.edge_count == 2

    grass = graph.find_node("трава", NodeType.CONCEPT)
    gas = graph.find_node("газон", NodeType.CONCEPT)
    edge = graph.find_edge(grass.id, gas.id, RelationType.RELATED_TO)
    assert edge is not None
    assert edge.metadata["label"] == "расти_на"

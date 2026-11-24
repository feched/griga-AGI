import pytest

from griga.graph.graph import KnowledgeGraph
from griga.perception import PerceptionParser, apply_parse
from griga.speech.constructions import Construction, GraphPattern, SlotSpec
from griga.speech.generator import (
    Generator,
    SlotValue,
    TurnContext,
    _Candidate,
)
from griga.speech.intents import Intent
from griga.thinking.spreader import Spreader


class MemoryStorage:
    """Хранилище-заглушка: генератору не нужен PostgreSQL."""

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


@pytest.fixture()
def generator(graph):
    return Generator(graph)


@pytest.fixture()
def spreader(graph):
    return Spreader(graph)


def remember(graph, parser, text):
    parse = parser.parse(text)
    apply_parse(parse, graph)
    return parse


def answer(generator, spreader, parse, last_response=None):
    memory = spreader.activate([], top_k=5)
    return generator.generate(
        parse,
        memory,
        TurnContext(last_response=last_response),
    )


def test_greeting_uses_greeting_construction(graph, generator, parser, spreader):
    parse = parser.parse("Привет!")
    response = answer(generator, spreader, parse)

    assert response.intent is Intent.GREET
    assert response.construction_id == "greet_hello"
    assert response.text


def test_fact_is_acknowledged_from_graph(graph, generator, parser, spreader):
    parse = remember(graph, parser, "Трава — это растение.")
    response = answer(generator, spreader, parse)

    assert response.intent is Intent.ACKNOWLEDGE
    assert response.construction_id == "ack_is_a"
    assert "трава" in response.text.lower()
    assert "растение" in response.text.lower()


def test_negation_is_not_written_to_graph(graph, generator, parser, spreader):
    parse = remember(graph, parser, "Трава не синяя.")
    response = answer(generator, spreader, parse)

    assert response.construction_id == "ack_negation"
    assert graph.find_node("синий") is None
    assert not graph.edges


def test_what_is_question_prefers_is_a(graph, generator, parser, spreader):
    remember(graph, parser, "Трава — это растение.")
    remember(graph, parser, "Трава растёт на газоне.")

    parse = parser.parse("Что такое трава?")
    response = answer(generator, spreader, parse)

    assert response.intent is Intent.ANSWER_DIRECTLY
    assert response.construction_id == "answer_is_a"
    assert response.text == "Трава — это растение."


def test_where_question_prefers_verb_relation(graph, generator, parser, spreader):
    remember(graph, parser, "Трава — это растение.")
    remember(graph, parser, "Трава растёт на газоне.")

    parse = parser.parse("Где растёт трава?")
    response = answer(generator, spreader, parse)

    assert response.construction_id == "answer_verb"
    assert "газон" in response.text.lower()


def test_yes_no_question_uses_yes_construction(graph, generator, parser, spreader):
    remember(graph, parser, "Трава зелёная.")

    parse = parser.parse("Трава зелёная?")
    response = answer(generator, spreader, parse)

    assert response.construction_id == "yes_property"
    assert response.text.startswith("Да,")


def test_yes_no_question_without_fact_admits_ignorance(
    graph, generator, parser, spreader
):
    remember(graph, parser, "Трава зелёная.")

    parse = parser.parse("Трава синяя?")
    response = answer(generator, spreader, parse)

    assert response.intent is Intent.ADMIT_IGNORANCE
    assert response.construction_id == "unknown_yesno"


def test_unknown_topic_admits_ignorance(graph, generator, parser, spreader):
    parse = parser.parse("Что такое квазар?")
    response = answer(generator, spreader, parse)

    assert response.intent is Intent.ADMIT_IGNORANCE
    assert response.construction_id in {"unknown_generic", "unknown_topic"}


def test_command_is_refused(graph, generator, parser, spreader):
    parse = parser.parse("Расскажи анекдот.")
    response = answer(generator, spreader, parse)

    assert response.intent is Intent.REFUSE
    assert response.construction_id == "refuse_action"


def test_emotion_gets_empathy(graph, generator, parser, spreader):
    parse = parser.parse("Мне грустно.")
    response = answer(generator, spreader, parse)

    assert response.intent is Intent.EMPATHIZE
    assert response.construction_id.startswith("empathize")


def test_monitor_rejects_repeated_response(graph, generator, parser, spreader):
    remember(graph, parser, "Трава — это растение.")
    parse = parser.parse("Что такое трава?")

    first = answer(generator, spreader, parse)
    second = answer(generator, spreader, parse, last_response=first.text)

    assert second.text != first.text or second.construction_id == "fallback"


def test_render_inflects_noun_case(generator):
    construction = Construction(
        id="test",
        intent=Intent.ANSWER_DIRECTLY,
        template="{X} находится на {Y}.",
        graph_pattern=GraphPattern(),
        slots={
            "X": SlotSpec(pos="noun", case="nominative"),
            "Y": SlotSpec(pos="noun", case="prepositional"),
        },
    )
    candidate = _Candidate(
        construction=construction,
        values={
            "X": SlotValue(lemma="трава"),
            "Y": SlotValue(lemma="газон"),
        },
    )

    assert generator.render(candidate) == "Трава находится на газоне."


def test_vocabulary_matches_requires_preposition(generator):
    with_prep = Construction(
        id="with_prep",
        intent=Intent.ANSWER_DIRECTLY,
        template="{X} {VERB_PRES} {PREP} {Y}.",
    )
    without_prep = Construction(
        id="without_prep",
        intent=Intent.ANSWER_DIRECTLY,
        template="{X} {VERB_PRES} {Y}.",
    )

    assert generator._vocabulary_matches(with_prep, "расти", "на")
    assert not generator._vocabulary_matches(with_prep, "расти", None)
    assert not generator._vocabulary_matches(without_prep, "расти", "на")


def test_relation_priority_for_question_words(generator):
    from griga.graph.relations import RelationType

    assert (
        generator._relation_priority(RelationType.RELATED_TO, "где")
        < generator._relation_priority(RelationType.IS_A, "где")
    )
    assert (
        generator._relation_priority(RelationType.IS_A, "что")
        < generator._relation_priority(RelationType.RELATED_TO, "что")
    )

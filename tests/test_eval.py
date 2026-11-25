from pathlib import Path

import pytest

from griga.evaluation import (
    EvalCase,
    load_corpus,
    load_questions,
    run_eval,
    seed_graph,
)
from griga.graph.graph import KnowledgeGraph


ROOT = Path(__file__).resolve().parent.parent


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


@pytest.fixture()
def graph():
    return KnowledgeGraph(MemoryStorage())


def test_eval_corpus_and_questions_are_valid():
    corpus = load_corpus()
    name, cases = load_questions()

    assert name == "v0.1 basic facts"
    assert len(corpus) == 18
    assert len(cases) == 20
    assert len({case.id for case in cases}) == 20
    assert all(case.question for case in cases)


def test_seed_graph_writes_facts(graph):
    corpus = load_corpus()

    nodes, edges = seed_graph(graph, corpus)

    assert nodes == 23
    assert edges == 18
    assert graph.node_count == 23
    assert graph.edge_count == 18


def test_eval_passes_all_twenty_questions(graph):
    seed_graph(graph, load_corpus())
    name, cases = load_questions()

    report = run_eval(graph, cases, name=name)

    assert report.total == 20
    assert report.ok
    assert report.pass_rate == 1.0
    assert report.failures() == ()


def test_eval_report_serializes_to_dict(graph):
    seed_graph(graph, load_corpus())
    _, cases = load_questions()

    payload = run_eval(graph, cases, name="test").to_dict()

    assert payload["total"] == 20
    assert payload["failed"] == 0
    assert payload["cases"][0]["passed"] is True
    assert "construction_id" in payload["cases"][0]


def test_eval_detects_missing_expected_word(graph):
    seed_graph(graph, load_corpus())
    case = EvalCase(id="bad", question="Что такое трава?", contains=("квазар",))

    report = run_eval(graph, [case], name="bad")

    assert not report.ok
    assert any("квазар" in failure for failure in report.failures()[0].failures)


def test_eval_detects_wrong_intent(graph):
    seed_graph(graph, load_corpus())
    case = EvalCase(
        id="bad", question="Что такое трава?", intent="признать_незнание"
    )

    report = run_eval(graph, [case], name="bad")

    assert not report.ok
    assert "намерение" in report.failures()[0].failures[0]


def test_eval_avoids_repeating_answer(graph):
    seed_graph(graph, load_corpus())
    cases = [
        EvalCase(id="a", question="Что такое трава?"),
        EvalCase(id="b", question="Что такое трава?"),
    ]

    report = run_eval(graph, cases, name="repeat")

    assert report.passed_count == 2
    assert report.results[0].response != report.results[1].response


def test_check_turn_flags_repeated_response(graph):
    from griga.dialogue import Dialogue
    from griga.evaluation.runner import _check_turn

    seed_graph(graph, load_corpus())
    dialogue = Dialogue(graph, learning=False)
    turn = dialogue.turn("Что такое трава?")
    case = EvalCase(id="a", question="Что такое трава?")

    failures = _check_turn(case, turn, turn.response, clamp=1.0)

    assert any("повторяет" in failure for failure in failures)


def test_questions_loader_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(
        '{"cases": ['
        '{"id": "a", "question": "Что такое трава?"},'
        '{"id": "a", "question": "Что такое вода?"}'
        "]}",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate"):
        load_questions(path)


def test_questions_loader_rejects_missing_question(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(
        '{"cases": [{"id": "a"}]}', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="question"):
        load_questions(path)


def test_corpus_loader_rejects_empty_file(tmp_path):
    path = tmp_path / "corpus.txt"
    path.write_text("\n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        load_corpus(path)

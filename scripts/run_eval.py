"""Eval-прогон v0.1: корпус → граф → 20 вопросов (ADR-015).

Работает в памяти процесса и не трогает PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import sys

from griga.evaluation import load_corpus, load_questions, run_eval, seed_graph
from griga.graph.graph import KnowledgeGraph


class MemoryStorage:
    """Минимальное хранилище для eval-прогона."""

    def __init__(self) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="Eval-прогон: 20 базовых вопросов по загруженному тексту.",
    )
    parser.add_argument("--corpus", default=None, help="путь к тексту корпуса")
    parser.add_argument("--questions", default=None, help="путь к JSON с вопросами")
    parser.add_argument(
        "--json",
        action="store_true",
        help="напечатать отчёт в JSON вместо таблицы",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    name, cases = load_questions(args.questions)
    corpus = load_corpus(args.corpus)

    graph = KnowledgeGraph(MemoryStorage())
    nodes, edges = seed_graph(graph, corpus)
    report = run_eval(graph, cases, name=name)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Eval: {report.name}")
        print(f"Корпус: {len(corpus)} фактов, узлов {nodes}, рёбер {edges}\n")
        for result in report.results:
            mark = "PASS" if result.passed else "FAIL"
            print(
                f"  [{mark}] {result.case.id} {result.case.question} "
                f"→ {result.response}"
            )
            for failure in result.failures:
                print(f"         ! {failure}")
        print(
            f"\nИтог: {report.passed_count}/{report.total} "
            f"({report.pass_rate:.0%})"
        )

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

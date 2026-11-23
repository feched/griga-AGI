"""Демонстрация Perception: текст → узлы/утверждения/маркеры.

Без флага ``--write`` только показывает разбор. С ``--write`` пишет факты
в PostgreSQL и запускает волну активации от первого субъекта.
"""

from __future__ import annotations

import sys

from griga.config import load_config
from griga.env import load_dotenv
from griga.graph.graph import KnowledgeGraph
from griga.perception import PerceptionParser, apply_parse
from griga.storage.postgres import PostgresStorage
from griga.thinking.spreader import Spreader


DEFAULT_TEXT = (
    "Трава — это растение. Трава зелёная. Трава растёт на газоне. "
    "Трава не синяя. Привет!"
)


def main(argv: list[str]) -> int:
    write = "--write" in argv
    text_parts = [part for part in argv if part != "--write"]
    text = " ".join(text_parts) or DEFAULT_TEXT

    parser = PerceptionParser()
    result = parser.parse(text)

    print(f"text: {result.text}")
    print(
        "markers: "
        f"act={result.markers.speech_act.value}, "
        f"question={result.markers.is_question}, "
        f"negation={result.markers.has_negation}, "
        f"emotion={result.markers.emotion}, "
        f"attribution={result.markers.attribution}, "
        f"modality={result.markers.modality}"
    )

    print("nodes:")
    for mention in result.nodes:
        print(f"  [{mention.lemma}] ({mention.node_type.value}, {mention.pos})")

    print("statements:")
    for statement in result.statements:
        fact = "fact" if statement.is_fact else "skipped"
        print(
            f"  [{statement.subject.lemma}] "
            f"--{statement.relation.value}({statement.label})--> "
            f"[{statement.object.lemma}]  {statement.polarity.value}, {fact}"
        )

    if not write:
        print("\n(dry-run; добавь --write, чтобы сохранить факты в PostgreSQL)")
        return 0

    load_dotenv()
    config = load_config()
    with PostgresStorage() as storage:
        storage.init_schema()
        graph = KnowledgeGraph(storage)
        applied = apply_parse(result, graph)
        print(
            f"\nDB: +{applied.node_count} nodes, "
            f"+{applied.edge_count} edges, "
            f"skipped {applied.skipped_statements}"
        )

        facts = result.facts()
        if facts:
            subject = graph.find_node(
                facts[0].subject.lemma, facts[0].subject.node_type
            )
            if subject is not None:
                memory = Spreader(graph, config).activate([subject])
                print("working memory:")
                for item in memory:
                    print(f"  {item.name}: {item.activation}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

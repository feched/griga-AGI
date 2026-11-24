import os

import pytest

from griga.env import load_dotenv
from griga.graph.edge import Edge
from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node, NodeType
from griga.graph.relations import RelationType
from griga.storage.postgres import PostgresStorage


@pytest.fixture()
def storage():
    load_dotenv()
    dsn = os.environ.get("GRIGA_TEST_DATABASE_URL") or os.environ.get(
        "GRIGA_DATABASE_URL"
    )
    if not dsn:
        pytest.skip("GRIGA_TEST_DATABASE_URL / GRIGA_DATABASE_URL is not set")

    try:
        db = PostgresStorage(dsn)
    except Exception as exc:  # noqa: BLE001 - tests must skip on no DB
        pytest.skip(f"PostgreSQL is not available: {exc}")

    db.init_schema()
    db.truncate_all()
    try:
        yield db
    finally:
        db.truncate_all()
        db.close()


def test_roundtrip_trava_is_a_rastenie(storage):
    graph = KnowledgeGraph(storage)

    grass = graph.add_node(Node(name="Трава"))
    plant = graph.add_node(Node(name="Растение"))
    edge = graph.add_edge(
        Edge(
            source_id=grass.id,
            target_id=plant.id,
            relation_type=RelationType.IS_A,
            weight=0.7,
        )
    )

    assert graph.node_count == 2
    assert graph.edge_count == 1
    assert graph.get_out_edges(grass.id)[0].id == edge.id

    # Новый KnowledgeGraph читает уже сохранённое из PostgreSQL.
    reloaded = KnowledgeGraph(storage)

    assert reloaded.node_count == 2
    assert reloaded.edge_count == 1

    reloaded_grass = reloaded.find_node("Трава", NodeType.CONCEPT)
    reloaded_plant = reloaded.find_node("Растение", NodeType.CONCEPT)
    assert reloaded_grass is not None
    assert reloaded_plant is not None

    reloaded_edge = reloaded.find_edge(
        reloaded_grass.id, reloaded_plant.id, RelationType.IS_A
    )
    assert reloaded_edge is not None
    assert reloaded_edge.weight == pytest.approx(0.7)


def test_same_node_is_not_duplicated(storage):
    graph = KnowledgeGraph(storage)

    first = graph.add_node(Node(name="Трава"))
    second = graph.add_node(Node(name="Трава"))

    assert first.id == second.id
    assert graph.node_count == 1
    assert len(storage.load_all_nodes()) == 1


def test_owner_isolation_on_load(storage):
    graph = KnowledgeGraph(storage)
    user_id = storage.save_user("11111111-1111-1111-1111-111111111111", "Саша")

    global_node = graph.add_node(Node(name="Трава"))
    personal_node = graph.add_node(
        Node(name="Любит кофе", node_type=NodeType.PROPERTY, owner_id=user_id)
    )
    graph.add_edge(
        Edge(
            source_id=personal_node.id,
            target_id=global_node.id,
            relation_type=RelationType.RELATED_TO,
            owner_id=user_id,
        )
    )

    visible = storage.load_all_nodes(owner_id=user_id)
    only_personal = storage.load_all_nodes(owner_id=user_id, include_global=False)

    assert {node.name for node in visible} == {"Трава", "Любит кофе"}
    assert {node.name for node in only_personal} == {"Любит кофе"}

    visible_edges = storage.load_all_edges(owner_id=user_id)
    assert len(visible_edges) == 1
    assert visible_edges[0].owner_id == user_id


def test_audit_log_records_creates(storage):
    graph = KnowledgeGraph(storage)

    grass = graph.add_node(Node(name="Трава"))
    plant = graph.add_node(Node(name="Растение"))
    edge = graph.add_edge(
        Edge(
            source_id=grass.id,
            target_id=plant.id,
            relation_type=RelationType.IS_A,
            weight=0.7,
        )
    )

    events = storage.load_events()

    assert [event["action"] for event in events] == [
        "create",
        "create",
        "create",
    ]
    assert events[0]["entity_type"] == "edge"
    assert events[0]["entity_id"] == edge.id
    assert events[0]["after"]["relation_type"] == RelationType.IS_A.value
    assert events[1]["entity_id"] == plant.id
    assert events[2]["entity_id"] == grass.id


def test_audit_log_records_weight_updates(storage):
    graph = KnowledgeGraph(storage)
    grass = graph.add_node(Node(name="Трава"))
    plant = graph.add_node(Node(name="Растение"))
    edge = graph.add_edge(
        Edge(
            source_id=grass.id,
            target_id=plant.id,
            relation_type=RelationType.IS_A,
            weight=0.5,
        )
    )

    graph.update_edge_weight(edge, 0.8)

    events = storage.load_events()
    update = events[0]

    assert update["action"] == "update_weight"
    assert update["before"]["weight"] == pytest.approx(0.5)
    assert update["after"]["weight"] == pytest.approx(0.8)


def test_audit_log_keeps_source_text(storage):
    from griga.perception import PerceptionParser, apply_parse

    graph = KnowledgeGraph(storage)
    apply_parse(PerceptionParser().parse("Трава — это растение."), graph)

    events = [
        event for event in storage.load_events() if event["action"] == "create"
    ]

    edge_event = next(
        event for event in events if event["entity_type"] == "edge"
    )
    assert edge_event["source"] == "Трава — это растение."


def test_audit_log_is_cleared_with_truncate(storage):
    graph = KnowledgeGraph(storage)
    graph.add_node(Node(name="Трава"))
    assert storage.load_events()

    storage.truncate_all()

    assert storage.load_events() == []


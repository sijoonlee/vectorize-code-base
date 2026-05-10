from codebase_search.graph.base import normalize_edge
from codebase_search.graph.kuzu_store import KuzuStore


def test_normalize_edge_defaults_metadata() -> None:
    edge = normalize_edge({"source": "a", "target": "b", "relation": "contains"})

    assert edge == {
        "source": "a",
        "target": "b",
        "relation": "contains",
        "confidence": 1.0,
        "edge_source": "",
        "details": "",
    }


def test_kuzu_store_persists_edge_metadata(tmp_path) -> None:
    store = KuzuStore(tmp_path / "graph")
    store.insert_nodes([
        {
            "id": "file_a",
            "label": "a.py",
            "entity_type": "file",
            "file_path": "a.py",
            "source_location": "L1",
        },
        {
            "id": "fn_b",
            "label": "b",
            "entity_type": "function",
            "file_path": "a.py",
            "source_location": "L3",
        },
    ])
    store.insert_edges([
        {
            "source": "file_a",
            "target": "fn_b",
            "relation": "contains",
            "confidence": 0.9,
            "edge_source": "ast_function_declaration",
            "details": "direct declaration",
        }
    ])

    rows = store.query(
        "MATCH (a:Entity)-[r:RELATES]->(b:Entity) "
        "RETURN a.id AS source, b.id AS target, r.relation AS relation, "
        "r.confidence AS confidence, r.source AS edge_source, r.details AS details"
    )
    store.close()

    assert rows == [
        {
            "source": "file_a",
            "target": "fn_b",
            "relation": "contains",
            "confidence": 0.9,
            "edge_source": "ast_function_declaration",
            "details": "direct declaration",
        }
    ]


def test_kuzu_store_preserves_legacy_edge_insert_defaults(tmp_path) -> None:
    store = KuzuStore(tmp_path / "graph")
    store.insert_nodes([
        {
            "id": "file_a",
            "label": "a.py",
            "entity_type": "file",
            "file_path": "a.py",
            "source_location": "L1",
        },
        {
            "id": "fn_b",
            "label": "b",
            "entity_type": "function",
            "file_path": "a.py",
            "source_location": "L3",
        },
    ])
    store.insert_edges([{"source": "file_a", "target": "fn_b", "relation": "contains"}])

    rows = store.query(
        "MATCH (a:Entity)-[r:RELATES]->(b:Entity) "
        "RETURN a.id AS source, b.id AS target, r.relation AS relation, "
        "r.confidence AS confidence, r.source AS edge_source, r.details AS details"
    )
    store.close()

    assert rows == [
        {
            "source": "file_a",
            "target": "fn_b",
            "relation": "contains",
            "confidence": 1.0,
            "edge_source": "",
            "details": "",
        }
    ]

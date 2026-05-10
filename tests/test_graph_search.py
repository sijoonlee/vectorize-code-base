from codebase_search.graph.kuzu_store import KuzuStore
from codebase_search.graph_search import _fetch_descendants, _fetch_root_ancestor


def test_graph_search_helpers_include_edge_metadata(tmp_path) -> None:
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
            "id": "fn_main",
            "label": "main",
            "entity_type": "function",
            "file_path": "a.py",
            "source_location": "L3",
        },
    ])
    store.insert_edges([
        {
            "source": "file_a",
            "target": "fn_main",
            "relation": "contains",
            "confidence": 1.0,
            "edge_source": "ast_function_definition",
        }
    ])

    descendants = _fetch_descendants(store, "file_a", depth=1)
    root = _fetch_root_ancestor(store, "fn_main")
    store.close()

    assert descendants == [
        {
            "id": "fn_main",
            "label": "main",
            "entity_type": "function",
            "file_path": "a.py",
            "source_location": "L3",
            "relation": "contains",
            "confidence": 1.0,
            "edge_source": "ast_function_definition",
            "details": "",
            "depth": 1,
        }
    ]
    assert root == {
        "id": "file_a",
        "label": "a.py",
        "entity_type": "file",
        "file_path": "a.py",
        "source_location": "L1",
        "relation": "contains",
        "confidence": 1.0,
        "edge_source": "ast_function_definition",
        "details": "",
    }


def test_graph_query_can_match_file_path_segments(tmp_path) -> None:
    store = KuzuStore(tmp_path / "graph")
    store.insert_nodes([
        {
            "id": "auth_service_index_ts",
            "label": "index.ts",
            "entity_type": "file",
            "file_path": "apps/auth-service/src/index.ts",
            "source_location": "L1",
        }
    ])

    rows = store.query(
        "MATCH (n:Entity) WHERE (lower(n.label) CONTAINS lower($q) "
        "OR lower(n.file_path) CONTAINS lower($q)) "
        "RETURN n.id AS id",
        {"q": "auth-service"},
    )
    store.close()

    assert rows == [{"id": "auth_service_index_ts"}]

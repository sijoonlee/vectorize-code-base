from codebase_search.graph.kuzu_store import KuzuStore
from codebase_search.search import _fetch_graph_context, _normalize_result


def test_normalize_result_keeps_search_metadata() -> None:
    result = _normalize_result(
        {
            "id": "abc",
            "file_path": "app/users.py",
            "language": "python",
            "symbol": "UserValidator",
            "entity_type": "class",
            "start_line": 1,
            "end_line": 3,
            "code": "class UserValidator:\n    pass",
            "_distance": 0.25,
        },
        graph_store=None,
    )

    assert result == {
        "id": "abc",
        "file_path": "app/users.py",
        "language": "python",
        "symbol": "UserValidator",
        "entity_type": "class",
        "start_line": 1,
        "end_line": 3,
        "code": "class UserValidator:\n    pass",
        "distance": 0.25,
        "graph_context": None,
    }


def test_fetch_graph_context_includes_edge_metadata(tmp_path) -> None:
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
        {
            "id": "fn_helper",
            "label": "helper",
            "entity_type": "function",
            "file_path": "a.py",
            "source_location": "L1",
        },
    ])
    store.insert_edges([
        {
            "source": "file_a",
            "target": "fn_main",
            "relation": "contains",
            "confidence": 1.0,
            "edge_source": "ast_function_definition",
        },
        {
            "source": "fn_main",
            "target": "fn_helper",
            "relation": "calls",
            "confidence": 0.9,
            "edge_source": "ast_direct_identifier_call",
            "details": "helper",
        },
    ])

    context = _fetch_graph_context(store, "main", "a.py")
    store.close()

    assert context == {
        "file_path": "a.py",
        "parents": [
            {
                "id": "file_a",
                "label": "a.py",
                "entity_type": "file",
                "source_location": "L1",
                "relation": "contains",
                "confidence": 1.0,
                "edge_source": "ast_function_definition",
                "details": "",
            }
        ],
        "children": [
            {
                "id": "fn_helper",
                "label": "helper",
                "entity_type": "function",
                "source_location": "L1",
                "relation": "calls",
                "confidence": 0.9,
                "edge_source": "ast_direct_identifier_call",
                "details": "helper",
            }
        ],
    }

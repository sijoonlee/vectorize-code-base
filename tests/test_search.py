from codebase_search.search import _normalize_result


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

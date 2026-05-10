import json

from codebase_search import file_changes
from codebase_search.file_changes import process_pending_file_changes, report_file_change

def test_report_created_records_stale_state(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    db_root = tmp_path / "db"
    monkeypatch.setattr(
        file_changes,
        "derive_db_paths",
        lambda repo_path: (db_root / "vector", db_root / "graph"),
    )

    result = report_file_change(repo, "src/new.py", "created")

    state = json.loads((db_root / "state" / "file_changes.json").read_text(encoding="utf-8"))
    assert result["file_path"] == "src/new.py"
    assert result["status"] == "stale"
    assert state["src/new.py"]["event"] == "created"
    assert state["src/new.py"]["status"] == "stale"
    assert "reported_at" in state["src/new.py"]


def test_latest_removed_event_wins_without_existing_index_records(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    db_root = tmp_path / "db"
    monkeypatch.setattr(
        file_changes,
        "derive_db_paths",
        lambda repo_path: (db_root / "vector", db_root / "graph"),
    )

    report_file_change(repo, "src/temp.py", "created")
    result = report_file_change(repo, "src/temp.py", "removed")

    state = json.loads((db_root / "state" / "file_changes.json").read_text(encoding="utf-8"))
    assert result["status"] == "removed"
    assert result["vector_deleted"] is False
    assert result["graph_deleted"] is False
    assert state["src/temp.py"]["event"] == "removed"
    assert state["src/temp.py"]["status"] == "removed"


def test_report_rejects_paths_outside_repo(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        file_changes,
        "derive_db_paths",
        lambda repo_path: (tmp_path / "db" / "vector", tmp_path / "db" / "graph"),
    )

    outside = tmp_path / "outside.py"

    try:
        report_file_change(repo, outside, "updated")
    except ValueError as error:
        assert "is not inside repo" in str(error)
    else:
        raise AssertionError("Expected outside repo path to be rejected")


def test_process_pending_removed_change_clears_state_without_existing_records(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    db_root = tmp_path / "db"
    monkeypatch.setattr(
        file_changes,
        "derive_db_paths",
        lambda repo_path: (db_root / "vector", db_root / "graph"),
    )
    report_file_change(repo, "src/removed.py", "removed")

    result = process_pending_file_changes(repo)

    assert result["processed"] == [
        {
            "file_path": "src/removed.py",
            "event": "removed",
            "vector_deleted": False,
            "graph_deleted": False,
        }
    ]
    assert not (db_root / "state" / "file_changes.json").exists()


def test_process_pending_created_change_refreshes_file_and_clears_state(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    db_root = tmp_path / "db"
    monkeypatch.setattr(
        file_changes,
        "derive_db_paths",
        lambda repo_path: (db_root / "vector", db_root / "graph"),
    )
    refreshed = []
    monkeypatch.setattr(
        file_changes,
        "_refresh_file",
        lambda repo_path, db_path, graph_db_path, rel_path, model: refreshed.append(rel_path)
        or {"status": "refreshed", "chunks": 1},
    )
    report_file_change(repo, "src/created.py", "created")

    result = process_pending_file_changes(repo)

    assert result["processed"] == [
        {
            "file_path": "src/created.py",
            "event": "created",
            "status": "refreshed",
            "chunks": 1,
        }
    ]
    assert refreshed == ["src/created.py"]
    assert not (db_root / "state" / "file_changes.json").exists()

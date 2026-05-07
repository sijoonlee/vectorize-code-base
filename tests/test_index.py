from codebase_search.index import _log


def test_log_prefixes_index_messages(capsys) -> None:
    _log("Embedding batch 1/2 (16 chunks)...")

    assert capsys.readouterr().out == "[index] Embedding batch 1/2 (16 chunks)...\n"

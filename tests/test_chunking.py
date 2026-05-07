from pathlib import Path

from codebase_search.chunking import chunk_file, iter_source_files


FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "sample_repo"


class FakeSplitter:
    def __init__(self, splits: list[str]) -> None:
        self.splits = splits

    def split_text(self, text: str) -> list[str]:
        return self.splits


def test_iter_source_files_skips_unsupported_files() -> None:
    files = {path.relative_to(FIXTURE_REPO).as_posix() for path in iter_source_files(FIXTURE_REPO)}

    assert files == {
        "app/users.py",
        "src/auth.js",
        "src/rates.ts",
    }


def test_python_chunking_extracts_symbols() -> None:
    chunks = chunk_file(FIXTURE_REPO / "app" / "users.py", FIXTURE_REPO)

    assert [(chunk.symbol, chunk.start_line) for chunk in chunks] == [
        ("UserValidator", 1),
        ("normalize_user_name", 6),
    ]
    assert chunks[0].language == "python"
    assert chunks[0].file_path == "app/users.py"


def test_typescript_chunking_extracts_symbols() -> None:
    chunks = chunk_file(FIXTURE_REPO / "src" / "rates.ts", FIXTURE_REPO)

    assert [(chunk.symbol, chunk.start_line) for chunk in chunks] == [
        ("validateMortgageRate", 1),
        ("RateFormatter", 5),
    ]
    assert chunks[1].end_line == 9


def test_javascript_chunking_extracts_arrow_function() -> None:
    chunks = chunk_file(FIXTURE_REPO / "src" / "auth.js", FIXTURE_REPO)

    assert len(chunks) == 1
    assert chunks[0].symbol == "requireAuth"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 7


def test_fallback_chunking_uses_langchain_text_splitter(tmp_path, monkeypatch) -> None:
    source = tmp_path / "constants.py"
    source.write_text("alpha = 1\nbeta = 2\n", encoding="utf-8")

    monkeypatch.setattr(
        "codebase_search.chunking._text_splitter_for_suffix",
        lambda suffix: FakeSplitter(["alpha = 1", "beta = 2"]),
    )

    chunks = chunk_file(source, tmp_path)

    assert [(chunk.symbol, chunk.start_line, chunk.end_line, chunk.code) for chunk in chunks] == [
        ("", 1, 1, "alpha = 1"),
        ("", 2, 2, "beta = 2"),
    ]


def test_symbol_chunking_uses_langchain_text_splitter(tmp_path, monkeypatch) -> None:
    source = tmp_path / "model.py"
    source.write_text("class Model:\n    first = 1\n    second = 2\n", encoding="utf-8")

    monkeypatch.setattr(
        "codebase_search.chunking._text_splitter_for_suffix",
        lambda suffix: FakeSplitter(["class Model:\n    first = 1", "second = 2"]),
    )

    chunks = chunk_file(source, tmp_path)

    assert [(chunk.symbol, chunk.start_line, chunk.end_line, chunk.code) for chunk in chunks] == [
        ("Model", 1, 2, "class Model:\n    first = 1"),
        ("Model", 3, 3, "second = 2"),
    ]

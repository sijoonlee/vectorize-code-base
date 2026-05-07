from __future__ import annotations

import hashlib
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from langchain_text_splitters import Language as SplitterLanguage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tree_sitter import Language, Node, Parser
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript


SOURCE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
}

DEFAULT_CHUNK_SIZE = 2_000
DEFAULT_CHUNK_OVERLAP = 200


@dataclass(frozen=True)
class CodeChunk:
    id: str
    file_path: str
    language: str
    symbol: str
    entity_type: str  # "class", "function", or ""
    start_line: int
    end_line: int
    code: str

    def to_record(self, vector: list[float]) -> dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "language": self.language,
            "symbol": self.symbol,
            "entity_type": self.entity_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "vector": vector,
        }


def iter_source_files(repo: Path) -> Iterable[Path]:
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            yield path


def language_for_path(path: Path) -> str | None:
    return SOURCE_EXTENSIONS.get(path.suffix.lower())


def chunk_file(path: Path, repo: Path) -> list[CodeChunk]:
    language = language_for_path(path)
    if language is None:
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return []

    rel_path = path.relative_to(repo).as_posix()
    line_starts = _line_start_offsets(text)
    chunks = _chunk_tree_sitter(text, path.suffix.lower(), lines, line_starts, rel_path, language)
    return chunks or _split_code_text(text, path.suffix.lower(), lines, line_starts, rel_path, language, "", "")


def _chunk_tree_sitter(
    text: str,
    suffix: str,
    lines: list[str],
    line_starts: list[int],
    rel_path: str,
    language: str,
) -> list[CodeChunk]:
    parser = _parser_for_suffix(suffix)
    if parser is None:
        return []

    tree = parser.parse(text.encode())
    if tree.root_node.has_error:
        return []

    occupied_until = 0
    chunks: list[CodeChunk] = []
    for node in tree.root_node.named_children:
        if node.start_point.row + 1 <= occupied_until:
            continue

        symbol_node = _symbol_node_for_top_level_node(node)
        if symbol_node is None:
            continue

        name_node = symbol_node.child_by_field_name("name")
        if name_node is None or name_node.text is None:
            continue

        symbol = name_node.text.decode()
        entity_type = _entity_type_for_node(symbol_node)
        chunks.extend(
            _split_code_text(
                text,
                suffix,
                lines,
                line_starts,
                rel_path,
                language,
                symbol,
                entity_type,
                start_offset=node.start_byte,
                end_offset=node.end_byte,
            )
        )
        occupied_until = node.end_point.row + 1
    return chunks


@lru_cache(maxsize=None)
def _parser_for_suffix(suffix: str) -> Parser | None:
    language = _tree_sitter_language_for_suffix(suffix)
    if language is None:
        return None
    return Parser(language)


def _tree_sitter_language_for_suffix(suffix: str) -> Language | None:
    if suffix == ".py":
        return Language(tree_sitter_python.language())
    if suffix in {".js", ".jsx"}:
        return Language(tree_sitter_javascript.language())
    if suffix == ".ts":
        return Language(tree_sitter_typescript.language_typescript())
    if suffix == ".tsx":
        return Language(tree_sitter_typescript.language_tsx())
    return None


def _entity_type_for_node(node: Node) -> str:
    if node.type in {"class_declaration", "class_definition"}:
        return "class"
    if node.type in {
        "function_declaration",
        "function_definition",
        "generator_function_declaration",
        "variable_declarator",
    }:
        return "function"
    return ""


def _symbol_node_for_top_level_node(node: Node) -> Node | None:
    if node.type == "export_statement":
        declaration = node.child_by_field_name("declaration")
        return _symbol_node_for_top_level_node(declaration) if declaration is not None else None

    if node.type == "decorated_definition":
        definition = node.child_by_field_name("definition")
        return _symbol_node_for_top_level_node(definition) if definition is not None else None

    if node.type in {
        "class_declaration",
        "class_definition",
        "function_declaration",
        "function_definition",
        "generator_function_declaration",
    }:
        return node

    if node.type == "lexical_declaration":
        return _symbol_node_for_variable_function(node)

    return None


def _symbol_node_for_variable_function(node: Node) -> Node | None:
    for child in node.named_children:
        if child.type != "variable_declarator":
            continue

        value = child.child_by_field_name("value")
        if value is None or value.type not in {"arrow_function", "function", "function_expression"}:
            continue
        return child

    return None


def _split_code_text(
    text: str,
    suffix: str,
    lines: list[str],
    line_starts: list[int],
    rel_path: str,
    language: str,
    symbol: str,
    entity_type: str,
    start_offset: int = 0,
    end_offset: int | None = None,
) -> list[CodeChunk]:
    if end_offset is None:
        end_offset = len(text)

    code = text[start_offset:end_offset]
    splits = _text_splitter_for_suffix(suffix).split_text(code)
    chunks: list[CodeChunk] = []
    search_from = start_offset

    for split in splits:
        absolute_start = text.find(split, search_from, end_offset)
        if absolute_start == -1:
            absolute_start = text.find(split, start_offset, end_offset)
        if absolute_start == -1:
            continue

        absolute_end = absolute_start + len(split)
        start_line = _line_number_for_offset(line_starts, absolute_start)
        end_line = _line_number_for_offset(line_starts, max(absolute_start, absolute_end - 1))
        chunks.append(_make_chunk(rel_path, language, symbol, entity_type, start_line, end_line, lines, split))
        search_from = max(absolute_start + 1, absolute_end - DEFAULT_CHUNK_OVERLAP)
    return chunks


@lru_cache(maxsize=None)
def _text_splitter_for_suffix(suffix: str) -> RecursiveCharacterTextSplitter:
    splitter_language = _splitter_language_for_suffix(suffix)
    if splitter_language is None:
        return RecursiveCharacterTextSplitter(
            chunk_size=DEFAULT_CHUNK_SIZE,
            chunk_overlap=DEFAULT_CHUNK_OVERLAP,
        )
    return RecursiveCharacterTextSplitter.from_language(
        language=splitter_language,
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    )


def _splitter_language_for_suffix(suffix: str) -> SplitterLanguage | None:
    if suffix == ".py":
        return SplitterLanguage.PYTHON
    if suffix in {".js", ".jsx"}:
        return SplitterLanguage.JS
    if suffix in {".ts", ".tsx"}:
        return SplitterLanguage.TS
    return None


def _line_start_offsets(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _line_number_for_offset(line_starts: list[int], offset: int) -> int:
    return bisect_right(line_starts, offset)


def _make_chunk(
    rel_path: str,
    language: str,
    symbol: str,
    entity_type: str,
    start_line: int,
    end_line: int,
    lines: list[str],
    code: str | None = None,
) -> CodeChunk:
    if code is None:
        code = "\n".join(lines[start_line - 1 : end_line])
    chunk_id = hashlib.sha256(f"{rel_path}:{symbol}:{start_line}:{end_line}:{code}".encode()).hexdigest()
    return CodeChunk(
        id=chunk_id,
        file_path=rel_path,
        language=language,
        symbol=symbol,
        entity_type=entity_type,
        start_line=start_line,
        end_line=end_line,
        code=code,
    )

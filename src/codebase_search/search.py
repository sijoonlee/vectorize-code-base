from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import lancedb

from codebase_search.embed import DEFAULT_MODEL, embed_text
from codebase_search.index import TABLE_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search an indexed codebase.")
    parser.add_argument("--db", required=True, help="Path to the LanceDB directory.")
    parser.add_argument("--query", required=True, help="Natural language search query.")
    parser.add_argument("--limit", type=int, default=5, help="Number of results to return. Default: 5")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama embedding model. Default: {DEFAULT_MODEL}")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    db_path = Path(args.db).expanduser()

    db = lancedb.connect(db_path)
    if TABLE_NAME not in db.table_names():
        raise SystemExit(f"Table '{TABLE_NAME}' not found in {db_path}. Run index first.")

    table = db.open_table(TABLE_NAME)
    query_vector = embed_text(args.query, model=args.model)
    results = table.search(query_vector).limit(args.limit).to_list()

    normalized = [_normalize_result(result) for result in results]
    if args.json:
        print(json.dumps(normalized, indent=2))
    else:
        _print_results(normalized)


def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": result["id"],
        "file_path": result["file_path"],
        "language": result["language"],
        "symbol": result.get("symbol") or "",
        "start_line": result["start_line"],
        "end_line": result["end_line"],
        "score": result.get("_distance"),
        "code": result["code"],
    }


def _print_results(results: list[dict[str, Any]]) -> None:
    for index, result in enumerate(results, start=1):
        symbol = f" {result['symbol']}" if result["symbol"] else ""
        score = result["score"]
        score_text = f" distance={score:.4f}" if isinstance(score, int | float) else ""
        print(
            f"{index}. {result['file_path']}:{result['start_line']}-{result['end_line']}"
            f"{symbol}{score_text}"
        )
        print(_indent_code(result["code"]))
        print()


def _indent_code(code: str) -> str:
    return "\n".join(f"    {line}" for line in code.splitlines())


if __name__ == "__main__":
    main()

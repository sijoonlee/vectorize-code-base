# Vectorize Code Base

A local CLI prototype for semantic codebase search.

Code is chunked with tree-sitter, then embeddings are loaded through LangChain's Ollama
integration and stored in LanceDB.

## Setup

```bash
uv sync
ollama pull qwen3-embedding:0.6b
```

Ollama must be running locally when indexing or searching.

## Index

```bash
uv run codebase-index --repo /path/to/repo --db ./codebase.lancedb
```

## Search

```bash
uv run codebase-search --db ./codebase.lancedb --query "where is user validation handled"
uv run codebase-search --db ./codebase.lancedb --query "where is user validation handled" --json
```

Compatibility wrappers are also available:

```bash
uv run python index.py --repo /path/to/repo --db ./codebase.lancedb
uv run python search.py --db ./codebase.lancedb --query "..."
```

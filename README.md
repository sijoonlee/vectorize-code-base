# Vectorize Code Base

A local CLI prototype for semantic codebase search.

Code is chunked with tree-sitter, then embeddings are loaded through LangChain's Ollama
integration and stored in LanceDB. Optionally, a graph DB (Kuzu or Neo4j) can be populated
alongside to store entity relationships for graph-aware queries.

## Setup

```bash
uv sync
ollama pull qwen3-embedding:0.6b
```

Ollama must be running locally when indexing or searching.

## Environment variables

Set these to avoid repeating paths on every command:

| Variable | Flag | Description |
|---|---|---|
| `CODEBASE_REPO` | `--repo` | Path to the repo root |
| `CODEBASE_DB` | `--db` | Path to the LanceDB directory |
| `CODEBASE_GRAPH_DB` | `--graph-db` | Path to the graph DB directory |
| `CODEBASE_GRAPH_BACKEND` | `--graph-backend` | `kuzu` (default) or `neo4j` |

```bash
export CODEBASE_REPO=/path/to/repo
export CODEBASE_DB=./codebase.lancedb
export CODEBASE_GRAPH_DB=./codebase.kuzu
```

CLI flags take precedence over environment variables when both are provided.

## Commands

### Index

```bash
uv run codebase-index
# or without env vars:
uv run codebase-index --repo /path/to/repo --db ./codebase.lancedb
```

Each chunk is embedded with metadata (entity type, symbol name, file path) prepended to the
code text, so queries like "how is profile created?" match on both name and implementation.

Unchanged files are skipped on re-runs using a SHA256 content cache stored at
`./codebase.lancedb/cache/`.

With graph DB (optional):

```bash
uv run codebase-index --graph-db ./codebase.kuzu
```

This populates a Kuzu graph DB alongside LanceDB with nodes (`file`, `class`, `function`,
`method`) and `contains` edges representing the code structure.

To use Neo4j instead (requires `pip install codebase-search[neo4j]` and a running Neo4j server):

```bash
uv run codebase-index --graph-db bolt://localhost:7687 --graph-backend neo4j
```

### Search

Vector search with optional graph context enrichment:

```bash
uv run codebase-search --query "how is profile created?"
uv run codebase-search --query "how is profile created?" --json
```

When `CODEBASE_GRAPH_DB` is set (or `--graph-db` is passed), each result is enriched with
its parent entity from the graph. Example output:

```
1. src/services/user.py:10-25  createProfile  distance=0.1234
   [class UserService  src/services/user.py:L1]
    def createProfile(user_id, data):
        ...
```

### Graph traverse

Search the graph by entity name and explore its structure:

```bash
uv run codebase-graph-traverse --query "UserService"
uv run codebase-graph-traverse --query "createProfile" --json
```

Example output:

```
class  UserService  src/services/user.py:L1
  parent: file user.py  L1
  children (3):
    method     __init__          L2
    method     createProfile     L10
    method     deleteProfile     L40
```

The query is a case-insensitive partial match against entity labels.

### Remove a deleted file

When a file is deleted from the repo, remove its records from both stores:

```bash
uv run codebase-remove src/services/user.py
# or without env vars:
uv run codebase-remove --repo /path/to/repo --db ./codebase.lancedb src/services/user.py
```

With graph DB:

```bash
uv run codebase-remove --graph-db ./codebase.kuzu src/services/user.py
```

## Chunk metadata

Each LanceDB record stores:

| Field | Description |
|---|---|
| `id` | SHA256 of file path + symbol + line range + code |
| `file_path` | Repo-relative path |
| `language` | `python`, `javascript`, `typescript` |
| `symbol` | Function or class name (`""` for fallback chunks) |
| `entity_type` | `class`, `function`, or `""` |
| `start_line` | Start line (1-indexed) |
| `end_line` | End line (1-indexed) |
| `code` | Raw source text |
| `vector` | Embedding vector |

## Graph schema

When `--graph-db` is provided, Kuzu/Neo4j stores:

**Nodes (`Entity`):** `id`, `label`, `entity_type` (`file`/`class`/`function`/`method`), `file_path`, `source_location`

**Edges (`RELATES`):** `relation` (`contains`)

## Supported languages

Python, JavaScript (`.js`, `.jsx`), TypeScript (`.ts`, `.tsx`)

## Compatibility wrappers

```bash
uv run python index.py --repo /path/to/repo --db ./codebase.lancedb
uv run python search.py --db ./codebase.lancedb --query "..."
```

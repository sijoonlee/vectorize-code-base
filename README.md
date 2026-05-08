# Vectorize Code Base

A local CLI prototype for semantic codebase search.

Code is chunked with tree-sitter, then embeddings are loaded through LangChain's Ollama
integration and stored in LanceDB. A Kuzu graph DB is populated alongside to store entity
relationships for graph-aware queries.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) must be installed locally
- [ollama](https://docs.ollama.com/quickstart) must be installed locally

## Setup

```bash
uv sync
ollama pull qwen3-embedding:0.6b
```

Ollama must be running locally when indexing or searching.

## Database layout

All databases are stored inside this project under `db/`:

```
db/
  <repo-name>/
    <branch>/
      vector/    ← LanceDB
      graph/     ← Kuzu
```

If the repo is not a git repository, `<branch>` is `local`.

Example for `jira-issue-solver` on branch `main`:
```
db/jira-issue-solver/main/vector
db/jira-issue-solver/main/graph
```

## Commands

### Index

Index a repo (both vector and graph are always written):

```bash
uv run codebase-index --repo /path/to/repo
```

Unchanged files are skipped on re-runs using a SHA256 content cache stored inside the vector DB directory.

### Search

Vector search with automatic graph context enrichment:

```bash
# from inside the repo directory
uv run codebase-search --query "how is profile created?"

# from anywhere, specifying the repo
uv run codebase-search --repo /path/to/repo --query "how is profile created?"

# restrict to a subdirectory
uv run codebase-search --query "how is profile created?" --scope src/services

# machine-readable output
uv run codebase-search --query "how is profile created?" --json
```

Example output:

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
uv run codebase-remove --repo /path/to/repo src/services/user.py
```

## Environment variables

| Variable | Description |
|---|---|
| `CODEBASE_REPO` | Default repo path for all commands |

## Claude Code MCP integration

This tool can be exposed as an MCP server so Claude Code can call `codebase_search` and
`codebase_graph_traverse` as native tools in any session, including headless `claude -p` mode.

### 1. Index your repo first

```bash
uv run codebase-index --repo /path/to/repo
```

### 2. Register the MCP server globally

```bash
claude mcp add -s user codebase-search \
  -- uv run --directory /path/to/vectorize-code-base codebase-mcp
```

The MCP server automatically detects the target repo via the MCP roots protocol — Claude Code
sends its working directory as a root URI, which the server reads on every tool call. The
current git branch is resolved from that path. No environment variables or explicit `repo`
argument needed in normal use.

If auto-detection fails (e.g. the client doesn't advertise roots), pass the repo path explicitly:

```
codebase_search(query="...", repo="/absolute/path/to/repo")
```

### 3. (Optional) Verify in Claude Code

Run `/mcp` inside any Claude Code session to confirm `codebase-search` is listed as connected.

### Available MCP tools

| Tool | Description |
|---|---|
| `codebase_index` | Index a repo (vector + graph). Repo detected via MCP roots; override with `repo` |
| `codebase_search` | Vector similarity search — returns ranked code chunks for a query. Optional `scope` to restrict to a subdirectory, `repo` to override auto-detection |
| `codebase_graph_traverse` | Graph traversal — explore parent/child relationships for a named entity. Optional `repo` to override auto-detection |

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

**Nodes (`Entity`):** `id`, `label`, `entity_type` (`file`/`class`/`function`/`method`), `file_path`, `source_location`

**Edges (`RELATES`):** `relation` (`contains`)

## Supported languages

Python, JavaScript (`.js`, `.jsx`), TypeScript (`.ts`, `.tsx`)

## Limitations

- **Indexing always does a full reset** — both the vector store and graph DB are wiped and rebuilt on every `codebase-index` run. Only the embedding step is cached (unchanged files skip re-embedding), but all records are rewritten to disk regardless.

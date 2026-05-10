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

### Report a changed file

Record that a file was created, updated, or removed without eagerly rebuilding it:

```bash
uv run codebase-file-change --repo /path/to/repo --event updated src/services/user.py
uv run codebase-file-change --repo /path/to/repo --event created src/services/new_user.py
uv run codebase-file-change --repo /path/to/repo --event removed src/services/old_user.py
```

Created and updated files are marked stale for later refresh. Removed files are cleaned
from vector and graph stores immediately, then recorded as removed.

## Lazy refresh

File-change reporting does not eagerly rebuild embeddings or graph edges. It records
pending work under the repo/branch DB directory:

```text
db/<repo-name>/<branch>/state/file_changes.json
```

The `<branch>` segment is the current git branch. If the repo is not a git repository, the
branch segment is `local`. Query commands derive this path from the repo's current branch,
so pending changes recorded for another branch are not processed.

Before `codebase-search`, `codebase-graph-traverse`, or their MCP equivalents run a query,
they process all pending file changes for the current branch:

- `created`: index that file into vector and graph stores, then clear the pending state.
- `updated`: delete old records, re-index that file, then clear the pending state.
- `removed`: delete vector chunks and graph nodes idempotently, then clear the pending
  state.

This means changed files are refreshed at query time, not when the file-change event is
reported. Removed files should not appear in query results because removals are cleaned up
both when reported and again before the next query if still pending.

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

The graph uses one physical Kuzu node table and one physical relationship table:

- Node table: `Entity`
- Relationship table: `RELATES`

Logical node and edge meaning is stored in properties.

### Nodes

Each `Entity` node represents a file or symbol.

| Field | Description |
|---|---|
| `id` | Stable graph id derived from file path and symbol name |
| `label` | Display name, such as `login.ts`, `AuthService`, or `loginUser` |
| `entity_type` | Logical type: `file`, `class`, `function`, or `method` |
| `file_path` | Repo-relative source path |
| `source_location` | Source line marker, such as `L12` |

Examples:

```text
Entity(file: src/auth/login.ts)
Entity(function: loginUser)
Entity(class: AuthService)
Entity(method: login)
```

### Edges

Each `RELATES` edge connects one `Entity` to another `Entity`.

| Field | Description |
|---|---|
| `relation` | Logical edge type |
| `confidence` | Rule-derived confidence score from `0.0` to `1.0` |
| `source` | How the edge was derived, such as `ast_direct_identifier_call` |
| `details` | Optional debug/context detail |

Current relation values:

| Relation | Meaning |
|---|---|
| `contains` | File/class structurally owns a symbol |
| `imports` | File imports another local file |
| `exports` | File explicitly exports a symbol |
| `calls` | Symbol directly calls another resolved symbol |
| `referenced_by` | Reverse edge for an emitted call/reference |
| `member_of` | Method belongs to a class |

Example:

```text
src/auth/login.ts -[contains]-> loginUser
src/auth/login.ts -[imports]-> src/auth/session.ts
src/auth/session.ts -[exports]-> createSession
loginUser -[calls {confidence: 0.85, source: ast_import_alias_call}]-> createSession
createSession -[referenced_by]-> loginUser
login -[member_of]-> AuthService
```

## Supported languages

Python, JavaScript (`.js`, `.jsx`), TypeScript (`.ts`, `.tsx`)

## Limitations

- **Indexing always does a full reset** — both the vector store and graph DB are wiped and rebuilt on every `codebase-index` run. Only the embedding step is cached (unchanged files skip re-embedding), but all records are rewritten to disk regardless.

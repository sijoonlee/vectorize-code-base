# Vector DB for Codebase Search

A standalone local vector DB that indexes a codebase and supports natural language search.

---

## Stack

| Component | Choice | Reason |
|---|---|---|
| Embedding model | `nomic-embed-code` via Ollama | Local, code-specific, zero setup |
| Vector DB | LanceDB | File-based, no server, SQLite-like simplicity |
| Language | Python | Best library support for both |

---

## How It Works

```
Codebase files
     ↓
Chunker (split by function/class)
     ↓
Embedder (nomic-embed-code)
     ↓
LanceDB (stored on disk)
     ↓ (at query time)
Query string → embed → nearest neighbor search → return top-k chunks
```

---

## Chunking Strategy

Split code at **function/class boundaries** rather than fixed token windows.

- Use `tree-sitter` to parse AST and extract functions/classes
- Each chunk stores: `file_path`, `language`, `symbol_name`, `start_line`, `end_line`, `code`
- Fallback: fixed 50-line sliding window with 10-line overlap for non-parseable files

---

## Schema (LanceDB table)

```python
{
  "id":          str,   # sha256(file_path + symbol_name)
  "file_path":   str,   # relative path from repo root
  "language":    str,   # "typescript", "python", etc.
  "symbol":      str,   # function/class name, or "" for fallback chunks
  "start_line":  int,
  "end_line":    int,
  "code":        str,   # raw source text
  "vector":      list[float],  # embedding (768-dim for nomic-embed-code)
}
```

---

## Scripts

### 1. Index a repo
```bash
python index.py --repo /path/to/repo --db ./codebase.lancedb
```
- Walks all source files
- Chunks each file
- Embeds chunks in batches
- Upserts into LanceDB (re-index is idempotent via `id`)

### 2. Search
```bash
python search.py --db ./codebase.lancedb --query "where is rate validation handled"
```
- Embeds the query
- Returns top-5 chunks with file path + line numbers

### 3. CLI wrapper (for AI tool use)
```bash
python search.py --db ./codebase.lancedb --query "$1" --json
```
Returns JSON so any tool (Claude Code, scripts) can parse results.

---

## Re-indexing

- **Full re-index**: drop table, re-run `index.py`
- **Incremental**: check file `mtime` against stored `updated_at`, only re-embed changed files
- Incremental is optional for now — full re-index on a typical repo takes < 1 min

---

## Visualization (Dimension Reduction)

Reduce 768-dim vectors to 2D with UMAP and plot interactively to inspect cluster quality.

### 4. Visualize embeddings
```bash
python visualize.py --db ./codebase.lancedb
```

```python
import lancedb
import umap
import plotly.express as px

db = lancedb.connect("./codebase.lancedb")
df = db.open_table("chunks").to_pandas()

coords = umap.UMAP(n_components=2).fit_transform(df["vector"].tolist())
df["x"], df["y"] = coords[:, 0], coords[:, 1]

fig = px.scatter(
    df, x="x", y="y",
    hover_data=["file_path", "symbol", "start_line"],
    color="language",
    title="Codebase Embeddings (UMAP)",
)
fig.show()
```

**What to look for:**
- Similar functions clustering together = good embedding quality
- A file isolated far from everything = likely a poorly chunked or auto-generated file
- Tight cluster of unrelated files = chunking is too coarse (chunks too large, losing specificity)

**Alternative tools** (no-code / cloud options):
| Tool | Notes |
|---|---|
| **Embedding Projector** (projector.tensorflow.org) | Free browser-based, upload vectors + labels as TSV, supports UMAP/t-SNE/PCA |
| **Nomic Atlas** | Cloud, beautiful UI, free tier, just `pip install nomic` and push your vectors |
| **Renumics Spotlight** | Local GUI, has native LanceDB support — `pip install renumics-spotlight` |

Use the script above for full control; use these tools for quick one-off exploration.

**Algorithm options** (pass via `--algo`):
| Algorithm | Speed | Best for |
|---|---|---|
| `umap` | Fast | Default, preserves local + global structure |
| `tsne` | Slow | Tighter local clusters, good for small repos |
| `pca` | Fastest | Quick sanity check, linear only |

---

## Dependencies

```
pip install lancedb ollama tree-sitter tree-sitter-languages umap-learn plotly pandas
```

Ollama must be running locally with the model pulled:
```bash
ollama pull nomic-embed-code
```

---

## Hybrid Search (Dense + Sparse)

Combining vector search (semantic) with BM25 full-text search (keyword) covers each other's blind spots.

| | Dense (LanceDB) | Sparse (SQLite FTS) |
|---|---|---|
| Good for | "find auth logic" | "find `validateMortgageRate`" |
| Misses | Exact symbols, variable names | Semantic meaning |

Results from both are merged using **RRF (Reciprocal Rank Fusion)** — a simple algorithm that re-ranks by position, no tuning needed.

---

### Pushing code chunks to SQLite FTS

SQLite has a built-in full-text search engine (`fts5`). You write the same chunks from `index.py` into a parallel SQLite table.

**1. Create the FTS table**
```python
import sqlite3

conn = sqlite3.connect("./codebase.db")
conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        id UNINDEXED,
        file_path,
        symbol,
        code,
        tokenize = 'trigram'  -- trigram tokenizer handles code better than default word tokenizer
    )
""")
conn.commit()
```

`tokenize = 'trigram'` is important for code — it matches substrings like `validateRate` inside `validateMortgageRate`, which the default word tokenizer would miss.

**2. Insert chunks during indexing**
```python
# In index.py, after chunking a file:
chunks = chunk_file(filepath)  # your chunker

# Insert into LanceDB (dense)
lance_table.add([{
    "id": chunk.id,
    "file_path": chunk.file_path,
    "symbol": chunk.symbol,
    "code": chunk.code,
    "vector": embed(chunk.code),
    ...
} for chunk in chunks])

# Insert into SQLite FTS (sparse) — same chunks, no vector
conn.executemany(
    "INSERT INTO chunks_fts (id, file_path, symbol, code) VALUES (?, ?, ?, ?)",
    [(c.id, c.file_path, c.symbol, c.code) for c in chunks]
)
conn.commit()
```

Both stores share the same `id`, so you can join results later.

**3. Query SQLite FTS**
```python
def sparse_search(conn, query: str, limit: int = 20) -> list[dict]:
    rows = conn.execute("""
        SELECT id, file_path, symbol, rank
        FROM chunks_fts
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, limit)).fetchall()
    return [{"id": r[0], "file_path": r[1], "symbol": r[2], "score": r[3]} for r in rows]
```

**4. Merge with RRF**
```python
def rrf(dense_results: list, sparse_results: list, k: int = 60) -> list:
    scores: dict[str, float] = {}
    for rank, item in enumerate(dense_results):
        scores[item["id"]] = scores.get(item["id"], 0) + 1 / (k + rank + 1)
    for rank, item in enumerate(sparse_results):
        scores[item["id"]] = scores.get(item["id"], 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

# Usage
dense  = lance_table.search(embed(query)).limit(20).to_list()
sparse = sparse_search(conn, query, limit=20)
final  = rrf(dense, sparse)
```

---

### Option B: Qdrant (hybrid in one place)

If managing two stores feels like too much overhead, Qdrant supports hybrid search natively:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector

client = QdrantClient(":memory:")  # or path="./codebase.qdrant" for local disk

# Qdrant handles both dense + sparse vectors in one upsert
client.upsert(collection_name="chunks", points=[{
    "id": chunk.id,
    "vector": {
        "dense": embed(chunk.code),          # nomic-embed-code output
        "sparse": bm25_encode(chunk.code),   # use `qdrant-sparse-text` or `bm25s` lib
    },
    "payload": {"file_path": chunk.file_path, "symbol": chunk.symbol, ...}
}])
```

Qdrant also has the same API locally and on Qdrant Cloud — so no code changes when you move to cloud.

---

### Which to choose

| | LanceDB + SQLite | Qdrant |
|---|---|---|
| Setup | Zero (files only) | Single binary or Docker |
| Hybrid search | Manual RRF glue code | Built-in |
| Cloud migration | Need to swap to Qdrant anyway | Same client, just change URL |
| Best for | Local prototype | If hybrid search is a priority from the start |

---

## Use Case: AI Agent Code Review via Vector DB

The vector DB doesn't find bugs itself — it gives the AI agent **relevant context it wouldn't otherwise have**. The agent reasons over: *"here's the new code + here's how similar things are done elsewhere in this codebase."*

---

### Flow

```
New code (PR diff or generated patch)
     ↓
Chunk it the same way as the indexed codebase
     ↓
Vector search → find top-k most similar existing chunks
     ↓
AI agent prompt:
  "Here is the new code.
   Here is how similar code looks elsewhere in this codebase.
   What is inconsistent, missing, or potentially wrong?"
     ↓
Report
```

---

### What the agent can catch

| Issue | Example |
|---|---|
| **Inconsistent patterns** | New endpoint skips auth middleware that every other endpoint uses |
| **Missing conventions** | Every DB call in the codebase has a try/catch — this one doesn't |
| **Duplicate logic** | New code reimplements something that already exists 3 files away |
| **Repeated past mistakes** | Similar code was previously patched for a bug; new code has the same shape |
| **Style drift** | New code uses a different error response format than the rest of the codebase |

---

### Example prompt to the agent

```
You are reviewing a code change. Below is the new code, followed by the most similar
existing code found in this codebase via semantic search.

## New code
{new_chunk}

## Similar existing code (retrieved from codebase)
{retrieved_chunks}

Identify anything in the new code that:
1. Deviates from patterns established in the existing code
2. Is missing something the existing code consistently includes
3. Looks like it could introduce a bug based on past patterns
```

---

### What it won't catch

- Bugs with no similar precedent in the codebase
- Type errors, null refs — use TypeScript / static analysis for these
- Security vulnerabilities requiring deep data-flow analysis — use dedicated SAST tools
- Logic errors that require understanding business requirements

---

### Relevance to jira-issue-solver

After the solver generates a patch, this pattern could be applied as a validation step:
1. Chunk the generated patch
2. Search the target repo's vector DB for similar code
3. Ask the agent to validate consistency before the patch is committed

This would catch cases where the solver generates technically correct code that doesn't match how the target codebase does things.

---

## MCP Server: Exposing Vector Search to AI Agents

Wrapping the vector DB as an MCP tool lets any AI agent (Claude Code, jira-issue-solver, etc.) query the codebase with natural language — without reading files blindly.

---

### Why this reduces tokens and time

**Without vector DB:**
- Agent reads many files to find relevant context → burns tokens
- Or misses context entirely → makes worse decisions
- 10-20 `read_file` calls per task is common

**With MCP `search_codebase`:**
- Agent fetches only the relevant chunks on demand
- Sub-100ms retrieval vs multiple file reads
- 5 precise chunks instead of 50 full files in context

The key insight: **more context + fewer tokens** at the same time. Vector search breaks the usual tradeoff between quality and cost.

---

### MCP tool definition

```json
{
  "name": "search_codebase",
  "description": "Search the codebase by natural language. Returns relevant code chunks with file paths and line numbers.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Natural language description of what you are looking for"
      },
      "limit": {
        "type": "number",
        "description": "Number of results to return (default 5)"
      }
    },
    "required": ["query"]
  }
}
```

Keep it one tool, one input — simple enough that the agent uses it naturally without special prompting.

---

### MCP server implementation (Python)

```python
# server.py
from mcp.server.fastmcp import FastMCP
import lancedb, sqlite3
from embed import embed  # your embedding helper

mcp = FastMCP("codebase-search")
db  = lancedb.connect("./codebase.lancedb")
conn = sqlite3.connect("./codebase.db")

@mcp.tool()
def search_codebase(query: str, limit: int = 5) -> list[dict]:
    """Search the codebase by natural language."""
    # Dense search
    dense = db.open_table("chunks").search(embed(query)).limit(limit * 2).to_list()

    # Sparse search
    rows = conn.execute(
        "SELECT id, file_path, symbol, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
        (query, limit * 2)
    ).fetchall()
    sparse = [{"id": r[0], "file_path": r[1], "symbol": r[2]} for r in rows]

    # RRF merge
    merged = rrf(dense, sparse)[:limit]

    # Return chunks with context
    ids = [id for id, _ in merged]
    return [c for c in dense if c["id"] in ids]

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

---

### Claude Code config (`.claude/settings.json`)

```json
{
  "mcpServers": {
    "codebase-search": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "/path/to/vector-db"
    }
  }
}
```

Once configured, Claude Code can call `search_codebase` in any session automatically.

---

### Relevance to jira-issue-solver

The solver currently reads files explicitly to gather context. With this MCP tool:

1. Before planning, agent calls `search_codebase(issue.summary)` → gets relevant code instantly
2. During code review, agent calls `search_codebase(new_code_description)` → finds similar patterns
3. Token cost per issue drops because context is targeted, not broad

---

## Limitations

- Semantic search only — not a replacement for grep/LSP for exact symbol lookup
- Quality degrades on minified or generated code
- Cross-file reasoning (call graphs, type chains) not supported — use LSP for that

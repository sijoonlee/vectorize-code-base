# TODO

## Graph DB incremental updates

Currently the graph DB calls `clear()` at the start of every `codebase-index` run, wiping
and rebuilding the entire graph even if only one file changed. Extraction is fast (pure
tree-sitter, no Ollama), but it still re-processes every file on every run.

Fix: track which files have been extracted (e.g. a per-file graph cache similar to the
vector cache) and only call `delete_file` + re-extract for files that changed. Unchanged
files can be skipped entirely. The `delete_file` method already exists on all backends for
exactly this purpose.

## LanceDB incremental updates

Currently LanceDB drops and recreates the entire table on every `codebase-index` run, even
if only one file changed. The per-file cache avoids re-embedding unchanged files, but all
records still get rewritten to disk.

Fix: switch from drop+recreate to per-file upsert/delete using `table.delete(where)` and
`table.add()`, matching how the graph side handles `delete_file`. This would make re-index
runs proportional to the number of changed files rather than the total repo size.

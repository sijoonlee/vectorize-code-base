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

## File change detection options

Current behavior is explicit reporting only: an external caller runs
`codebase-file-change --event created|updated|removed <file>`, which records pending work in
`db/<repo-name>/<branch>/state/file_changes.json`. Searches and graph traversals process
that pending state lazily before querying.

Options for detecting changes automatically:

1. Git diff/status detection

   On query or via a separate command, inspect git state and convert changed paths into
   pending file-change records.

   Useful commands:

   ```bash
   git status --porcelain
   git diff --name-only
   git diff --cached --name-only
   ```

   Pros:
   - No background process.
   - Good fit for CLI usage.
   - Fast for normal git repos.

   Cons:
   - Git-only.
   - Needs explicit handling for untracked files, deleted files, staged changes, and branch
     switches.
   - Still needs a clear indexed baseline, such as last indexed file hash or commit.

2. Filesystem watcher

   Run a long-lived watcher, for example using Python `watchdog`, that reports changes as
   files are created, updated, renamed, or removed.

   Pros:
   - Near real-time.
   - Matches the lazy refresh model well because it can cheaply mark files stale.

   Cons:
   - Requires a background process.
   - Needs debounce logic for editor atomic saves and duplicate events.
   - Rename events and temporary files can be noisy across operating systems.

3. Content hash reconciliation

   Maintain an indexed-file manifest containing repo-relative paths and SHA256 hashes from
   the last successful index or refresh. Detect changes by walking supported source files
   and comparing current hashes to the manifest.

   Pros:
   - Works without git.
   - Most directly reflects whether indexed content is current.
   - Can recover from missed watcher events or stale pending state.

   Cons:
   - Requires scanning the repo.
   - Needs ignore rules for generated/vendor directories.
   - Large repos may need optimized traversal or git-assisted narrowing.

Recommended direction: use content hash reconciliation as the authoritative detector, then
optionally add git diff/status or a filesystem watcher as shortcuts that feed the same
pending `file_changes.json` state.

   A practical flow:

   1. Watch repo files for create/update/delete events.
   2. Debounce events briefly, maybe 250-1000ms.
   3. Ignore unsupported files and ignored directories.
   4. For create/update:
         - compute current SHA256
         - compare with the indexed manifest hash
         - if changed, record created or updated
         - if same, do nothing
   5. For delete:
         - if file existed in manifest or vector/graph state, record removed
   6. Lazy refresh runs before query.
   7. After successful refresh, update the manifest hash for that file.
   8. After successful removal, remove it from the manifest.
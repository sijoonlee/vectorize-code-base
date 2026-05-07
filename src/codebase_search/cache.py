from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def file_hash(path: Path, repo: Path) -> str:
    """SHA256 of file contents + repo-relative path.

    Using the relative path makes cache entries portable across machines
    and checkout directories.
    """
    p = Path(path)
    raw = p.read_bytes()
    h = hashlib.sha256()
    h.update(raw)
    h.update(b"\x00")
    try:
        rel = p.resolve().relative_to(repo.resolve())
        h.update(str(rel).encode())
    except ValueError:
        h.update(str(p.resolve()).encode())
    return h.hexdigest()


def load_cached(path: Path, repo: Path, cache_dir: Path) -> list[dict] | None:
    """Return cached records for this file if the hash matches, else None."""
    try:
        h = file_hash(path, repo)
    except OSError:
        return None
    entry = cache_dir / f"{h}.json"
    if not entry.exists():
        return None
    try:
        return json.loads(entry.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cached(path: Path, records: list[dict], repo: Path, cache_dir: Path) -> None:
    """Save chunk records (with vectors) for this file keyed by content hash."""
    p = Path(path)
    if not p.is_file():
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    h = file_hash(p, repo)
    entry = cache_dir / f"{h}.json"
    tmp = entry.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(records), encoding="utf-8")
        try:
            os.replace(tmp, entry)
        except PermissionError:
            import shutil
            shutil.copy2(tmp, entry)
            tmp.unlink(missing_ok=True)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

from __future__ import annotations

import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_BASE = _PROJECT_ROOT / "db"


def derive_db_paths(repo: Path) -> tuple[Path, Path]:
    """Return (vector_db_path, graph_db_path) for a repo directory."""
    repo_name = repo.resolve().name
    branch = _git_branch(repo)
    base = DB_BASE / repo_name / branch
    return base / "vector", base / "graph"


def _git_branch(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()
        return branch if branch else "local"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "local"

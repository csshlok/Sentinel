"""Read-only GitHub repository-slug resolution from the local Git remote.

`ChangeView` carries only a local filesystem `repository_path`, not a
GitHub `owner/repo` slug. Until `[SD]` adds one to the frozen contract,
this module derives it read-only from `git remote get-url origin`,
consistent with the project's read-only repository-inspection rule. The
lookup runs through the hardened harness (`backend.app.git.safe_exec`), so
no hook, filter, driver or execution-bearing config from the repository can
run, and any Git failure resolves to ``None``.
"""

from __future__ import annotations

import re

from backend.app.git.errors import GitRepositoryError
from backend.app.git.safe_exec import run_git

_SSH_PATTERN = re.compile(r"^git@github\.com:(?P<slug>[^/]+/[^/]+?)(\.git)?$")
_HTTPS_PATTERN = re.compile(r"^https://github\.com/(?P<slug>[^/]+/[^/]+?)(\.git)?$")


def resolve_github_repository_slug(repository_path: str) -> str | None:
    try:
        completed = run_git(
            repository_path, ["remote", "get-url", "origin"], timeout=5, limit=4096,
        )
    except (GitRepositoryError, OSError):
        return None
    if (completed.returncode != 0 or completed.timed_out or completed.incomplete
            or completed.truncated):
        return None
    url = completed.stdout.decode("utf-8", errors="replace").strip()
    for pattern in (_SSH_PATTERN, _HTTPS_PATTERN):
        match = pattern.match(url)
        if match:
            return match.group("slug")
    return None

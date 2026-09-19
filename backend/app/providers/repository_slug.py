"""Read-only GitHub repository-slug resolution from the local Git remote.

`ChangeView` carries only a local filesystem `repository_path`, not a
GitHub `owner/repo` slug. Until `[SD]` adds one to the frozen contract,
this module derives it read-only from `git remote get-url origin`,
consistent with the project's read-only repository-inspection rule.
"""

from __future__ import annotations

import re
import subprocess

_SSH_PATTERN = re.compile(r"^git@github\.com:(?P<slug>[^/]+/[^/]+?)(\.git)?$")
_HTTPS_PATTERN = re.compile(r"^https://github\.com/(?P<slug>[^/]+/[^/]+?)(\.git)?$")


def resolve_github_repository_slug(repository_path: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", repository_path, "remote", "get-url", "origin"],
            capture_output=True,
            shell=False,
            timeout=5,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    url = completed.stdout.decode("utf-8", errors="replace").strip()
    for pattern in (_SSH_PATTERN, _HTTPS_PATTERN):
        match = pattern.match(url)
        if match:
            return match.group("slug")
    return None

"""Shared real-repository helpers for the Person 2 (KB) test suites."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=KB Test", "-c", "user.email=kb@example.test",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=root, capture_output=True, text=True, check=check,
    )
    return result.stdout


def make_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    for name, text in (files or {"README.md": "hello\n"}).items():
        write(path, name, text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "initial")
    return path


def write(root: Path, name: str, text: str) -> Path:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return target

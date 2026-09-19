from __future__ import annotations

from pathlib import PurePosixPath

DEPENDENCY_NAMES = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "setup.py",
    "setup.cfg",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gradle.properties",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "requirements-dev.txt",
}

CONFIG_NAMES = {
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env",
    ".env.example",
    "settings.json",
    "appsettings.json",
    "tsconfig.json",
    "webpack.config.js",
    "vite.config.ts",
    "pytest.ini",
    "tox.ini",
    "mypy.ini",
    ".gitignore",
    ".github",
    ".gitlab-ci.yml",
    ".circleci",
    ".devcontainer",
}

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".cs",
    ".go",
    ".rs",
    ".kt",
    ".php",
    ".rb",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".sql",
    ".sh",
    ".ps1",
    ".yaml",
    ".yml",
    ".json",
    ".xml",
    ".toml",
}


def classify_path(path: str) -> str:
    """Return a stable category for a repository-relative path."""
    normalized = path.replace("\\", "/")
    posix = PurePosixPath(normalized)
    name = posix.name.lower()
    parent_parts = [part.lower() for part in posix.parts[:-1]]

    if normalized.lower().endswith(".lock") or name in DEPENDENCY_NAMES or "package" in name:
        return "DEPENDENCY"

    if any(token in parent_parts for token in ("test", "tests")) or "test_" in name or name.startswith("test") or name.endswith("_test.py"):
        return "TEST"

    if any(token in parent_parts for token in ("ci", ".github")) or name in CONFIG_NAMES or normalized.lower().endswith(".config"):
        return "CONFIG"

    if any(token in parent_parts for token in ("docs", "doc")) or name.lower().endswith(".md"):
        return "DOCUMENTATION"

    if name == "dockerfile" or any(token in parent_parts for token in ("scripts", "bin")):
        return "CONFIG"

    if normalized.lower().endswith(tuple(SOURCE_EXTENSIONS)):
        return "SOURCE"

    return "OTHER"

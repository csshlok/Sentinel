"""Pure, deterministic repository-path classification."""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.app.contracts.models import PathCategory


DEPENDENCY_NAMES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "poetry.lock",
    "setup.py", "setup.cfg", "pom.xml", "build.gradle", "build.gradle.kts",
    "gradle.properties", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
    "gemfile", "gemfile.lock", "composer.json", "composer.lock",
}
CONFIG_NAMES = {
    "dockerfile", "compose.yml", "compose.yaml", "docker-compose.yml",
    "docker-compose.yaml", ".env", ".env.example", ".gitignore",
    ".gitattributes", ".editorconfig", "settings.json", "appsettings.json",
    "tsconfig.json", "jsconfig.json", "pytest.ini", "tox.ini", "mypy.ini",
}
CONFIG_DIRECTORIES = {
    ".circleci", ".devcontainer", ".github", ".gitlab", "ci", "config", "configs",
}
TEST_DIRECTORIES = {"test", "tests", "spec", "specs", "__tests__"}
DOC_DIRECTORIES = {"doc", "docs", "documentation"}
CONFIG_EXTENSIONS = {".cfg", ".ini", ".json", ".toml", ".yaml", ".yml"}
SOURCE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".java", ".js",
    ".jsx", ".kt", ".php", ".ps1", ".py", ".rb", ".rs", ".sh", ".sql",
    ".swift", ".ts", ".tsx",
}


def classify_path(path: str) -> PathCategory:
    """Classify a repository-relative path using the documented precedence."""

    normalized = path.replace("\\", "/")
    posix = PurePosixPath(normalized)
    name = posix.name.lower()
    suffix = posix.suffix.lower()
    parent_parts = {part.lower() for part in posix.parts[:-1]}

    if (
        name in DEPENDENCY_NAMES
        or name.endswith(".lock")
        or (name.startswith("requirements") and name.endswith(".txt"))
    ):
        return PathCategory.DEPENDENCY
    if (
        parent_parts & TEST_DIRECTORIES
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    ):
        return PathCategory.TEST
    if (
        parent_parts & CONFIG_DIRECTORIES
        or name in CONFIG_NAMES
        or suffix in CONFIG_EXTENSIONS
        or ".config." in name
    ):
        return PathCategory.CONFIG
    if parent_parts & DOC_DIRECTORIES or suffix in {".md", ".mdx", ".rst"}:
        return PathCategory.DOCUMENTATION
    if suffix in SOURCE_EXTENSIONS:
        return PathCategory.SOURCE
    return PathCategory.OTHER

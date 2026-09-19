"""Pure, bounded parsers for the supported Python and Node manifests/lockfiles.

Supported formats (anything else is reported, never guessed):

* Python: ``requirements*.txt``, ``pyproject.toml`` (PEP 621, PEP 735 groups,
  Poetry tables), ``poetry.lock``.
* Node: ``package.json``, ``package-lock.json`` (lockfileVersion 1, 2 and 3).

Parsers treat repository content strictly as data: nothing is executed, imported
or fetched. Failure raises ``ParseError`` so callers can report partial evidence.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_ENTRIES = 20_000


class ParseError(ValueError):
    """The file is malformed or uses an unsupported shape."""


@dataclass(frozen=True)
class Entry:
    ecosystem: str          # "python" | "node"
    name: str               # normalized identity
    version: str            # exact version, or the declared specifier text
    kind: str               # "declared" | "resolved"
    source: str = "registry"  # registry | path | url | git | workspace
    exact: bool = False
    scope: str = ""         # e.g. "dev", "optional:group", "nested:path"
    direct: bool | None = None


SUPPORTED = {
    "requirements.txt", "pyproject.toml", "poetry.lock", "package.json",
    "package-lock.json",
}
UNSUPPORTED = {
    "yarn.lock": "node", "pnpm-lock.yaml": "node", "npm-shrinkwrap.json": "node",
    "pipfile": "python", "pipfile.lock": "python", "setup.py": "python",
    "setup.cfg": "python", "uv.lock": "python", "cargo.toml": "rust",
    "cargo.lock": "rust", "go.mod": "go", "go.sum": "go", "gemfile": "ruby",
    "gemfile.lock": "ruby", "composer.json": "php", "composer.lock": "php",
    "pom.xml": "java", "build.gradle": "java", "build.gradle.kts": "java",
}


def is_supported(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name in SUPPORTED or (name.startswith("requirements") and name.endswith(".txt"))


def unsupported_ecosystem(path: str) -> str | None:
    return UNSUPPORTED.get(PurePosixPath(path).name.lower())


def normalize_python(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


_PEP508 = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(\[[^\]]*\])?\s*(.*)$")
_EXACT = re.compile(r"^==\s*([0-9][^\s,;*]*)$")


def _python_requirement(text: str, scope: str) -> Entry:
    text = text.strip()
    match = _PEP508.match(text)
    if not match:
        raise ParseError("Unrecognized requirement.")
    name, _extras, rest = match.groups()
    rest = rest.split(";", 1)[0].strip()
    source = "registry"
    if rest.startswith("@"):
        target = rest[1:].strip()
        source = ("git" if target.startswith("git+") else
                  "url" if re.match(r"^[a-z][a-z0-9+.-]*://", target, re.I) else "path")
        return Entry("python", normalize_python(name), target[:512], "declared",
                     source, False, scope, True)
    rest = re.sub(r"\s+", "", rest)
    exact = _EXACT.match(rest)
    if exact:
        return Entry("python", normalize_python(name), exact.group(1), "declared",
                     source, True, scope, True)
    return Entry("python", normalize_python(name), rest or "(unpinned)", "declared",
                 source, False, scope, True)


def parse_requirements(text: str) -> list[Entry]:
    entries: list[Entry] = []
    logical: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if pending:
            line = pending + line.lstrip()
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1] + " "
            continue
        logical.append(line)
    if pending:
        logical.append(pending)
    for line in logical:
        line = re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            option = line.split(None, 1)[0].lower()
            if option in {"-r", "--requirement", "-c", "--constraint"}:
                target = line.split(None, 1)[1] if " " in line else ""
                entries.append(Entry("python", f"<include:{target.strip()[:200]}>", "(not followed)",
                                     "declared", "path", False, "include", True))
            elif option in {"-e", "--editable"}:
                target = line.split(None, 1)[1] if " " in line else ""
                entries.append(Entry("python", f"<editable:{target.strip()[:200]}>", "(editable)",
                                     "declared", "path", False, "editable", True))
            continue  # index/hash/format options carry no package identity
        line = re.sub(r"\s--hash=\S+", "", line)
        if re.match(r"^[a-z][a-z0-9+.-]*://", line, re.I) or line.startswith(("./", "../", "/")):
            entries.append(Entry("python", f"<direct:{line[:200]}>", "(direct reference)",
                                 "declared", "url" if "://" in line else "path", False, "", True))
            continue
        entries.append(_python_requirement(line, ""))
        if len(entries) > MAX_ENTRIES:
            raise ParseError("Too many requirements.")
    return entries


def parse_pyproject(text: str) -> list[Entry]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ParseError("Invalid TOML.") from exc
    entries: list[Entry] = []

    def add_list(items: object, scope: str) -> None:
        if not isinstance(items, list):
            raise ParseError("Dependency list has an unsupported shape.")
        for item in items:
            if isinstance(item, str):
                entries.append(_python_requirement(item, scope))
            elif isinstance(item, dict) and "include-group" in item:
                continue
            else:
                raise ParseError("Dependency entry has an unsupported shape.")

    project = data.get("project", {})
    if not isinstance(project, dict):
        raise ParseError("Invalid [project] table.")
    if "dependencies" in project:
        add_list(project["dependencies"], "")
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        raise ParseError("Invalid optional dependencies.")
    for group in sorted(optional):
        add_list(optional[group], f"optional:{group}")
    groups = data.get("dependency-groups", {})
    if not isinstance(groups, dict):
        raise ParseError("Invalid dependency groups.")
    for group in sorted(groups):
        add_list(groups[group], f"group:{group}")
    build = data.get("build-system", {})
    if isinstance(build, dict) and "requires" in build:
        add_list(build["requires"], "build")

    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    if isinstance(poetry, dict):
        tables = [("", poetry.get("dependencies")), ("dev", poetry.get("dev-dependencies"))]
        for gname, group in sorted((poetry.get("group") or {}).items()):
            if isinstance(group, dict):
                tables.append((f"group:{gname}", group.get("dependencies")))
        for scope, table in tables:
            if table is None:
                continue
            if not isinstance(table, dict):
                raise ParseError("Invalid Poetry dependency table.")
            for name, spec in sorted(table.items()):
                if name.lower() == "python":
                    continue
                entries.append(_poetry_entry(name, spec, scope))
    if len(entries) > MAX_ENTRIES:
        raise ParseError("Too many dependencies.")
    return entries


def _poetry_entry(name: str, spec: object, scope: str) -> Entry:
    normalized = normalize_python(name)
    if isinstance(spec, list):
        spec = spec[0] if spec and isinstance(spec[0], dict) else ""
    if isinstance(spec, str):
        version, source = spec, "registry"
    elif isinstance(spec, dict):
        source = ("git" if "git" in spec else "path" if "path" in spec
                  else "url" if "url" in spec else "registry")
        version = str(spec.get("version") or spec.get("path") or spec.get("url")
                      or spec.get("git") or "(unpinned)")
    else:
        raise ParseError("Invalid Poetry dependency specification.")
    exact = source == "registry" and bool(re.fullmatch(r"=?=?\s*[0-9][^\s,^~*<>|]*", version))
    if exact:
        version = version.lstrip("= ").strip()
    return Entry("python", normalized, version[:512], "declared", source, exact, scope, True)


def parse_poetry_lock(text: str, direct_names: set[str] | None = None) -> list[Entry]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ParseError("Invalid TOML.") from exc
    packages = data.get("package", [])
    if not isinstance(packages, list):
        raise ParseError("Invalid poetry.lock package list.")
    entries = []
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str) \
                or not isinstance(package.get("version"), str):
            raise ParseError("Invalid poetry.lock package.")
        name = normalize_python(package["name"])
        source = package.get("source", {})
        kind = source.get("type", "registry") if isinstance(source, dict) else "registry"
        mapped = {"legacy": "registry", "directory": "path", "file": "path",
                  "url": "url", "git": "git"}.get(kind, "registry")
        entries.append(Entry("python", name, package["version"], "resolved", mapped, True, "",
                             None if direct_names is None else name in direct_names))
    if len(entries) > MAX_ENTRIES:
        raise ParseError("Too many locked packages.")
    return entries


def _node_source(spec: str) -> str:
    lowered = spec.lower()
    if lowered.startswith(("file:", "link:", "./", "../", "/", "~/")):
        return "path"
    if lowered.startswith(("http://", "https://")):
        return "url"
    if lowered.startswith(("git+", "git://", "github:", "gitlab:", "bitbucket:")) \
            or re.match(r"^[\w.-]+/[\w.-]+(#.*)?$", spec):
        return "git"
    if lowered.startswith("workspace:"):
        return "workspace"
    return "registry"


_NODE_EXACT = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]+)?$")


def parse_package_json(text: str) -> tuple[list[Entry], bool]:
    """Return declared dependencies and whether the manifest declares workspaces."""

    data = _load_json(text)
    if not isinstance(data, dict):
        raise ParseError("package.json must be an object.")
    entries: list[Entry] = []
    for section, scope in (("dependencies", ""), ("devDependencies", "dev"),
                           ("optionalDependencies", "optional"), ("peerDependencies", "peer")):
        table = data.get(section)
        if table is None:
            continue
        if not isinstance(table, dict):
            raise ParseError(f"{section} must be an object.")
        for name in sorted(table):
            spec = table[name]
            if not isinstance(spec, str):
                raise ParseError("Dependency specifications must be strings.")
            source = _node_source(spec)
            entries.append(Entry("node", name.lower(), spec[:512], "declared", source,
                                 source == "registry" and bool(_NODE_EXACT.match(spec)),
                                 scope, True))
    if len(entries) > MAX_ENTRIES:
        raise ParseError("Too many dependencies.")
    return entries, bool(data.get("workspaces"))


def parse_package_lock(text: str, direct_names: set[str] | None = None) -> list[Entry]:
    data = _load_json(text)
    if not isinstance(data, dict):
        raise ParseError("package-lock.json must be an object.")
    entries: list[Entry] = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        root = packages.get("", {})
        root_direct: set[str] = set()
        if isinstance(root, dict):
            for section in ("dependencies", "devDependencies", "optionalDependencies",
                            "peerDependencies"):
                table = root.get(section, {})
                if isinstance(table, dict):
                    root_direct |= {name.lower() for name in table}
        direct = direct_names if direct_names is not None else root_direct
        for key in sorted(packages):
            entry = packages[key]
            if key == "" or not isinstance(entry, dict):
                continue
            if "node_modules/" not in key:
                # workspace member or linked package location
                if entry.get("link") or "version" not in entry:
                    continue
            name = key.rsplit("node_modules/", 1)[-1] or key
            version = entry.get("version")
            if not isinstance(version, str):
                if entry.get("link"):
                    version = f"link:{entry.get('resolved', '')}"
                else:
                    continue
            nested = key.count("node_modules/") > 1
            resolved = str(entry.get("resolved", ""))
            source = ("path" if entry.get("link") else
                      "git" if resolved.startswith(("git+", "git:")) else
                      "url" if resolved and not resolved.startswith("https://registry.") and "/-/" not in resolved
                      else "registry")
            entries.append(Entry("node", name.lower(), version[:512], "resolved", source, True,
                                 f"nested:{key}" if nested else "",
                                 (name.lower() in direct) and not nested))
    elif isinstance(data.get("dependencies"), dict):
        direct = direct_names or set()

        def walk(table: dict, prefix: str, depth: int) -> None:
            for name in sorted(table):
                entry = table[name]
                if not isinstance(entry, dict) or not isinstance(entry.get("version"), str):
                    raise ParseError("Invalid legacy lock entry.")
                entries.append(Entry(
                    "node", name.lower(), entry["version"][:512], "resolved",
                    "registry" if "://" not in entry["version"] else "url", True,
                    f"nested:{prefix}{name}" if depth else "",
                    depth == 0 and name.lower() in direct))
                sub = entry.get("dependencies")
                if isinstance(sub, dict):
                    if depth > 64:
                        raise ParseError("Lock nesting is too deep.")
                    walk(sub, f"{prefix}{name}>", depth + 1)

        walk(data["dependencies"], "", 0)
    else:
        raise ParseError("Unsupported package-lock.json shape.")
    if len(entries) > MAX_ENTRIES:
        raise ParseError("Too many locked packages.")
    return entries


def _load_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ParseError("Invalid JSON.") from exc

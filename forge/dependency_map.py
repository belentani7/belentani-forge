"""Dependency map — what each project depends on, and what is shared.

Parses the manifests projects actually declare (``requirements.txt``,
``pyproject.toml``, ``package.json``) with the standard library only. The point
is not a resolver; it is knowing which packages appear across the ecosystem, and
which are pinned to conflicting versions in different repositories.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import Project

REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]+\])?\s*([<>=!~^]{1,2}\s*[\w.*+-]+)?")
PEP508 = re.compile(r'^\s*["\']?([A-Za-z0-9._-]+)\s*(?:\[[^\]]+\])?\s*([<>=!~^]{1,2}[^"\',]*)?')


@dataclass
class Dependency:
    name: str
    version: str = ""
    ecosystem: str = "python"
    dev: bool = False

    def key(self) -> str:
        return "%s:%s" % (self.ecosystem, self.name.lower())


@dataclass
class DependencyMap:
    """Ecosystem-wide dependency graph."""
    by_project: Dict[str, List[Dependency]] = field(default_factory=dict)

    def add(self, project: str, deps: List[Dependency]) -> None:
        self.by_project[project] = deps

    def usage(self) -> Dict[str, List[str]]:
        """``{dependency_key: [projects using it]}``, most used first."""
        index: Dict[str, List[str]] = defaultdict(list)
        for project, deps in self.by_project.items():
            for dep in deps:
                index[dep.key()].append(project)
        return dict(sorted(index.items(), key=lambda kv: -len(kv[1])))

    def shared(self, minimum: int = 3) -> Dict[str, List[str]]:
        """Dependencies used by at least *minimum* projects."""
        return {k: v for k, v in self.usage().items() if len(v) >= minimum}

    def conflicts(self) -> Dict[str, List[Tuple[str, str]]]:
        """Dependencies pinned to different versions across projects."""
        versions: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
        for project, deps in self.by_project.items():
            for dep in deps:
                if dep.version:
                    versions[dep.key()].add((project, dep.version))

        out = {}
        for key, pairs in versions.items():
            distinct = {v for _p, v in pairs}
            if len(distinct) > 1:
                out[key] = sorted(pairs)
        return out

    def ecosystems(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for deps in self.by_project.values():
            for dep in deps:
                counts[dep.ecosystem] += 1
        return dict(counts)

    def to_dict(self) -> dict:
        return {
            "projects": {p: [d.__dict__ for d in deps]
                         for p, deps in sorted(self.by_project.items())},
            "shared": self.shared(),
            "conflicts": self.conflicts(),
            "ecosystems": self.ecosystems(),
        }


def parse_requirements(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return deps

    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        match = REQ_LINE.match(line)
        if match:
            deps.append(Dependency(name=match.group(1),
                                   version=(match.group(2) or "").replace(" ", ""),
                                   ecosystem="python"))
    return deps


def parse_pyproject(path: Path) -> List[Dependency]:
    """Extract dependencies without a TOML parser dependency.

    Handles the two common shapes: PEP 621 ``[project] dependencies = [...]``
    and Poetry's ``[tool.poetry.dependencies]`` table.
    """
    deps: List[Dependency] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return deps

    block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    if block:
        for entry in block.group(1).split(","):
            entry = entry.strip().strip("'\"")
            if not entry:
                continue
            match = PEP508.match(entry)
            if match:
                deps.append(Dependency(name=match.group(1),
                                       version=(match.group(2) or "").strip(),
                                       ecosystem="python"))

    poetry = re.search(r"\[tool\.poetry\.dependencies\](.*?)(?:\n\[|\Z)", text, re.S)
    if poetry:
        for line in poetry.group(1).splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            name, _, version = line.partition("=")
            name = name.strip()
            if name and name.lower() != "python":
                deps.append(Dependency(name=name,
                                       version=version.strip().strip('"\'{} '),
                                       ecosystem="python"))
    return deps


def parse_package_json(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return deps

    for field_name, is_dev in (("dependencies", False), ("devDependencies", True)):
        for name, version in (data.get(field_name) or {}).items():
            deps.append(Dependency(name=name, version=str(version),
                                   ecosystem="node", dev=is_dev))
    return deps


PARSERS = (
    ("requirements.txt", parse_requirements),
    ("pyproject.toml", parse_pyproject),
    ("package.json", parse_package_json),
)


def scan_project(path: Path) -> List[Dependency]:
    """Collect every declared dependency for one project, de-duplicated."""
    found: Dict[str, Dependency] = {}
    for filename, parser in PARSERS:
        manifest = path / filename
        if manifest.exists():
            for dep in parser(manifest):
                found.setdefault(dep.key(), dep)
    return list(found.values())


def build(projects: List[Project]) -> DependencyMap:
    """Build the ecosystem-wide dependency map from scanned projects."""
    dmap = DependencyMap()
    for project in projects:
        if not project.path:
            continue
        path = Path(project.path)
        if path.exists():
            deps = scan_project(path)
            if deps:
                dmap.add(project.name, deps)
    return dmap

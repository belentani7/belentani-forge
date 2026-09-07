"""Project state — idempotent tracking across runs.

``forge scan`` can run once or a hundred times; if nothing changed on disk the
recorded state is identical. That is enforced with a content fingerprint per
project rather than a timestamp, so re-running never produces a spurious diff
and never generates ``file_final2.py``-style residue.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .models import Project
from .safety import redact

STATE_VERSION = 2


def identity(project: Project) -> str:
    """Stable store key for *project*.

    Name alone is not unique: the same project often exists both standalone and
    vendored inside a monorepo. Keying on name plus path keeps those as separate
    entries instead of letting them overwrite each other every run.
    """
    if not project.path:
        return project.name
    digest = hashlib.sha256(project.path.encode("utf-8")).hexdigest()[:8]
    return "%s@%s" % (project.name, digest)


def fingerprint(project: Project) -> str:
    """Stable hash of the facts that define a project's state.

    Deliberately excludes timestamps and scan order so identical inputs always
    yield an identical digest.
    """
    payload = {
        "name": project.name,
        "stack": project.stack,
        "files": project.file_count,
        "status": project.status,
        "category": project.category,
        "branch": project.git.branch,
        "dirty": project.git.dirty,
        "remote": project.git.remote,
        "commit": project.git.last_commit,
        "flags": [project.has_readme, project.has_license, project.has_gitignore,
                  project.has_ci, project.has_tests, project.has_docker,
                  project.has_env_example],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class Snapshot:
    """One project's recorded state."""
    name: str
    fingerprint: str
    status: str
    score: int
    issues: int
    first_seen: str
    last_seen: str
    last_changed: str
    path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StateStore:
    """Persistent, idempotent project-state database."""
    path: Path = field(default_factory=lambda: config.FORGE_HOME / "project_state.json")
    snapshots: Dict[str, Snapshot] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "StateStore":
        store = cls(path=path or config.FORGE_HOME / "project_state.json")
        if not store.path.exists():
            return store
        try:
            raw = json.loads(store.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return store
        for name, data in raw.get("projects", {}).items():
            store.snapshots[name] = Snapshot(**data)
        return store

    def save(self) -> Path:
        payload = {
            "version": STATE_VERSION,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "projects": {n: s.to_dict() for n, s in sorted(self.snapshots.items())},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            redact(json.dumps(payload, indent=2, sort_keys=True)),
            encoding="utf-8")
        return self.path

    def record(self, project: Project) -> str:
        """Record *project* and return what happened: new / changed / unchanged."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        digest = fingerprint(project)
        key = identity(project)
        existing = self.snapshots.get(key)

        if existing is None:
            self.snapshots[key] = Snapshot(
                name=project.name, fingerprint=digest, status=project.status,
                score=project.score(), issues=len(project.issues),
                first_seen=now, last_seen=now, last_changed=now,
                path=project.path)
            return "new"

        if existing.fingerprint == digest:
            existing.last_seen = now
            return "unchanged"

        existing.fingerprint = digest
        existing.status = project.status
        existing.score = project.score()
        existing.issues = len(project.issues)
        existing.last_seen = now
        existing.last_changed = now
        return "changed"

    def record_all(self, projects: List[Project]) -> Dict[str, int]:
        counts = {"new": 0, "changed": 0, "unchanged": 0}
        for project in projects:
            counts[self.record(project)] += 1
        return counts

    def drifted(self) -> List[Snapshot]:
        """Projects whose state changed since they were first recorded."""
        return [s for s in self.snapshots.values() if s.last_changed != s.first_seen]

    def regressed(self, projects: List[Project]) -> List[str]:
        """Projects whose score dropped versus the recorded snapshot."""
        out = []
        for project in projects:
            prev = self.snapshots.get(identity(project))
            if prev and project.score() < prev.score:
                out.append("%s: %d → %d" % (project.name, prev.score, project.score()))
        return out

    def duplicates(self) -> Dict[str, List[str]]:
        """Project names recorded at more than one path."""
        by_name: Dict[str, List[str]] = {}
        for snap in self.snapshots.values():
            by_name.setdefault(snap.name, []).append(snap.path)
        return {n: sorted(p) for n, p in by_name.items() if len(p) > 1}

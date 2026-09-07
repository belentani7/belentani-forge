"""Inventory — the pipeline that turns raw scans into a decided ecosystem.

    SCAN → MAP → CLASSIFY → VERIFY → DEPENDENCIES → STATE → REPORT

:func:`build` runs the whole thing read-only and returns an :class:`Inventory`
that every reporter can consume. Running it twice with unchanged inputs
produces byte-identical output.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import classifier, config, dependency_map, scanner, skills_router, verifier
from .executor import Executor
from .models import Project, Status
from .project_state import StateStore
from .safety import redact

PRIORITY_ORDER = ["P0_SECURITY", "P1_NOT_EXECUTABLE", "P2_BACKEND_BROKEN",
                  "P3_TOOLING_BROKEN", "P4_TESTS_DOCS", "P5_ORGANIZATION",
                  "P6_OPTIMIZATION"]


@dataclass
class Inventory:
    """Everything FORGE knows about the ecosystem after one pass."""
    generated: str = ""
    projects: List[Project] = field(default_factory=list)
    github_repos: List[dict] = field(default_factory=list)
    orphans: List[dict] = field(default_factory=list)
    issues: List = field(default_factory=list)
    verdicts: List = field(default_factory=list)
    dependencies: Optional[dependency_map.DependencyMap] = None
    state_changes: Dict[str, int] = field(default_factory=dict)
    regressions: List[str] = field(default_factory=list)
    duplicates: Dict[str, List[str]] = field(default_factory=dict)

    # ------------------------------------------------------------- summaries
    def by_status(self) -> Dict[str, int]:
        counts = {s.value: 0 for s in Status}
        for p in self.projects:
            counts[p.status] = counts.get(p.status, 0) + 1
        return counts

    def by_category(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for p in self.projects:
            out.setdefault(p.category, []).append(p.name)
        return {k: sorted(v) for k, v in sorted(out.items())}

    def frozen(self) -> List[str]:
        return sorted(p.name for p in self.projects if p.frozen)

    def repair_queue(self) -> List[Project]:
        """Projects needing work, worst priority first, then lowest score.

        Excludes everything :meth:`do_not_touch` covers — frozen, archived and
        backup projects. An archived repository is read-only upstream, so
        writing into it produces a diff that can never land.
        """
        untouchable = {id(p) for p in self.do_not_touch()}
        pending = [p for p in self.projects if p.issues and id(p) not in untouchable]
        return sorted(pending, key=lambda p: (
            PRIORITY_ORDER.index(p.priority) if p.priority in PRIORITY_ORDER else 99,
            p.score(),
        ))

    def finished(self) -> List[Project]:
        """Projects that genuinely meet the Definition of Done."""
        done = {v.project for v in self.verdicts if v.done}
        return sorted((p for p in self.projects if p.name in done),
                      key=lambda p: -p.score())

    def needs_work(self) -> List[Project]:
        done = {v.project for v in self.verdicts if v.done}
        return sorted((p for p in self.projects if p.name not in done and not p.frozen),
                      key=lambda p: p.score())

    def do_not_touch(self) -> List[Project]:
        return sorted((p for p in self.projects
                       if p.frozen or p.archived or p.classification == "BACKUP"),
                      key=lambda p: p.name)

    def nested_repos(self) -> Dict[str, List[str]]:
        """Git repositories living inside another repository's working tree.

        Unless registered as submodules these show up as untracked noise in the
        parent, which is the usual cause of a repo reporting hundreds of dirty
        files. Reported, never auto-resolved: the fix is either a submodule, a
        ``.gitignore`` entry, or extraction — and that is a design decision.
        """
        paths = sorted(((p.path.replace("\\", "/").rstrip("/"), p.name)
                        for p in self.projects if p.path),
                       key=lambda kv: len(kv[0]))
        out: Dict[str, List[str]] = {}
        for i, (child_path, child_name) in enumerate(paths):
            # Walk candidates longest-first so a child is attributed to its
            # nearest enclosing repo, not the outermost one.
            for parent_path, parent_name in reversed(paths[:i]):
                if child_path.startswith(parent_path + "/"):
                    out.setdefault(parent_name, []).append(child_name)
                    break
        return {k: sorted(v) for k, v in sorted(out.items())}

    def issues_by_priority(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for issue in self.issues:
            counts[issue.priority] = counts.get(issue.priority, 0) + 1
        return {k: counts[k] for k in PRIORITY_ORDER if k in counts}

    # ---------------------------------------------------------------- export
    def to_dict(self) -> dict:
        return {
            "generated": self.generated,
            "totals": {
                "local_projects": len(self.projects),
                "github_repos": len(self.github_repos),
                "orphan_github_repos": len(self.orphans),
                "issues": len(self.issues),
                "frozen": len(self.frozen()),
            },
            "by_status": self.by_status(),
            "by_category": self.by_category(),
            "issues_by_priority": self.issues_by_priority(),
            "state_changes": self.state_changes,
            "regressions": self.regressions,
            "duplicate_names": self.duplicates,
            "nested_repos": self.nested_repos(),
            "finished": [p.name for p in self.finished()],
            "needs_work": [p.name for p in self.needs_work()],
            "do_not_touch": [p.name for p in self.do_not_touch()],
            "repair_queue": [
                {"project": p.name, "priority": p.priority, "score": p.score(),
                 "issues": p.issues}
                for p in self.repair_queue()
            ],
            "verdicts": [v.to_dict() for v in self.verdicts],
            "dependencies": self.dependencies.to_dict() if self.dependencies else {},
            "projects": [p.to_dict() for p in self.projects],
        }

    def save(self, path: Optional[Path] = None) -> Path:
        target = path or config.REPORTS_DIR / "PROJECT_INVENTORY.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            redact(json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)),
            encoding="utf-8")
        return target


def build(local_scan: Optional[Path] = None, github_scan: Optional[Path] = None,
          deep: bool = False, track_state: bool = True) -> Inventory:
    """Run the full read-only pipeline and return the :class:`Inventory`."""
    inv = Inventory(generated=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    projects = scanner.load_local_scan(local_scan)
    repos = scanner.load_github_scan(github_scan)

    inv.projects = scanner.match_local_to_github(projects, repos)
    inv.github_repos = repos
    inv.orphans = scanner.find_orphan_github_repos(inv.projects, repos)
    inv.issues = classifier.classify_all(inv.projects)

    executor = Executor(apply=False)
    inv.verdicts = verifier.verify_all(inv.projects, executor=executor, deep=deep)
    inv.dependencies = dependency_map.build(inv.projects)

    if track_state:
        store = StateStore.load()
        inv.regressions = store.regressed(inv.projects)
        inv.state_changes = store.record_all(inv.projects)
        inv.duplicates = store.duplicates()
        store.save()

    return inv


def plan(inv: Inventory, limit: int = 20) -> List[dict]:
    """Concrete next actions, highest priority first.

    Frozen projects never appear here — they are documented, not modified.
    """
    actions: List[dict] = []
    for project in inv.repair_queue()[:limit]:
        route = skills_router.route(" ".join(project.issues) or "project audit")
        actions.append({
            "project": project.name,
            "path": project.path,
            "priority": project.priority,
            "score": project.score(),
            "issues": project.issues,
            "skills": route.available or route.skills,
            "intent": route.intent.value,
        })
    return actions


def save_plan(inv: Inventory, path: Optional[Path] = None, limit: int = 20) -> Path:
    target = path or config.REPORTS_DIR / "REPAIR_PLAN.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": inv.generated,
        "totals": inv.to_dict()["totals"],
        "issues_by_priority": inv.issues_by_priority(),
        "actions": plan(inv, limit=limit),
    }
    target.write_text(redact(json.dumps(payload, indent=2, sort_keys=True)),
                      encoding="utf-8")
    return target

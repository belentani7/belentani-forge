"""Verifier — the Definition of Done, enforced.

A project is FINISHED only when every check below passes. "Has many files" is
not evidence of anything. Each :class:`Check` records what was tested, what
happened, and — when it fails — what the next action is.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from .executor import Executor
from .models import Project
from .safety import find_secrets


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    blocking: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Verdict:
    project: str
    checks: List[Check] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    @property
    def blockers(self) -> List[Check]:
        return [c for c in self.checks if c.blocking and not c.passed]

    @property
    def score(self) -> int:
        if not self.checks:
            return 0
        return round(100 * sum(1 for c in self.checks if c.passed) / len(self.checks))

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "done": self.done,
            "score": self.score,
            "checks": [c.to_dict() for c in self.checks],
            "blockers": [c.name for c in self.blockers],
        }


TEST_COMMANDS = {
    "python": [["python", "-m", "pytest", "-q", "--no-header"]],
    "node": [["npm", "test", "--silent"]],
}

BUILD_COMMANDS = {
    "node": [["npm", "run", "build"]],
}


def detect_runner(path: Path) -> Optional[str]:
    """Return ``python`` / ``node`` based on what the project actually declares."""
    if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
        return "python"
    if (path / "package.json").exists():
        return "node"
    return None


def check_structure(project: Project) -> List[Check]:
    return [
        Check("readme", project.has_readme, "README.md present", blocking=False),
        Check("license", project.has_license, "LICENSE present", blocking=False),
        Check("gitignore", project.has_gitignore, ".gitignore present", blocking=False),
        Check("not_empty", project.file_count > 0,
              "%d files" % project.file_count),
    ]


def check_git(project: Project) -> List[Check]:
    return [
        Check("git_repo", project.git.repo, "is a git repository"),
        Check("has_remote", project.git.remote not in ("", "none"),
              project.git.remote or "no remote"),
        Check("clean_tree", project.git.dirty == 0,
              "%d uncommitted files" % project.git.dirty
              if project.git.dirty else "clean",
              blocking=False),
    ]


def check_secrets(path: Path, max_files: int = 400) -> Check:
    """Scan tracked source files for real credentials."""
    hits: List[str] = []
    scanned = 0
    skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build"}

    for file in path.rglob("*"):
        if scanned >= max_files:
            break
        if not file.is_file() or file.suffix not in {".py", ".js", ".ts", ".json", ".yml",
                                                     ".yaml", ".toml", ".sh", ".env"}:
            continue
        if any(part in skip_dirs for part in file.parts):
            continue
        scanned += 1
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for kind, lineno in find_secrets(text):
            hits.append("%s:%d %s" % (file.name, lineno, kind))

    return Check("no_secrets", not hits,
                 "clean (%d files scanned)" % scanned if not hits
                 else "%d potential secrets: %s" % (len(hits), "; ".join(hits[:3])))


def check_tests(path: Path, executor: Executor) -> Check:
    runner = detect_runner(path)
    if not runner:
        return Check("tests", False, "no recognised project manifest", blocking=False)

    for cmd in TEST_COMMANDS.get(runner, []):
        res = executor.run(cmd, cwd=path, timeout=300)
        if res.dry_run:
            return Check("tests", False, "not run (dry run)", blocking=False)
        if res.ok:
            return Check("tests", True, "%s test suite passed" % runner)
        return Check("tests", False, res.output.splitlines()[-1] if res.output else "failed")

    return Check("tests", False, "no test command for %s" % runner, blocking=False)


def check_build(path: Path, executor: Executor) -> Check:
    runner = detect_runner(path)
    commands = BUILD_COMMANDS.get(runner or "", [])
    if not commands:
        return Check("build", True, "no build step required", blocking=False)

    for cmd in commands:
        res = executor.run(cmd, cwd=path, timeout=600)
        if res.dry_run:
            return Check("build", False, "not run (dry run)", blocking=False)
        if not res.ok:
            return Check("build", False, res.output.splitlines()[-1] if res.output else "failed")
    return Check("build", True, "build succeeded")


def verify(project: Project, executor: Optional[Executor] = None,
           deep: bool = False) -> Verdict:
    """Run the Definition of Done against *project*.

    With ``deep=False`` (default) only static checks run — fast and safe across
    hundreds of repositories. ``deep=True`` additionally runs the test suite and
    build, which requires ``executor.apply``.
    """
    executor = executor or Executor(apply=False)
    verdict = Verdict(project=project.name)

    verdict.checks.extend(check_structure(project))
    verdict.checks.extend(check_git(project))

    path = Path(project.path) if project.path else None
    if path and path.exists():
        verdict.checks.append(check_secrets(path))
        if deep:
            verdict.checks.append(check_tests(path, executor))
            verdict.checks.append(check_build(path, executor))

    return verdict


def verify_all(projects: List[Project], executor: Optional[Executor] = None,
               deep: bool = False) -> List[Verdict]:
    return [verify(p, executor=executor, deep=deep) for p in projects]

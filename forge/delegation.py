"""Delegation — route bulk mechanical work to a cheaper model, durably.

The premise: an expensive model should spend its tokens on judgement, not on
adding four hundred docstrings. This module defines the work a mid-tier model
is genuinely precise at, keeps a resumable task bank in SQLite, and drives the
work through a direct model API one file at a time.

Three properties make it safe to point at a large codebase:

  * **Scoped.** Only patterns with one defensible answer are delegated. Anything
    needing architectural judgement, or touching security or frozen frontend,
    is refused by :func:`eligible`.
  * **Verified.** Every task runs a mechanical check afterwards. A task that
    breaks the file is marked ``failed`` and its diff reverted.
  * **Resumable.** State lives in SQLite, so an interrupted run picks up exactly
    where it stopped instead of redoing finished work.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from . import config
from .executor import DRY_RUN_CODE, Executor, Result
from .safety import is_frontend_path, is_frozen_project, redact

DB_PATH = config.FORGE_HOME / "delegation.db"
SCHEMA_VERSION = 1

# Files that must never be delegated regardless of pattern.
SENSITIVE_NAMES = {
    "auth", "authentication", "authorization", "login", "session",
    "crypto", "secrets", "credentials", "password", "token", "security",
    "payment", "billing", "settings", "config",
}


class State(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    REVERTED = "reverted"


@dataclass
class Pattern:
    """A unit of work with exactly one defensible answer.

    ``verify`` is a command template run after the edit. If it fails, the edit
    is reverted — that is what keeps a mid-tier model honest at volume.
    """
    name: str
    instruction: str
    glob: str = "**/*.py"
    verify: Sequence[str] = ("python", "-m", "py_compile", "{file}")
    max_bytes: int = 40_000
    rationale: str = ""

    def to_dict(self) -> dict:
        return {**asdict(self), "verify": list(self.verify)}


# Ordered as a chain: each pass assumes the previous one landed.
PATTERNS: Dict[str, Pattern] = {
    p.name: p for p in [
        Pattern(
            "imports",
            "Remove unused imports and sort the remaining ones into standard "
            "library, third-party, then local groups. Change nothing else — "
            "no logic, no formatting outside the import block.",
            rationale="Purely mechanical; the compiler verifies it.",
        ),
        Pattern(
            "docstrings",
            "Add a concise docstring to every public function, method and class "
            "that lacks one. Describe what it does, its arguments and what it "
            "returns. Do not modify any code, signature or existing docstring.",
            rationale="Bounded, additive, and verifiable by compilation.",
        ),
        Pattern(
            "type_hints",
            "Add type annotations to function parameters and return values where "
            "they are missing and the correct type is unambiguous from the code. "
            "Import from typing as needed. If a type is not obvious, leave it "
            "alone. Change no logic.",
            rationale="Deterministic where inferable; skips what it cannot infer.",
        ),
        Pattern(
            "error_handling",
            "Replace every bare 'except:' with 'except Exception:' and every "
            "silent 'pass' in an except block with a logged warning using the "
            "module logger. Do not change control flow or add new behaviour.",
            rationale="A single mechanical rule with a fixed correct output.",
        ),
        Pattern(
            "smoke_tests",
            "Write a pytest smoke test module for this file. Import it, assert "
            "each public function is callable, and exercise any pure function "
            "with obvious inputs. Do not mock. Do not test side effects. Do not "
            "modify the source file.",
            verify=("python", "-m", "py_compile", "{file}"),
            rationale="Scaffolding only; a human still writes the real tests.",
        ),
        Pattern(
            "sql_schema",
            "Generate a CREATE TABLE statement for each dataclass or model in "
            "this file, mapping Python types to SQL types, with primary keys and "
            "NOT NULL where the field has no default. Output SQL only, in a new "
            "file. Do not modify the source.",
            rationale="A direct type mapping, not a design decision.",
        ),
    ]
}

CHAINS: Dict[str, List[str]] = {
    "hygiene": ["imports", "error_handling"],
    "document": ["imports", "docstrings", "type_hints"],
    "full": ["imports", "error_handling", "docstrings", "type_hints"],
    "scaffold": ["smoke_tests"],
    "data": ["sql_schema"],
}


@dataclass
class Task:
    project: str
    file: str
    pattern: str
    state: str = State.PENDING.value
    attempts: int = 0
    detail: str = ""
    updated: str = ""

    def key(self) -> str:
        return "%s|%s|%s" % (self.project, self.file, self.pattern)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ eligibility
def eligible(path: Path, project_name: str = "") -> tuple:
    """Return ``(ok, reason)`` for delegating work on *path*.

    Refusals are deliberate: a mid-tier model editing auth or frozen frontend
    at volume is how a codebase quietly breaks.
    """
    if project_name and is_frozen_project(project_name):
        return False, "project is frozen this phase"
    if is_frontend_path(path):
        return False, "frontend asset — frozen this phase"

    stem = path.stem.lower()
    if any(marker in stem for marker in SENSITIVE_NAMES):
        return False, "security- or config-sensitive filename"
    if path.name.startswith("test_") or path.name == "conftest.py":
        return False, "test file — edit these deliberately"
    if "migrations" in {p.lower() for p in path.parts}:
        return False, "migration — historical record, never rewrite"

    try:
        if path.stat().st_size == 0:
            return False, "empty file"
    except OSError as exc:
        return False, str(exc)

    return True, ""


def collect(root: Path, pattern: Pattern, project_name: str = "",
            limit: Optional[int] = None) -> List[Path]:
    """Files under *root* eligible for *pattern*, deterministically ordered."""
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv",
            "dist", "build", ".next", "site-packages"}
    found: List[Path] = []

    for path in sorted(root.glob(pattern.glob)):
        if any(part in skip for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > pattern.max_bytes:
                continue
        except OSError:
            continue
        ok, _reason = eligible(path, project_name)
        if ok:
            found.append(path)
        if limit and len(found) >= limit:
            break
    return found


# -------------------------------------------------------------------- task bank
class TaskBank:
    """SQLite-backed, resumable task store.

    Keyed on ``(project, file, pattern)`` so re-planning the same work is a
    no-op and an interrupted run never repeats finished tasks.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                project  TEXT NOT NULL,
                file     TEXT NOT NULL,
                pattern  TEXT NOT NULL,
                state    TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                detail   TEXT NOT NULL DEFAULT '',
                updated  TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (project, file, pattern)
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),))
        self.conn.commit()

    # ------------------------------------------------------------------ writes
    def enqueue(self, tasks: Iterable[Task]) -> int:
        """Insert tasks, ignoring any already known. Returns the number added."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        added = 0
        for task in tasks:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO tasks(project, file, pattern, state, updated) "
                "VALUES(?,?,?,?,?)",
                (task.project, task.file, task.pattern, State.PENDING.value, now))
            added += cur.rowcount
        self.conn.commit()
        return added

    def mark(self, task: Task, state: State, detail: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        bump = 1 if state is State.RUNNING else 0
        self.conn.execute(
            "UPDATE tasks SET state=?, detail=?, updated=?, attempts=attempts+? "
            "WHERE project=? AND file=? AND pattern=?",
            (state.value, redact(detail)[:500], now, bump,
             task.project, task.file, task.pattern))
        self.conn.commit()

    def reset_running(self) -> int:
        """Return tasks orphaned by a crash to the queue."""
        cur = self.conn.execute(
            "UPDATE tasks SET state='pending' WHERE state='running'")
        self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------- reads
    def pending(self, limit: Optional[int] = None,
                max_attempts: int = 2) -> List[Task]:
        sql = ("SELECT * FROM tasks WHERE state='pending' AND attempts < ? "
               "ORDER BY project, pattern, file")
        params: list = [max_attempts]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [Task(**dict(r)) for r in self.conn.execute(sql, params)]

    def counts(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT state, COUNT(*) n FROM tasks GROUP BY state")
        return {r["state"]: r["n"] for r in rows}

    def failures(self, limit: int = 20) -> List[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE state='failed' ORDER BY updated DESC LIMIT ?",
            (limit,))
        return [Task(**dict(r)) for r in rows]

    def close(self) -> None:
        self.conn.close()


def _extract_code_block(text: str) -> str:
    """Return the first fenced code block of a model reply, else the reply."""
    match = re.search(r"```[a-zA-Z0-9+_-]*\n(.*?)```", text, re.DOTALL)
    return match.group(1) if match else text


# ------------------------------------------------------------------- delegation
@dataclass
class Delegator:
    """Drives tasks through a direct model API (no aider, no terminal)."""
    model: str = "deepseek/deepseek-v4-pro"
    executor: Executor = field(default_factory=lambda: Executor(apply=False))
    timeout: int = 300

    def command(self, task: Task, pattern: Pattern) -> List[str]:
        """Human-readable description of the edit (direct API — no aider)."""
        return ["forge-api", "--model", self.model,
                "--pattern", pattern.name, "--edit", task.file]

    def edit(self, task: Task, pattern: Pattern, cwd: Path) -> Result:
        """Edit one file by calling the model API directly.

        Credentials are read only from environment variables and are never
        printed. Requires ``DEEPSEEK_API_KEY``; honours ``DEEPSEEK_BASE_URL``
        and ``DEEPSEEK_MODEL`` when present.
        """
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        model = os.environ.get("DEEPSEEK_MODEL", self.model)
        label = ["forge-api", "edit", task.file]

        if not key:
            return Result(cmd=label, code=1,
                          output="missing DEEPSEEK_API_KEY (set it to delegate)")
        if not self.executor.apply:
            return Result(cmd=label, code=DRY_RUN_CODE,
                          output="(dry run — not executed)", dry_run=True)

        path = cwd / task.file
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            return Result(cmd=label, code=1, output=str(exc))

        prompt = (
            "%s\n\nFile: %s\nReply with ONLY the complete modified file "
            "content inside a single fenced code block. If no change is "
            "required, return the file exactly as given.\n\n```\n%s\n```"
            % (pattern.instruction, task.file, original)
        )
        payload = json.dumps({
            "model": model,
            "temperature": 0,
            "stream": False,
            "messages": [
                {"role": "system",
                 "content": "You are a precise code editor. Output only the "
                            "complete file content in one fenced code block. "
                            "Change nothing except what the instruction requires."},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            base + "/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return Result(cmd=label, code=exc.code,
                          output="API %s: %s" % (exc.code, redact(str(exc))[:200]))
        except (urllib.error.URLError, OSError) as exc:
            return Result(cmd=label, code=1, output=str(exc)[:200])

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return Result(cmd=label, code=1, output="unexpected API response shape")

        edited = _extract_code_block(content)
        if edited.strip() == original.strip():
            return Result(cmd=label, code=0, output="no change")
        try:
            path.write_text(edited, encoding="utf-8")
        except OSError as exc:
            return Result(cmd=label, code=1, output=str(exc))
        return Result(cmd=label, code=0, output="edited")

    def verify(self, task: Task, pattern: Pattern) -> Result:
        cmd = [part.replace("{file}", task.file) for part in pattern.verify]
        if cmd and cmd[0] == "python":
            cmd[0] = sys.executable
        return Executor(apply=True, timeout=120).run(cmd)

    def revert(self, task: Task, cwd: Path) -> None:
        """Undo a failed edit. Scoped to the one file — never the whole tree."""
        subprocess.run(["git", "checkout", "--", task.file],
                       cwd=str(cwd), capture_output=True)

    def run_task(self, task: Task, cwd: Path) -> tuple:
        """Run one task. Returns ``(State, detail)``."""
        pattern = PATTERNS.get(task.pattern)
        if pattern is None:
            return State.SKIPPED, "unknown pattern"

        edit = self.edit(task, pattern, cwd)
        if edit.dry_run:
            return State.PENDING, "dry run — not executed"
        if not edit.ok:
            return State.FAILED, (edit.output or "edit failed").splitlines()[-1][:200]

        check = self.verify(task, pattern)
        if not check.ok:
            self.revert(task, cwd)
            return State.REVERTED, "verification failed: %s" % (
                (check.output or "").splitlines()[-1][:160])

        return State.DONE, "edited and verified"


def plan(project_name: str, root: Path, chain: str = "document",
         limit_files: Optional[int] = None) -> List[Task]:
    """Build the task list for one project without touching anything."""
    tasks: List[Task] = []
    for pattern_name in CHAINS.get(chain, []):
        pattern = PATTERNS[pattern_name]
        for path in collect(root, pattern, project_name, limit=limit_files):
            tasks.append(Task(project=project_name,
                              file=str(path.relative_to(root)).replace("\\", "/"),
                              pattern=pattern_name))
    return tasks


def estimate(tasks: Sequence[Task]) -> Dict[str, object]:
    """Rough volume estimate so a run can be sized before it starts."""
    by_pattern: Dict[str, int] = {}
    for t in tasks:
        by_pattern[t.pattern] = by_pattern.get(t.pattern, 0) + 1
    return {
        "tasks": len(tasks),
        "files": len({t.file for t in tasks}),
        "by_pattern": dict(sorted(by_pattern.items())),
        "serial_minutes_estimate": round(len(tasks) * 0.5, 1),
    }

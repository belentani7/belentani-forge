"""Executor — command execution that is read-only until you say otherwise.

Every subprocess in the modular API goes through :class:`Executor`. In the
default (``apply=False``) mode nothing runs that could change state: the call
is recorded and returned as a ``DRY_RUN`` result. That makes ``forge`` safe to
point at a live workspace before you have decided what should happen.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from .safety import SafetyViolation, guard_command, redact

DRY_RUN_CODE = -1

# Commands that only observe. They run even when apply=False.
READ_ONLY = {
    ("git", "status"), ("git", "diff"), ("git", "log"),
    ("git", "remote"), ("git", "rev-parse"), ("git", "ls-files"),
    ("git", "show"), ("git", "config"), ("git", "describe"),
    ("git", "rev-list"),
    ("gh", "repo"), ("gh", "auth"), ("gh", "api"),
    ("python", "--version"), ("node", "--version"), ("npm", "--version"),
}

# Subcommands that only observe when given no positional argument.
# ``git branch`` lists; ``git branch <name>`` creates one.
CONDITIONAL_READ_ONLY = {("git", "branch"), ("git", "tag"), ("git", "stash")}


@dataclass
class Result:
    """Outcome of one command."""
    cmd: List[str]
    code: int
    output: str = ""
    duration: float = 0.0
    dry_run: bool = False
    cwd: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0

    def __str__(self) -> str:
        tag = "DRY_RUN" if self.dry_run else ("OK" if self.ok else "FAIL(%d)" % self.code)
        return "%s %s" % (tag, " ".join(self.cmd))


@dataclass
class Executor:
    """Runs commands under the safety rules.

    Args:
        apply: when False, state-changing commands are recorded, not run.
        timeout: per-command ceiling in seconds.
        authorized: set True only for a destructive operation the user approved.
    """
    apply: bool = False
    timeout: int = 900
    authorized: bool = False
    history: List[Result] = field(default_factory=list)

    def is_read_only(self, cmd: Sequence[str]) -> bool:
        """True only when *cmd* cannot change state.

        ``git branch`` and friends list when bare but mutate when given a
        positional argument, so they are checked for one.
        """
        if not cmd:
            return False
        head = Path(str(cmd[0])).stem.lower()
        sub = str(cmd[1]).lower() if len(cmd) > 1 else ""

        if (head, sub) in READ_ONLY:
            return True

        if (head, sub) in CONDITIONAL_READ_ONLY:
            positionals = [a for a in cmd[2:] if not str(a).startswith("-")]
            return not positionals

        return False

    def run(self, cmd: Sequence[str], cwd: Optional[Path] = None,
            timeout: Optional[int] = None) -> Result:
        """Execute *cmd*, honouring dry-run and the destructive-command guard."""
        cmd = [str(c) for c in cmd]
        guard_command(cmd, authorized=self.authorized)

        if not self.apply and not self.is_read_only(cmd):
            result = Result(cmd=cmd, code=DRY_RUN_CODE, output="(dry run — not executed)",
                            dry_run=True, cwd=str(cwd or ""))
            self.history.append(result)
            return result

        exe = shutil.which(cmd[0])
        if not exe:
            result = Result(cmd=cmd, code=127, output="not found in PATH: %s" % cmd[0],
                            cwd=str(cwd or ""))
            self.history.append(result)
            return result

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [exe, *cmd[1:]],
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                timeout=timeout or self.timeout,
            )
            text = (proc.stdout + b"\n" + proc.stderr).decode("utf-8", "replace").strip()
            code = proc.returncode
        except subprocess.TimeoutExpired:
            text, code = "timeout after %ss" % (timeout or self.timeout), 124
        except OSError as exc:
            text, code = str(exc), 1

        result = Result(cmd=cmd, code=code, output=redact(text),
                        duration=time.monotonic() - start, cwd=str(cwd or ""))
        self.history.append(result)
        return result

    def run_all(self, commands: Sequence[Sequence[str]], cwd: Optional[Path] = None,
                stop_on_error: bool = True) -> List[Result]:
        """Run *commands* in order, stopping at the first failure by default."""
        results: List[Result] = []
        for cmd in commands:
            try:
                res = self.run(cmd, cwd=cwd)
            except SafetyViolation as exc:
                res = Result(cmd=[str(c) for c in cmd], code=126, output=str(exc),
                             cwd=str(cwd or ""))
                self.history.append(res)
            results.append(res)
            if stop_on_error and not res.ok and not res.dry_run:
                break
        return results

    def summary(self) -> dict:
        return {
            "total": len(self.history),
            "ok": sum(1 for r in self.history if r.ok),
            "failed": sum(1 for r in self.history if not r.ok and not r.dry_run),
            "dry_run": sum(1 for r in self.history if r.dry_run),
        }

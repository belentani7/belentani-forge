"""Git manager — inspection first, mutation only when it is provably safe.

The rule from the FORGE spec: never destroy local work. Every mutating helper
here checks the working tree before it acts, and refuses rather than guessing.
``git reset --hard``, ``git clean -fd`` and force pushes are not implemented at
all — they are blocked one layer down in :mod:`forge.safety`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .executor import Executor, Result
from .models import GitState
from .safety import safe_to_commit


@dataclass
class GitManager:
    """Safe git operations for a single repository."""
    path: Path
    executor: Executor

    def _git(self, *args: str) -> Result:
        return self.executor.run(["git", *args], cwd=self.path)

    # ---------------------------------------------------------------- inspect
    def is_repo(self) -> bool:
        return (Path(self.path) / ".git").exists()

    def state(self) -> GitState:
        """Full read-only snapshot of the repository."""
        if not self.is_repo():
            return GitState()

        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        status = self._git("status", "--porcelain")
        remote = self._git("remote", "get-url", "origin")
        commit = self._git("log", "-1", "--format=%h %s")

        dirty = len([ln for ln in status.output.splitlines() if ln.strip()]) if status.ok else 0

        unpushed = 0
        if remote.ok:
            counts = self._git("rev-list", "--count", "@{u}..HEAD")
            if counts.ok and counts.output.strip().isdigit():
                unpushed = int(counts.output.strip())

        return GitState(
            repo=True,
            branch=branch.output.strip() if branch.ok else "",
            dirty=dirty,
            remote=remote.output.strip() if remote.ok else "none",
            last_commit=commit.output.strip() if commit.ok else "",
            unpushed=unpushed,
        )

    def dirty_files(self) -> List[Path]:
        status = self._git("status", "--porcelain")
        if not status.ok:
            return []
        files = []
        for line in status.output.splitlines():
            if len(line) > 3:
                files.append(Path(self.path) / line[3:].strip().strip('"'))
        return files

    def diverged(self) -> bool:
        """True when local and remote have both moved on — needs a rebase."""
        if not self._git("remote", "get-url", "origin").ok:
            return False
        behind = self._git("rev-list", "--count", "HEAD..@{u}")
        ahead = self._git("rev-list", "--count", "@{u}..HEAD")
        try:
            return int(behind.output.strip()) > 0 and int(ahead.output.strip()) > 0
        except (ValueError, AttributeError):
            return False

    # ----------------------------------------------------------------- mutate
    def stage(self, paths: Optional[List[str]] = None) -> Result:
        return self._git("add", *(paths or ["-A"]))

    def commit(self, message: str, allow_empty: bool = False) -> Result:
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        return self._git(*args)

    def safe_commit(self, message: str) -> Result:
        """Stage and commit, but refuse if the tree carries secrets.

        Returns a synthetic ``code=126`` result listing every reason rather than
        committing something that should not leave the machine.
        """
        problems = safe_to_commit(self.dirty_files())
        if problems:
            return Result(cmd=["git", "commit"], code=126,
                          output="refused — secrets or private files staged:\n  " +
                                 "\n  ".join(problems),
                          cwd=str(self.path))
        staged = self.stage()
        if not staged.ok and not staged.dry_run:
            return staged
        return self.commit(message)

    def safe_push(self, remote: str = "origin", branch: Optional[str] = None) -> Result:
        """Push only from a clean tree with a configured remote."""
        state = self.state()
        if state.dirty:
            return Result(cmd=["git", "push"], code=126,
                          output="refused — %d uncommitted files; commit or stash first"
                                 % state.dirty,
                          cwd=str(self.path))
        if state.remote == "none":
            return Result(cmd=["git", "push"], code=126,
                          output="refused — no remote configured", cwd=str(self.path))
        return self._git("push", remote, branch or state.branch)

    def sync(self, remote: str = "origin") -> Result:
        """Rebase onto the remote. Refuses when the tree is dirty."""
        state = self.state()
        if state.dirty:
            return Result(cmd=["git", "pull", "--rebase"], code=126,
                          output="refused — %d uncommitted files would be at risk"
                                 % state.dirty,
                          cwd=str(self.path))
        return self._git("pull", "--rebase", remote, state.branch)

    def snapshot_branch(self, label: str) -> Result:
        """Create a backup branch pointing at HEAD before a structural change."""
        return self._git("branch", "forge-snapshot/%s" % label)

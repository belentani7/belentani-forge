"""Tests for the executor."""
import sys

import pytest

from forge.executor import DRY_RUN_CODE, Executor, Result
from forge.safety import SafetyViolation


class TestDryRun:
    def test_state_changing_command_not_executed(self):
        ex = Executor(apply=False)
        res = ex.run(["git", "commit", "-m", "x"])
        assert res.dry_run
        assert res.code == DRY_RUN_CODE

    def test_read_only_command_still_runs(self):
        ex = Executor(apply=False)
        res = ex.run(["git", "status", "--porcelain"])
        assert not res.dry_run

    def test_apply_mode_executes(self):
        ex = Executor(apply=True)
        res = ex.run([sys.executable, "--version"])
        assert not res.dry_run
        assert res.ok


class TestResult:
    def test_ok_property(self):
        assert Result(cmd=["x"], code=0).ok
        assert not Result(cmd=["x"], code=1).ok

    def test_str_shows_dry_run(self):
        assert "DRY_RUN" in str(Result(cmd=["git", "push"], code=-1, dry_run=True))

    def test_str_shows_failure_code(self):
        assert "FAIL(2)" in str(Result(cmd=["git"], code=2))


class TestSafety:
    def test_destructive_command_raises(self):
        with pytest.raises(SafetyViolation):
            Executor(apply=True).run(["git", "reset", "--hard"])

    def test_authorized_executor_permits(self):
        ex = Executor(apply=False, authorized=True)
        res = ex.run(["git", "reset", "--hard"])
        assert res.dry_run


class TestMissingBinary:
    def test_returns_127(self):
        ex = Executor(apply=True)
        res = ex.run(["definitely-not-a-real-binary-xyz"])
        assert res.code == 127


class TestHistory:
    def test_records_every_call(self):
        ex = Executor(apply=False)
        ex.run(["git", "commit", "-m", "a"])
        ex.run(["git", "commit", "-m", "b"])
        assert len(ex.history) == 2

    def test_summary_counts(self):
        ex = Executor(apply=False)
        ex.run(["git", "commit", "-m", "a"])
        summary = ex.summary()
        assert summary["total"] == 1
        assert summary["dry_run"] == 1


class TestRunAll:
    def test_runs_in_order(self):
        ex = Executor(apply=False)
        results = ex.run_all([["git", "add", "-A"], ["git", "commit", "-m", "x"]])
        assert len(results) == 2

    def test_destructive_becomes_126_not_exception(self):
        ex = Executor(apply=False)
        results = ex.run_all([["git", "clean", "-fd"]], stop_on_error=False)
        assert results[0].code == 126

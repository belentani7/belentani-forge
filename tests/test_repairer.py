"""Tests for the repairer.

The properties that make it safe to run across the whole ecosystem:
create-only, idempotent, and blind to frozen work.
"""
from pathlib import Path

from forge import repairer
from forge.models import GitState, Project
from forge.repairer import Outcome


def bare(tmp_path, name="demo", stack="python"):
    return Project(name=name, path=str(tmp_path), stack=stack, file_count=3,
                   git=GitState(repo=True, branch="main"))


def outcomes(repairs):
    return {r.fix: r.outcome for r in repairs}


class TestDryRun:
    def test_writes_nothing(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=False)
        assert list(tmp_path.iterdir()) == []

    def test_reports_would_fix(self, tmp_path):
        result = outcomes(repairer.repair_project(bare(tmp_path), apply=False))
        assert result["gitignore"] == Outcome.WOULD_FIX.value
        assert result["license"] == Outcome.WOULD_FIX.value


class TestApply:
    def test_creates_missing_files(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=True)
        assert (tmp_path / ".gitignore").exists()
        assert (tmp_path / "LICENSE").exists()
        assert (tmp_path / ".env.example").exists()
        assert (tmp_path / "README.md").exists()

    def test_creates_nested_ci_path(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=True)
        assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()

    def test_creates_smoke_test(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=True)
        assert (tmp_path / "tests" / "test_smoke.py").exists()

    def test_license_carries_author(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=True)
        text = (tmp_path / "LICENSE").read_text(encoding="utf-8")
        assert "MIT License" in text
        assert "{{AUTHOR}}" not in text

    def test_readme_names_the_project(self, tmp_path):
        repairer.repair_project(bare(tmp_path, name="my-tool"), apply=True)
        assert "# my-tool" in (tmp_path / "README.md").read_text(encoding="utf-8")


class TestIdempotency:
    def test_second_run_changes_nothing(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=True)
        before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

        repairer.repair_project(bare(tmp_path), apply=True)
        after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert before == after

    def test_second_run_reports_already_ok(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=True)
        second = outcomes(repairer.repair_project(bare(tmp_path), apply=True))
        assert all(v == Outcome.ALREADY_OK.value for v in second.values())

    def test_never_overwrites_existing(self, tmp_path):
        (tmp_path / "LICENSE").write_text("CUSTOM LICENSE", encoding="utf-8")
        repairer.repair_project(bare(tmp_path), apply=True)
        assert (tmp_path / "LICENSE").read_text(encoding="utf-8") == "CUSTOM LICENSE"


class TestFrozen:
    def test_frozen_flag_skips_everything(self, tmp_path):
        p = bare(tmp_path)
        p.frozen = True
        repairs = repairer.repair_project(p, apply=True)
        assert repairs[0].outcome == Outcome.SKIPPED_FROZEN.value
        assert list(tmp_path.iterdir()) == []

    def test_frozen_by_name_skips(self, tmp_path):
        repairs = repairer.repair_project(
            bare(tmp_path, name="ManosAbiertas"), apply=True)
        assert repairs[0].outcome == Outcome.SKIPPED_FROZEN.value
        assert list(tmp_path.iterdir()) == []

    def test_archived_project_skipped(self, tmp_path):
        """An archived repo is read-only upstream — a diff there can never land."""
        p = bare(tmp_path)
        p.archived = True
        repairs = repairer.repair_project(p, apply=True)
        assert repairs[0].outcome == Outcome.SKIPPED_FROZEN.value
        assert "archived" in repairs[0].detail
        assert list(tmp_path.iterdir()) == []

    def test_backup_project_skipped(self, tmp_path):
        p = bare(tmp_path)
        p.classification = "BACKUP"
        repairs = repairer.repair_project(p, apply=True)
        assert repairs[0].outcome == Outcome.SKIPPED_FROZEN.value
        assert list(tmp_path.iterdir()) == []


class TestStackGating:
    def test_node_project_gets_no_python_ci(self, tmp_path):
        result = outcomes(repairer.repair_project(
            bare(tmp_path, stack="node"), apply=True))
        assert result["ci"] == Outcome.ALREADY_OK.value
        assert not (tmp_path / ".github").exists()

    def test_node_project_gets_no_pytest_scaffold(self, tmp_path):
        repairer.repair_project(bare(tmp_path, stack="node"), apply=True)
        assert not (tmp_path / "tests").exists()

    def test_node_still_gets_license(self, tmp_path):
        repairer.repair_project(bare(tmp_path, stack="node"), apply=True)
        assert (tmp_path / "LICENSE").exists()


class TestNeedsDecision:
    def test_missing_remote_is_not_auto_fixed(self, tmp_path):
        p = bare(tmp_path)
        p.issues = ["P3_TOOLING_BROKEN: No git remote configured"]
        decisions = [r for r in repairer.repair_project(p, apply=True)
                     if r.outcome == Outcome.NEEDS_DECISION.value]
        assert decisions and "wrong place" in decisions[0].detail

    def test_dirty_tree_is_not_auto_committed(self, tmp_path):
        p = bare(tmp_path)
        p.issues = ["P5_ORGANIZATION: Dirty git state: 7 uncommitted files"]
        decisions = [r for r in repairer.repair_project(p, apply=True)
                     if r.outcome == Outcome.NEEDS_DECISION.value]
        assert decisions and "belongs to you" in decisions[0].detail


class TestMissingPath:
    def test_reports_failure_not_crash(self):
        repairs = repairer.repair_project(
            Project(name="ghost", path="/nonexistent/xyz"), apply=True)
        assert repairs[0].outcome == Outcome.FAILED.value


class TestBatch:
    def test_summarise_counts_outcomes(self, tmp_path):
        a = tmp_path / "a"; a.mkdir()
        b = tmp_path / "b"; b.mkdir()
        repairs = repairer.repair_all(
            [bare(a, "a"), bare(b, "b")], apply=False)
        assert repairer.summarise(repairs)[Outcome.WOULD_FIX.value] > 0

    def test_limit_respected(self, tmp_path):
        a = tmp_path / "a"; a.mkdir()
        b = tmp_path / "b"; b.mkdir()
        repairs = repairer.repair_all([bare(a, "a"), bare(b, "b")], limit=1)
        assert {r.project for r in repairs} == {"a"}

    def test_actionable_filters_noise(self, tmp_path):
        repairer.repair_project(bare(tmp_path), apply=True)
        repairs = repairer.repair_project(bare(tmp_path), apply=True)
        assert repairer.actionable(repairs) == []

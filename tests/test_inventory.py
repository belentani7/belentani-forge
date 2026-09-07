"""Tests for the inventory pipeline."""
import json

from forge import inventory
from forge.models import GitState, Project


def sample():
    inv = inventory.Inventory(generated="2026-09-08T00:00:00+00:00")
    inv.projects = [
        Project(name="green", status="GREEN", category="CORE", file_count=20,
                has_readme=True, has_license=True, has_gitignore=True,
                has_tests=True, has_ci=True,
                git=GitState(repo=True, remote="https://github.com/u/green")),
        Project(name="yellow", status="YELLOW", category="PRODUCTS", priority="P4_TESTS_DOCS",
                issues=["P4_TESTS_DOCS: No tests directory"], file_count=5,
                git=GitState(repo=True, remote="https://github.com/u/yellow")),
        Project(name="ManosAbiertas", status="YELLOW", category="PRODUCTS",
                frozen=True, issues=["P4_TESTS_DOCS: Missing README.md"],
                priority="P4_TESTS_DOCS", file_count=8, git=GitState(repo=True)),
    ]
    return inv


class TestSummaries:
    def test_by_status(self):
        counts = sample().by_status()
        assert counts["GREEN"] == 1
        assert counts["YELLOW"] == 2

    def test_by_category_groups(self):
        assert sample().by_category()["PRODUCTS"] == ["ManosAbiertas", "yellow"]

    def test_frozen_listed(self):
        assert sample().frozen() == ["ManosAbiertas"]

    def test_repair_queue_excludes_frozen(self):
        names = [p.name for p in sample().repair_queue()]
        assert "ManosAbiertas" not in names
        assert "yellow" in names

    def test_do_not_touch_includes_frozen(self):
        assert "ManosAbiertas" in [p.name for p in sample().do_not_touch()]

    def test_issues_by_priority(self):
        inv = sample()
        assert inv.issues_by_priority() == {}


class TestRepairQueueOrdering:
    def test_worst_priority_first(self):
        inv = inventory.Inventory()
        inv.projects = [
            Project(name="low", priority="P5_ORGANIZATION", issues=["x"], file_count=1),
            Project(name="critical", priority="P0_SECURITY", issues=["y"], file_count=1),
        ]
        assert [p.name for p in inv.repair_queue()] == ["critical", "low"]


class TestExport:
    def test_to_dict_sections(self):
        payload = sample().to_dict()
        for key in ("generated", "totals", "by_status", "by_category",
                    "repair_queue", "finished", "needs_work", "do_not_touch",
                    "projects"):
            assert key in payload

    def test_totals_are_accurate(self):
        assert sample().to_dict()["totals"]["local_projects"] == 3

    def test_save_writes_valid_json(self, tmp_path):
        path = sample().save(tmp_path / "inv.json")
        assert json.loads(path.read_text(encoding="utf-8"))["totals"]

    def test_save_is_deterministic(self, tmp_path):
        first = sample().save(tmp_path / "a.json").read_text(encoding="utf-8")
        second = sample().save(tmp_path / "b.json").read_text(encoding="utf-8")
        assert first == second


class TestPlan:
    def test_excludes_frozen_projects(self):
        assert "ManosAbiertas" not in [a["project"] for a in inventory.plan(sample())]

    def test_limit_respected(self):
        assert len(inventory.plan(sample(), limit=1)) <= 1

    def test_actions_carry_skills(self):
        actions = inventory.plan(sample())
        assert actions and "skills" in actions[0]

    def test_save_plan_writes_json(self, tmp_path):
        path = inventory.save_plan(sample(), tmp_path / "plan.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "actions" in payload and "totals" in payload


class TestBuildPipeline:
    def test_runs_with_missing_scans(self, tmp_path):
        """No scan files present must yield an empty inventory, not a crash."""
        inv = inventory.build(local_scan=tmp_path / "none.json",
                              github_scan=tmp_path / "none2.json",
                              track_state=False)
        assert inv.projects == []
        assert inv.generated

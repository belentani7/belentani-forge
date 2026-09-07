"""Tests for the skill router."""
import pytest

from forge import skills_router as sr
from forge.skills_router import Intent


class TestDetectIntent:
    @pytest.mark.parametrize("task,expected", [
        ("audit the repositories and build an inventory", Intent.PROJECT_AUDIT),
        ("write a python script to automate the pipeline", Intent.PYTHON_AUTOMATION),
        ("scan for leaked secrets and credentials", Intent.SECURITY),
        ("build a fastapi backend with a database", Intent.BACKEND),
        ("set up ci and deploy to vercel", Intent.DEPLOYMENT),
        ("write the readme documentation", Intent.DOCUMENTATION),
        ("run pytest and check coverage", Intent.TESTING),
    ])
    def test_maps_task_to_intent(self, task, expected):
        assert sr.detect_intent(task) == expected

    @pytest.mark.parametrize("task", [
        "restyle the landing page css",
        "tweak the gsap animation",
        "fix the webgl shader",
        "adjust the tailwind layout",
    ])
    def test_frontend_always_wins(self, task):
        assert sr.detect_intent(task) == Intent.FRONTEND

    def test_frontend_beats_other_signals(self):
        """A task mentioning both must still be caught as frontend."""
        assert sr.detect_intent("test the css animation") == Intent.FRONTEND

    def test_unknown_for_unrelated_text(self):
        assert sr.detect_intent("banana sandwich") == Intent.UNKNOWN

    def test_spanish_keywords(self):
        assert sr.detect_intent("auditoria del inventario") == Intent.PROJECT_AUDIT


class TestRoute:
    def test_frontend_is_blocked(self):
        route = sr.route("redesign the landing page")
        assert route.blocked
        assert route.skills == []
        assert "frozen" in route.reason

    def test_non_frontend_returns_skills(self):
        route = sr.route("audit the repositories")
        assert not route.blocked
        assert route.skills

    def test_limit_is_respected(self):
        assert len(sr.route("audit repositories", limit=2).skills) <= 2

    def test_available_and_missing_partition(self, tmp_path):
        (tmp_path / "investigate-first").mkdir()
        route = sr.route("audit the repositories", root=tmp_path)
        assert "investigate-first" in route.available
        assert "investigate-first" not in route.missing
        assert set(route.available) | set(route.missing) == set(route.skills)

    def test_to_dict_shape(self):
        payload = sr.route("run the tests").to_dict()
        assert set(payload) == {"intent", "skills", "available", "missing",
                                "blocked", "reason"}


class TestInstalledSkills:
    def test_lists_directories(self, tmp_path):
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        (tmp_path / "not-a-skill.txt").write_text("x", encoding="utf-8")
        assert sr.installed_skills(tmp_path) == ["alpha", "beta"]

    def test_missing_root_is_empty(self, tmp_path):
        assert sr.installed_skills(tmp_path / "absent") == []


class TestNamespacedSkills:
    def test_detects_plugin_format(self):
        assert sr.is_namespaced("engineering:architecture")
        assert not sr.is_namespaced("investigate-first")

    def test_plugin_skills_not_reported_missing(self, tmp_path):
        """Plugin skills have no directory, so a scan must not call them absent."""
        route = sr.route("set up ci and deploy", root=tmp_path)
        assert not any(sr.is_namespaced(s) for s in route.missing)

    def test_plugin_skills_counted_available(self, tmp_path):
        route = sr.route("set up ci and deploy", root=tmp_path)
        assert "engineering:deploy-checklist" in route.available


class TestCoverage:
    def test_reports_partition(self, tmp_path):
        (tmp_path / "investigate-first").mkdir()
        cov = sr.coverage(tmp_path)
        assert cov["installed_total"] == 1
        assert "investigate-first" in cov["available"]
        assert cov["referenced"] > 0

    def test_plugin_provided_listed_separately(self, tmp_path):
        cov = sr.coverage(tmp_path)
        assert cov["plugin_provided"]
        assert not set(cov["plugin_provided"]) & set(cov["missing"])

    def test_route_all(self):
        routes = sr.route_all(["run the tests", "restyle the css"])
        assert len(routes) == 2
        assert routes[1].blocked

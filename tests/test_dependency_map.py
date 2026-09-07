"""Tests for dependency parsing and the ecosystem graph."""
import json

from forge import dependency_map as dm
from forge.models import Project


class TestParseRequirements:
    def test_name_and_version(self, tmp_path):
        f = tmp_path / "requirements.txt"
        f.write_text("requests==2.31.0\nflask>=2.0\n", encoding="utf-8")
        deps = dm.parse_requirements(f)
        assert {d.name for d in deps} == {"requests", "flask"}
        assert deps[0].version == "==2.31.0"

    def test_skips_comments_and_flags(self, tmp_path):
        f = tmp_path / "requirements.txt"
        f.write_text("# comment\n-r other.txt\nrequests\n", encoding="utf-8")
        assert [d.name for d in dm.parse_requirements(f)] == ["requests"]

    def test_strips_extras(self, tmp_path):
        f = tmp_path / "requirements.txt"
        f.write_text("uvicorn[standard]==0.29.0\n", encoding="utf-8")
        assert dm.parse_requirements(f)[0].name == "uvicorn"

    def test_missing_file_is_empty(self, tmp_path):
        assert dm.parse_requirements(tmp_path / "nope.txt") == []


class TestParsePyproject:
    def test_pep621_dependencies(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text(
            '[project]\nname = "x"\ndependencies = [\n  "httpx>=0.27",\n  "rich",\n]\n',
            encoding="utf-8")
        assert {d.name for d in dm.parse_pyproject(f)} == {"httpx", "rich"}

    def test_poetry_table(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text(
            '[tool.poetry.dependencies]\npython = "^3.11"\nrequests = "^2.31"\n',
            encoding="utf-8")
        names = {d.name for d in dm.parse_pyproject(f)}
        assert "requests" in names
        assert "python" not in names


class TestParsePackageJson:
    def test_splits_dev_dependencies(self, tmp_path):
        f = tmp_path / "package.json"
        f.write_text(json.dumps({
            "dependencies": {"react": "^18.0.0"},
            "devDependencies": {"vitest": "^1.0.0"},
        }), encoding="utf-8")
        deps = {d.name: d for d in dm.parse_package_json(f)}
        assert deps["react"].dev is False
        assert deps["vitest"].dev is True
        assert deps["react"].ecosystem == "node"

    def test_invalid_json_is_empty(self, tmp_path):
        f = tmp_path / "package.json"
        f.write_text("{broken", encoding="utf-8")
        assert dm.parse_package_json(f) == []


class TestDependencyMap:
    def build(self):
        graph = dm.DependencyMap()
        graph.add("a", [dm.Dependency("requests", "==2.31.0"),
                        dm.Dependency("flask", "==2.0")])
        graph.add("b", [dm.Dependency("requests", "==2.28.0")])
        graph.add("c", [dm.Dependency("requests", "==2.31.0")])
        return graph

    def test_usage_ranks_by_popularity(self):
        usage = self.build().usage()
        assert list(usage)[0] == "python:requests"
        assert len(usage["python:requests"]) == 3

    def test_shared_respects_minimum(self):
        assert "python:requests" in self.build().shared(minimum=3)
        assert "python:flask" not in self.build().shared(minimum=3)

    def test_conflicts_detected(self):
        conflicts = self.build().conflicts()
        assert "python:requests" in conflicts

    def test_no_conflict_when_versions_agree(self):
        graph = dm.DependencyMap()
        graph.add("a", [dm.Dependency("rich", "==13.0")])
        graph.add("b", [dm.Dependency("rich", "==13.0")])
        assert graph.conflicts() == {}

    def test_ecosystems_counted(self):
        graph = dm.DependencyMap()
        graph.add("a", [dm.Dependency("react", "^18", ecosystem="node"),
                        dm.Dependency("rich", "", ecosystem="python")])
        assert graph.ecosystems() == {"node": 1, "python": 1}

    def test_to_dict_has_all_sections(self):
        payload = self.build().to_dict()
        assert set(payload) == {"projects", "shared", "conflicts", "ecosystems"}


class TestScanAndBuild:
    def test_scan_project_dedupes(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("rich\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["rich"]\n', encoding="utf-8")
        assert len(dm.scan_project(tmp_path)) == 1

    def test_build_skips_missing_paths(self):
        graph = dm.build([Project(name="ghost", path="/nonexistent/path/xyz")])
        assert graph.by_project == {}

    def test_build_collects_real_project(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("httpx\n", encoding="utf-8")
        graph = dm.build([Project(name="real", path=str(tmp_path))])
        assert "real" in graph.by_project

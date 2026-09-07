"""Tests for the ecosystem drawings."""
import json

from forge import graph, inventory
from forge.models import GitState, Project


def sample():
    inv = inventory.Inventory(generated="2026-09-08T00:00:00+00:00")
    inv.projects = [
        Project(name="core-app", status="GREEN", category="CORE", stack="python",
                languages=["Python"], file_count=30, has_readme=True,
                repository="https://github.com/u/core-app",
                git=GitState(repo=True, remote="https://github.com/u/core-app")),
        Project(name="ManosAbiertas", status="YELLOW", category="PRODUCTS",
                stack="node", languages=["TypeScript"], frozen=True, file_count=12,
                git=GitState(repo=True)),
    ]
    inv.orphans = [{"name": "abandoned-repo"}]
    inv.duplicates = {"open-school": ["/a/open-school", "/b/apps/open-school"]}
    return inv


class TestAsciiTree:
    def test_lists_every_project(self):
        text = graph.ascii_tree(sample())
        assert "core-app" in text
        assert "ManosAbiertas" in text

    def test_marks_frozen(self):
        assert "[FROZEN]" in graph.ascii_tree(sample())

    def test_uses_status_marks(self):
        text = graph.ascii_tree(sample())
        assert "+ core-app" in text
        assert "legend:" in text

    def test_groups_by_category(self):
        text = graph.ascii_tree(sample())
        assert "CORE (1)" in text
        assert "PRODUCTS (1)" in text


class TestPipeline:
    def test_names_each_stage(self):
        text = graph.ascii_pipeline()
        for stage in ("scanner", "classifier", "verifier", "inventory", "repairer"):
            assert stage in text


class TestMermaid:
    def test_ecosystem_is_fenced(self):
        text = graph.mermaid_ecosystem(sample())
        assert text.startswith("```mermaid")
        assert text.rstrip().endswith("```")

    def test_ecosystem_has_category_nodes(self):
        assert "CORE" in graph.mermaid_ecosystem(sample())

    def test_status_pie_counts(self):
        text = graph.mermaid_status(sample())
        assert '"GREEN" : 1' in text
        assert "pie showData" in text

    def test_dependencies_render_without_map(self):
        assert graph.mermaid_dependencies(sample()).startswith("```mermaid")


class TestRepositoryGraph:
    def test_node_per_project(self):
        assert len(graph.repository_graph(sample())["nodes"]) == 2

    def test_remote_edge_created(self):
        edges = graph.repository_graph(sample())["edges"]
        assert any(e["kind"] == "remote" for e in edges)

    def test_duplicate_paths_become_edges(self):
        edges = graph.repository_graph(sample())["edges"]
        dupes = [e for e in edges if e["kind"] == "duplicate_path"]
        assert len(dupes) == 2

    def test_orphans_listed(self):
        assert graph.repository_graph(sample())["orphan_github_repos"] == \
            ["abandoned-repo"]


class TestTechStackMap:
    def test_counts_stacks(self):
        payload = graph.tech_stack_map(sample())
        assert payload["stack_counts"]["python"] == 1
        assert payload["stack_counts"]["node"] == 1

    def test_counts_languages(self):
        payload = graph.tech_stack_map(sample())
        assert payload["language_counts"]["Python"] == 1

    def test_groups_projects_by_stack(self):
        payload = graph.tech_stack_map(sample())
        assert payload["projects_by_stack"]["python"] == ["core-app"]


class TestSkillsMap:
    def test_has_route_per_intent(self):
        payload = graph.skills_map(sample())
        assert "SECURITY" in payload["routes"]
        assert "coverage" in payload

    def test_frontend_route_is_blocked(self):
        assert graph.skills_map(sample())["routes"]["FRONTEND"]["blocked"]


class TestGenerateAll:
    def test_writes_every_artifact(self, tmp_path):
        paths = graph.generate_all(sample(), tmp_path)
        names = {p.name for p in paths}
        assert names == {"REPOSITORY_GRAPH.json", "TECH_STACK_MAP.json",
                         "SKILLS_MAP.json", "DEPENDENCY_MAP.json",
                         "ECOSYSTEM_TREE.txt", "DIAGRAMS.md"}

    def test_json_artifacts_parse(self, tmp_path):
        for path in graph.generate_all(sample(), tmp_path):
            if path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))

    def test_diagrams_contain_mermaid_and_ascii(self, tmp_path):
        paths = {p.name: p for p in graph.generate_all(sample(), tmp_path)}
        text = paths["DIAGRAMS.md"].read_text(encoding="utf-8")
        assert "```mermaid" in text
        assert "BELENTANI ECOSYSTEM" in text

    def test_output_is_deterministic(self, tmp_path):
        first = {p.name: p.read_text(encoding="utf-8")
                 for p in graph.generate_all(sample(), tmp_path / "a")}
        second = {p.name: p.read_text(encoding="utf-8")
                  for p in graph.generate_all(sample(), tmp_path / "b")}
        assert first == second

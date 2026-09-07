import os
import tempfile
from pathlib import Path

from forge.models import Project, GitState, Issue, Status, Priority


def _make_projects():
    return [
        Project(
            name="green-proj", status=Status.GREEN.value, category="CORE",
            has_readme=True, has_license=True, has_gitignore=True,
            has_tests=True, has_ci=True, file_count=20, stack="python",
            git=GitState(repo=True, remote="https://github.com/x/y", dirty=0),
        ),
        Project(
            name="yellow-proj", status=Status.YELLOW.value, category="DUCK",
            has_readme=True, file_count=5, stack="node",
            issues=["P4_TESTS_DOCS: No tests"],
            git=GitState(repo=True, remote="https://github.com/x/z", dirty=2),
        ),
        Project(
            name="ManosAbiertas", status=Status.YELLOW.value, category="PRODUCTS",
            frozen=True, has_readme=False, file_count=100,
            git=GitState(repo=True, remote="https://github.com/x/m", dirty=50),
        ),
    ]


def test_generate_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr("forge.config.REPORTS_DIR", tmp_path)
    from forge.reporter import generate_inventory
    projects = _make_projects()
    path = generate_inventory(projects)
    assert path.exists()
    assert path.name == "PROJECT_INVENTORY.json"
    import json
    data = json.loads(path.read_text())
    assert len(data) == 3
    assert data[0]["name"] == "green-proj"


def test_generate_status_report(tmp_path, monkeypatch):
    monkeypatch.setattr("forge.config.REPORTS_DIR", tmp_path)
    from forge.reporter import generate_status_report
    projects = _make_projects()
    github_repos = [{"name": "x", "archived": False}]
    orphans = [{"name": "orphan-repo"}]
    all_issues = [Issue("yellow-proj", Priority.P4.value, "No tests")]

    path = generate_status_report(projects, github_repos, orphans, all_issues)
    assert path.exists()
    content = path.read_text()
    assert "green-proj" in content
    assert "yellow-proj" in content
    assert "FROZEN" in content
    assert "ManosAbiertas" in content


def test_generate_ecosystem_map(tmp_path, monkeypatch):
    monkeypatch.setattr("forge.config.REPORTS_DIR", tmp_path)
    from forge.reporter import generate_ecosystem_map
    projects = _make_projects()
    path = generate_ecosystem_map(projects)
    assert path.exists()
    content = path.read_text()
    assert "BELENTANI ECOSYSTEM" in content
    assert "CORE" in content


def test_generate_forge_report(tmp_path, monkeypatch):
    monkeypatch.setattr("forge.config.REPORTS_DIR", tmp_path)
    from forge.reporter import generate_forge_report
    projects = _make_projects()
    github_repos = [{"name": "a", "archived": False}]
    all_issues = [Issue("p", Priority.P4.value, "x")]

    path = generate_forge_report(projects, github_repos, all_issues, ["file1.json"])
    assert path.exists()
    content = path.read_text()
    assert "FORGE REPORT" in content
    assert "GREEN" in content
    assert (tmp_path / "FORGE_REPORT.json").exists()

import json
import tempfile
from pathlib import Path

from forge.scanner import (
    load_local_scan, load_github_scan,
    match_local_to_github, find_orphan_github_repos,
)


def test_load_local_scan_empty(tmp_path):
    assert load_local_scan(tmp_path / "nope.json") == []


def test_load_local_scan_valid(tmp_path):
    data = [
        {
            "name": "my-project",
            "path": "/some/path",
            "remote": "https://github.com/user/my-project",
            "stack": "python",
            "tests": True,
            "readme": True,
            "ci": False,
            "docker": False,
            "envExample": False,
            "license": True,
            "gitignore": True,
            "files": 42,
            "branch": "main",
            "dirty": 3,
            "lastCommit": "abc123",
        }
    ]
    f = tmp_path / "scan.json"
    f.write_text(json.dumps(data))

    projects = load_local_scan(f)
    assert len(projects) == 1
    p = projects[0]
    assert p.name == "my-project"
    assert p.has_tests is True
    assert p.has_ci is False
    assert p.file_count == 42
    assert p.git.dirty == 3


def test_load_github_scan_empty(tmp_path):
    assert load_github_scan(tmp_path / "nope.json") == []


def test_load_github_scan_valid(tmp_path):
    data = [
        {
            "name": "repo-a",
            "url": "https://github.com/user/repo-a",
            "isArchived": False,
            "visibility": "PUBLIC",
            "pushedAt": "2026-01-01",
            "primaryLanguage": {"name": "Python"},
            "description": "test",
        },
        {
            "name": "repo-b",
            "url": "https://github.com/user/repo-b",
            "isArchived": True,
            "visibility": "PRIVATE",
            "pushedAt": "2025-06-01",
            "primaryLanguage": None,
            "description": "",
        },
    ]
    f = tmp_path / "gh.json"
    f.write_text(json.dumps(data))

    repos = load_github_scan(f)
    assert len(repos) == 2
    assert repos[0]["language"] == "Python"
    assert repos[1]["archived"] is True
    assert repos[1]["language"] == ""


def test_match_local_to_github():
    from forge.models import Project, GitState
    local = [
        Project(name="repo-a", git=GitState(remote="https://github.com/user/repo-a")),
        Project(name="repo-c", git=GitState(remote="none")),
    ]
    github = [
        {"name": "repo-a", "url": "https://github.com/user/repo-a",
         "archived": False, "visibility": "PUBLIC", "language": "Python"},
        {"name": "repo-b", "url": "https://github.com/user/repo-b",
         "archived": False, "visibility": "PRIVATE", "language": ""},
    ]
    result = match_local_to_github(local, github)
    assert result[0].repository == "https://github.com/user/repo-a"
    assert result[0].visibility == "PUBLIC"
    assert result[1].repository == ""


def test_find_orphan_github_repos():
    from forge.models import Project, GitState
    local = [
        Project(name="repo-a", git=GitState(remote="https://github.com/user/repo-a")),
    ]
    github = [
        {"name": "repo-a", "url": "https://github.com/user/repo-a"},
        {"name": "repo-orphan", "url": "https://github.com/user/repo-orphan"},
    ]
    orphans = find_orphan_github_repos(local, github)
    assert len(orphans) == 1
    assert orphans[0]["name"] == "repo-orphan"

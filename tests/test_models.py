from forge.models import (
    Project, GitState, Issue, ForgeReport,
    Status, Classification, Priority, Category,
)


def test_project_default_status():
    p = Project(name="test-proj")
    assert p.status == Status.BLACK.value
    assert p.classification == Classification.UNKNOWN.value


def test_project_score_empty():
    p = Project(name="empty")
    assert p.score() == 10  # dirty==0 gives 10 points even on empty project


def test_project_score_full():
    p = Project(
        name="full",
        has_readme=True,
        has_license=True,
        has_gitignore=True,
        has_ci=True,
        has_tests=True,
        has_env_example=True,
        has_docker=True,
        file_count=10,
        stack="python",
        status=Status.GREEN.value,
        git=GitState(repo=True, remote="https://github.com/x/y", dirty=0),
    )
    assert p.score() >= 80


def test_project_score_dirty_penalty():
    clean = Project(name="a", git=GitState(repo=True, dirty=0))
    dirty = Project(name="b", git=GitState(repo=True, dirty=5))
    assert clean.score() > dirty.score()


def test_project_to_dict():
    p = Project(name="x", stack="python")
    d = p.to_dict()
    assert d["name"] == "x"
    assert d["stack"] == "python"
    assert isinstance(d["git"], dict)


def test_git_state_defaults():
    g = GitState()
    assert g.repo is False
    assert g.dirty == 0
    assert g.remote == "none"


def test_issue_creation():
    i = Issue(project="proj", priority=Priority.P4.value, description="no tests")
    assert i.project == "proj"
    assert not i.resolved


def test_forge_report_to_dict():
    r = ForgeReport(timestamp="2026-01-01", repos_scanned_local=5)
    d = r.to_dict()
    assert d["repos_scanned_local"] == 5
    assert d["frontend_modified"] == 0


def test_enums_are_strings():
    assert Status.GREEN == "GREEN"
    assert Classification.ACTIVE == "ACTIVE"
    assert Priority.P0 == "P0_SECURITY"
    assert Category.CORE == "CORE"

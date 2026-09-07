from forge.models import Project, GitState, Status, Classification, Priority
from forge.classifier import (
    categorize, classify_status, classify_type, is_frozen,
    assign_priority, classify_all,
)


def _proj(name="test", **kw):
    defaults = dict(
        has_readme=True, has_license=True, has_gitignore=True,
        has_ci=True, has_tests=True, has_env_example=True,
        file_count=10,
        git=GitState(repo=True, remote="https://github.com/x/y", dirty=0),
    )
    defaults.update(kw)
    return Project(name=name, **defaults)


def test_categorize_core():
    p = _proj(name="belentani-omega-core")
    assert categorize(p) == "CORE"


def test_categorize_duck():
    p = _proj(name="duck-ecosystem")
    assert categorize(p) == "DUCK"


def test_categorize_unknown():
    p = _proj(name="random-thing")
    assert categorize(p) == "UNKNOWN"


def test_classify_status_green():
    p = _proj()
    status, issues = classify_status(p)
    assert status == Status.GREEN.value
    assert len(issues) == 0


def test_classify_status_yellow_missing_readme():
    p = _proj(has_readme=False)
    status, issues = classify_status(p)
    assert status == Status.YELLOW.value
    assert any("README" in i.description for i in issues)


def test_classify_status_red_empty():
    p = _proj(file_count=0)
    status, issues = classify_status(p)
    assert status == Status.RED.value


def test_classify_status_yellow_no_remote():
    p = _proj(git=GitState(repo=True, remote="none", dirty=0))
    status, issues = classify_status(p)
    assert status == Status.YELLOW.value


def test_classify_status_dirty():
    p = _proj(git=GitState(repo=True, remote="https://x", dirty=100))
    status, issues = classify_status(p)
    assert any("dirty" in i.description.lower() for i in issues)


def test_classify_type_archived():
    p = _proj(archived=True)
    assert classify_type(p) == Classification.ARCHIVED.value


def test_classify_type_backup():
    p = _proj(name="my-backup-repo")
    assert classify_type(p) == Classification.BACKUP.value


def test_classify_type_template():
    p = _proj(name="next-template")
    assert classify_type(p) == Classification.TEMPLATE.value


def test_classify_type_active():
    p = _proj()
    assert classify_type(p) == Classification.ACTIVE.value


def test_classify_type_experiment():
    p = _proj(file_count=0)
    assert classify_type(p) == Classification.EXPERIMENT.value


def test_is_frozen():
    assert is_frozen(_proj(name="ManosAbiertas"))
    assert is_frozen(_proj(name="secure-t"))
    assert not is_frozen(_proj(name="random-project"))


def test_assign_priority_empty():
    assert assign_priority([]) == ""


def test_assign_priority_highest():
    from forge.models import Issue
    issues = [
        Issue("p", Priority.P4.value, "no tests"),
        Issue("p", Priority.P1.value, "empty"),
    ]
    assert assign_priority(issues) == Priority.P1.value


def test_classify_all():
    projects = [_proj(name="belentani-core"), _proj(name="duck-hub")]
    all_issues = classify_all(projects)
    assert projects[0].category == "CORE"
    assert projects[1].category == "DUCK"
    assert isinstance(all_issues, list)

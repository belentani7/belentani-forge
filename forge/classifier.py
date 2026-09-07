"""Classifier — assigns category, status, classification, priority."""
from .models import Project, Status, Classification, Category, Priority, Issue
from . import config


def categorize(project: Project) -> str:
    name_lower = project.name.lower()
    path_lower = project.path.lower()

    for cat, patterns in config.CATEGORY_PATTERNS.items():
        for pat in patterns:
            if pat.lower() in name_lower or pat.lower() in path_lower:
                return cat
    return Category.UNKNOWN.value


def classify_status(project: Project) -> tuple:
    issues = []

    if not project.has_readme:
        issues.append(Issue(project.name, Priority.P4.value, "Missing README.md"))
    if not project.has_gitignore:
        issues.append(Issue(project.name, Priority.P5.value, "Missing .gitignore"))
    if not project.has_license:
        issues.append(Issue(project.name, Priority.P5.value, "Missing LICENSE"))
    if not project.has_env_example:
        issues.append(Issue(project.name, Priority.P4.value, "Missing .env.example"))
    if not project.has_tests:
        issues.append(Issue(project.name, Priority.P4.value, "No tests directory"))
    if not project.has_ci:
        issues.append(Issue(project.name, Priority.P4.value, "No CI/CD workflows"))
    if project.git.dirty > 50:
        issues.append(Issue(project.name, Priority.P5.value,
                            f"Very dirty git state: {project.git.dirty} uncommitted files"))
    elif project.git.dirty > 0:
        issues.append(Issue(project.name, Priority.P5.value,
                            f"Dirty git state: {project.git.dirty} uncommitted files"))
    if project.git.remote == "none":
        issues.append(Issue(project.name, Priority.P3.value, "No git remote configured"))
    if project.file_count == 0:
        issues.append(Issue(project.name, Priority.P1.value, "Empty project (0 files)"))

    critical = [i for i in issues if i.priority in (Priority.P0.value, Priority.P1.value)]
    warnings = [i for i in issues if i.priority in (Priority.P2.value, Priority.P3.value)]

    if critical:
        status = Status.RED.value
    elif warnings or len(issues) > 3:
        status = Status.YELLOW.value
    elif not issues:
        status = Status.GREEN.value
    else:
        status = Status.YELLOW.value

    return status, issues


def classify_type(project: Project) -> str:
    if project.archived:
        return Classification.ARCHIVED.value
    if project.file_count == 0:
        return Classification.EXPERIMENT.value
    if "backup" in project.name.lower() or "bak" in project.name.lower():
        return Classification.BACKUP.value
    if "template" in project.name.lower():
        return Classification.TEMPLATE.value
    if project.git.dirty == 0 and project.has_readme and project.git.remote != "none":
        return Classification.ACTIVE.value
    return Classification.UNKNOWN.value


def is_frozen(project: Project) -> bool:
    return project.name in config.FROZEN_FRONTEND


def assign_priority(issues: list) -> str:
    if not issues:
        return ""
    for p in [Priority.P0, Priority.P1, Priority.P2, Priority.P3,
              Priority.P4, Priority.P5, Priority.P6]:
        if any(i.priority == p.value for i in issues):
            return p.value
    return Priority.P6.value


def classify_all(projects: list) -> list:
    all_issues = []
    for p in projects:
        p.category = categorize(p)
        p.status, issues = classify_status(p)
        p.classification = classify_type(p)
        p.frozen = is_frozen(p)
        p.issues = [f"{i.priority}: {i.description}" for i in issues]
        p.priority = assign_priority(issues)
        all_issues.extend(issues)
    return all_issues

"""Scanner — reads scan data and builds Project objects."""
import json
from pathlib import Path
from .models import Project, GitState
from . import config


def load_local_scan(path: Path = None) -> list:
    src = path or config.SCAN_LOCAL
    if not src.exists():
        return []
    with open(src, "r", encoding="utf-8") as f:
        raw = json.load(f)

    projects = []
    for r in raw:
        p = Project(
            name=r["name"],
            path=r.get("path", ""),
            repository=r.get("remote", "none"),
            stack=r.get("stack", ""),
            has_tests=r.get("tests", False),
            has_readme=r.get("readme", False),
            has_ci=r.get("ci", False),
            has_docker=r.get("docker", False),
            has_env_example=r.get("envExample", False),
            has_license=r.get("license", False),
            has_gitignore=r.get("gitignore", False),
            file_count=r.get("files", 0),
            git=GitState(
                repo=True,
                branch=r.get("branch", ""),
                dirty=r.get("dirty", 0),
                remote=r.get("remote", "none"),
                last_commit=r.get("lastCommit", ""),
            ),
        )
        projects.append(p)
    return projects


def load_github_scan(path: Path = None) -> list:
    src = path or config.SCAN_GITHUB
    if not src.exists():
        return []
    with open(src, "r", encoding="utf-8") as f:
        raw = json.load(f)

    repos = []
    for r in raw:
        repos.append({
            "name": r.get("name", ""),
            "url": r.get("url", ""),
            "archived": r.get("isArchived", False),
            "visibility": r.get("visibility", "").upper(),
            "pushed_at": r.get("pushedAt", ""),
            "language": (r.get("primaryLanguage") or {}).get("name", ""),
            "description": r.get("description", ""),
        })
    return repos


def match_local_to_github(local_projects, github_repos):
    gh_by_url = {}
    gh_by_name = {}
    for r in github_repos:
        url = r["url"].rstrip("/")
        gh_by_url[url] = r
        gh_by_url[url + ".git"] = r
        gh_by_name[r["name"].lower()] = r

    for p in local_projects:
        remote = p.git.remote.rstrip("/").rstrip(".git")
        gh = gh_by_url.get(p.git.remote) or gh_by_url.get(remote) or gh_by_name.get(p.name.lower())
        if gh:
            p.repository = gh["url"]
            p.visibility = gh["visibility"]
            p.archived = gh["archived"]
            if gh["language"]:
                p.languages = [gh["language"]]

    return local_projects


def find_orphan_github_repos(local_projects, github_repos):
    local_remotes = set()
    for p in local_projects:
        if p.git.remote and p.git.remote != "none":
            local_remotes.add(p.git.remote.rstrip("/").rstrip(".git"))
            local_remotes.add(p.git.remote.rstrip("/"))

    local_names = {p.name.lower() for p in local_projects}

    orphans = []
    for r in github_repos:
        url = r["url"].rstrip("/")
        if url not in local_remotes and url + ".git" not in local_remotes:
            if r["name"].lower() not in local_names:
                orphans.append(r)
    return orphans

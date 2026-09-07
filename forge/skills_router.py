"""Skills router — pick the few skills a task needs, not all of them.

Loading every installed skill into every task wastes context and degrades the
result. This router maps a task intent to a small ordered set of skills, then
intersects that set with what is actually installed on the machine.

``FRONTEND`` intent resolves to an empty set by design: visual work is frozen
during the engineering phase.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SKILLS_HOME = Path.home() / ".claude" / "skills"


class Intent(str, Enum):
    PROJECT_AUDIT = "PROJECT_AUDIT"
    PYTHON_AUTOMATION = "PYTHON_AUTOMATION"
    SECURITY = "SECURITY"
    BACKEND = "BACKEND"
    DEPLOYMENT = "DEPLOYMENT"
    DOCUMENTATION = "DOCUMENTATION"
    TESTING = "TESTING"
    GIT = "GIT"
    FRONTEND = "FRONTEND"
    UNKNOWN = "UNKNOWN"


# Ordered by usefulness — the first entries matter most.
ROUTES: Dict[Intent, List[str]] = {
    Intent.PROJECT_AUDIT: [
        "investigate-first", "repo-metadata-repair", "git-repo-cleanup",
        "engineering:architecture", "markdown-documentation",
    ],
    Intent.PYTHON_AUTOMATION: [
        "karpathy-coder", "safe-refactor", "powershell-automation",
        "system-environment-vars", "test-driven-development",
    ],
    Intent.SECURITY: [
        "security-review", "user-privacy-protection", "dependency-management",
        "rgdp-studio-compliance",
    ],
    Intent.BACKEND: [
        "backend-expert", "fastapi-backend", "database-schema-prisma",
        "json-schema-design", "test-master",
    ],
    Intent.DEPLOYMENT: [
        "continuous-integration", "deploy-to-vercel", "docker-container-ops",
        "engineering:deploy-checklist", "verification-before-completion",
    ],
    Intent.DOCUMENTATION: [
        "markdown-documentation", "writing-guidelines", "explaining-with-ascii",
        "engineering:documentation", "md-document",
    ],
    Intent.TESTING: [
        "test-driven-development", "test-master", "webapp-testing",
        "systematic-debugging", "verification-before-completion",
    ],
    Intent.GIT: [
        "git-repo-cleanup", "using-git-worktrees", "finishing-a-development-branch",
        "requesting-code-review",
    ],
    # Frozen this phase — deliberately empty.
    Intent.FRONTEND: [],
    Intent.UNKNOWN: ["investigate-first"],
}

KEYWORDS: Dict[Intent, Sequence[str]] = {
    Intent.PROJECT_AUDIT: ("audit", "inventory", "scan", "classify", "map",
                           "organize", "auditoria", "inventario", "organizar"),
    Intent.PYTHON_AUTOMATION: ("python", "script", "automate", "pipeline",
                               "refactor", "automatizar"),
    Intent.SECURITY: ("security", "secret", "credential", "vulnerab", "leak",
                      "seguridad", "secreto", "gitleaks"),
    Intent.BACKEND: ("backend", "api", "endpoint", "database", "fastapi",
                     "server", "sql", "base de datos"),
    Intent.DEPLOYMENT: ("deploy", "ci", "cd", "docker", "vercel", "release",
                        "publish", "despliegue"),
    Intent.DOCUMENTATION: ("document", "readme", "docs", "write", "explain",
                           "documenta", "escribir"),
    Intent.TESTING: ("test", "pytest", "coverage", "verify", "prueba", "verificar"),
    Intent.GIT: ("git", "commit", "branch", "merge", "rebase", "push", "rama"),
    Intent.FRONTEND: ("frontend", "css", "html", "gsap", "animation", "landing",
                      "shader", "webgl", "three", "tailwind", "visual", "diseño"),
}


@dataclass
class Route:
    intent: Intent
    skills: List[str] = field(default_factory=list)
    available: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    blocked: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "skills": self.skills,
            "available": self.available,
            "missing": self.missing,
            "blocked": self.blocked,
            "reason": self.reason,
        }


def installed_skills(root: Optional[Path] = None) -> List[str]:
    """Names of directory-installed skills on this machine."""
    home = root or SKILLS_HOME
    if not home.exists():
        return []
    return sorted(p.name for p in home.iterdir() if p.is_dir())


def is_namespaced(skill: str) -> bool:
    """True for plugin-provided skills such as ``engineering:architecture``.

    These are supplied by a plugin rather than installed as a directory, so
    a filesystem scan cannot see them and must not call them missing.
    """
    return ":" in skill


def detect_intent(task: str) -> Intent:
    """Classify a free-text task description into an :class:`Intent`.

    Frontend keywords win over everything else so visual work is always caught
    and blocked rather than silently routed somewhere useful.
    """
    text = task.lower()
    words = set(re.findall(r"[a-zá-ú]+", text))

    if any(k in text for k in KEYWORDS[Intent.FRONTEND]):
        return Intent.FRONTEND

    scores: Dict[Intent, int] = {}
    for intent, keywords in KEYWORDS.items():
        if intent is Intent.FRONTEND:
            continue
        score = sum(1 for k in keywords if k in text or k in words)
        if score:
            scores[intent] = score

    if not scores:
        return Intent.UNKNOWN
    return max(scores.items(), key=lambda kv: kv[1])[0]


def route(task: str, root: Optional[Path] = None, limit: int = 5) -> Route:
    """Resolve *task* to the skills that should be loaded for it."""
    intent = detect_intent(task)
    wanted = ROUTES.get(intent, [])[:limit]

    if intent is Intent.FRONTEND:
        return Route(intent=intent, blocked=True,
                     reason="frontend is frozen this phase — document, do not modify")

    present = set(installed_skills(root))
    return Route(
        intent=intent,
        skills=wanted,
        available=[s for s in wanted if s in present or is_namespaced(s)],
        missing=[s for s in wanted if s not in present and not is_namespaced(s)],
    )


def route_all(tasks: Sequence[str], root: Optional[Path] = None) -> List[Route]:
    return [route(t, root=root) for t in tasks]


def coverage(root: Optional[Path] = None) -> Dict[str, object]:
    """How much of the routing table is actually installed."""
    present = set(installed_skills(root))
    referenced = {s for skills in ROUTES.values() for s in skills}
    namespaced = {s for s in referenced if is_namespaced(s)}
    return {
        "installed_total": len(present),
        "referenced": len(referenced),
        "available": sorted((referenced & present) | namespaced),
        "missing": sorted(referenced - present - namespaced),
        "plugin_provided": sorted(namespaced),
    }

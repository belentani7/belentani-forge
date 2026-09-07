"""Graph — draws the ecosystem instead of only describing it.

Emits the artifacts the FORGE spec asks for: a repository graph, a tech-stack
matrix, a skill-routing map, Mermaid diagrams and ASCII trees. Everything is
generated from the inventory, so a diagram can never drift from the data.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from . import config, skills_router
from .safety import redact

STATUS_MARK = {"GREEN": "+", "YELLOW": "~", "RED": "!", "BLACK": "?"}


def _write(name: str, text: str, directory: Optional[Path] = None) -> Path:
    target = (directory or config.REPORTS_DIR) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(redact(text), encoding="utf-8")
    return target


def _dump(name: str, payload: dict, directory: Optional[Path] = None) -> Path:
    return _write(name, json.dumps(payload, indent=2, sort_keys=True, default=str),
                  directory)


# ------------------------------------------------------------------ ASCII
def ascii_tree(inv) -> str:
    """Category tree with a status mark per project."""
    lines = ["BELENTANI ECOSYSTEM", "|"]
    grouped = inv.by_category()
    by_name = {p.name: p for p in inv.projects}

    cats = sorted(grouped)
    for ci, cat in enumerate(cats):
        last_cat = ci == len(cats) - 1
        lines.append("%s-- %s (%d)" % ("`" if last_cat else "+", cat, len(grouped[cat])))
        pad = "    " if last_cat else "|   "
        names = grouped[cat]
        for ni, name in enumerate(names):
            project = by_name.get(name)
            mark = STATUS_MARK.get(project.status if project else "", "?")
            frozen = "  [FROZEN]" if project and project.frozen else ""
            branch = "`--" if ni == len(names) - 1 else "+--"
            lines.append("%s%s %s %s%s" % (pad, branch, mark, name, frozen))
        if not last_cat:
            lines.append("|")

    lines += ["", "legend: + green   ~ yellow   ! red   ? unknown"]
    return "\n".join(lines)


def ascii_pipeline() -> str:
    return "\n".join([
        "FORGE PIPELINE",
        "",
        "   scan JSON        GitHub",
        "       |               |",
        "       +-------+-------+",
        "               v",
        "           scanner            load + cross-reference",
        "               v",
        "          classifier          status / category / priority",
        "               v",
        "           verifier           definition of done",
        "               v",
        "       dependency_map         manifests + conflicts",
        "               v",
        "        project_state         idempotent fingerprints",
        "               v",
        "          inventory           the decided ecosystem",
        "               |",
        "       +-------+-------+",
        "       v               v",
        "  skills_router     reporter",
        "       v               v",
        "   repair plan      reports",
        "       v",
        "    repairer          create-only, --apply gated",
    ])


# ---------------------------------------------------------------- Mermaid
def mermaid_ecosystem(inv) -> str:
    lines = ["```mermaid", "graph TD", "    ROOT[BELENTANI ECOSYSTEM]"]
    for cat, names in inv.by_category().items():
        cid = cat.replace("-", "_")
        lines.append('    ROOT --> %s["%s<br/>%d projects"]' % (cid, cat, len(names)))
    lines.append("```")
    return "\n".join(lines)


def mermaid_status(inv) -> str:
    counts = {k: v for k, v in inv.by_status().items() if v}
    lines = ["```mermaid", "pie showData", '    title Project status']
    for status, count in counts.items():
        lines.append('    "%s" : %d' % (status, count))
    lines.append("```")
    return "\n".join(lines)


def mermaid_dependencies(inv, minimum: int = 6) -> str:
    """Shared dependencies as a bipartite graph, limited to the hubs."""
    lines = ["```mermaid", "graph LR"]
    if inv.dependencies:
        for key, users in list(inv.dependencies.shared(minimum=minimum).items())[:12]:
            dep = key.split(":", 1)[-1]
            node = "D_" + dep.replace("-", "_").replace("@", "").replace("/", "_").replace(".", "_")
            lines.append('    %s(["%s<br/>%d projects"])' % (node, dep, len(users)))
    lines.append("```")
    return "\n".join(lines)


# ----------------------------------------------------------------- payloads
def repository_graph(inv) -> dict:
    nodes, edges = [], []
    for p in inv.projects:
        nodes.append({"id": p.name, "path": p.path, "category": p.category,
                      "status": p.status, "stack": p.stack, "frozen": p.frozen,
                      "score": p.score()})
        if p.repository:
            edges.append({"from": p.name, "to": p.repository, "kind": "remote"})

    for name, paths in (inv.duplicates or {}).items():
        for path in paths:
            edges.append({"from": name, "to": path, "kind": "duplicate_path"})

    return {
        "generated": inv.generated,
        "nodes": nodes,
        "edges": edges,
        "orphan_github_repos": [r["name"] for r in inv.orphans],
        "categories": inv.by_category(),
    }


def tech_stack_map(inv) -> dict:
    stacks = Counter(p.stack or "unknown" for p in inv.projects)
    languages = Counter(lang for p in inv.projects for lang in p.languages)
    by_stack: Dict[str, List[str]] = defaultdict(list)
    for p in inv.projects:
        by_stack[p.stack or "unknown"].append(p.name)

    return {
        "generated": inv.generated,
        "stack_counts": dict(stacks.most_common()),
        "language_counts": dict(languages.most_common()),
        "projects_by_stack": {k: sorted(v) for k, v in sorted(by_stack.items())},
        "ecosystems": inv.dependencies.ecosystems() if inv.dependencies else {},
    }


def skills_map(inv) -> dict:
    routes = {}
    for intent, skills in skills_router.ROUTES.items():
        route = skills_router.route(intent.value.replace("_", " ").lower())
        routes[intent.value] = {
            "skills": skills,
            "available": route.available,
            "missing": route.missing,
            "blocked": route.blocked,
        }
    return {
        "generated": inv.generated,
        "coverage": skills_router.coverage(),
        "routes": routes,
    }


# ------------------------------------------------------------------ writer
def generate_all(inv, directory: Optional[Path] = None) -> List[Path]:
    """Write every graph artifact and return the paths."""
    diagrams = "\n\n".join([
        "# BELENTANI ECOSYSTEM DIAGRAMS",
        "_Generated %s — do not edit by hand._" % inv.generated,
        "## Categories", mermaid_ecosystem(inv),
        "## Status", mermaid_status(inv),
        "## Shared dependencies", mermaid_dependencies(inv),
        "## Pipeline", "```\n%s\n```" % ascii_pipeline(),
        "## Tree", "```\n%s\n```" % ascii_tree(inv),
    ])

    return [
        _dump("REPOSITORY_GRAPH.json", repository_graph(inv), directory),
        _dump("TECH_STACK_MAP.json", tech_stack_map(inv), directory),
        _dump("SKILLS_MAP.json", skills_map(inv), directory),
        _dump("DEPENDENCY_MAP.json",
              inv.dependencies.to_dict() if inv.dependencies else {}, directory),
        _write("ECOSYSTEM_TREE.txt", ascii_tree(inv), directory),
        _write("DIAGRAMS.md", diagrams, directory),
    ]

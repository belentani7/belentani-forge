"""Reporter — generates inventory, maps, and reports."""
import json
from datetime import datetime
from pathlib import Path
from .models import Project, ForgeReport, Status
from . import config


def save_json(data, filename: str) -> Path:
    path = config.REPORTS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    return path


def generate_inventory(projects: list) -> Path:
    inv = [p.to_dict() for p in projects]
    return save_json(inv, "PROJECT_INVENTORY.json")


def generate_status_report(projects: list, github_repos: list,
                           orphans: list, all_issues: list) -> Path:
    green = [p for p in projects if p.status == Status.GREEN.value]
    yellow = [p for p in projects if p.status == Status.YELLOW.value]
    red = [p for p in projects if p.status == Status.RED.value]
    black = [p for p in projects if p.status == Status.BLACK.value]
    frozen = [p for p in projects if p.frozen]

    lines = [
        "# BELENTANI FORGE — PROJECT STATUS",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "## Summary",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Local repos scanned | {len(projects)} |",
        f"| GitHub repos | {len(github_repos)} |",
        f"| GitHub archived | {sum(1 for r in github_repos if r['archived'])} |",
        f"| Orphan GitHub repos (no local) | {len(orphans)} |",
        f"| GREEN | {len(green)} |",
        f"| YELLOW | {len(yellow)} |",
        f"| RED | {len(red)} |",
        f"| BLACK | {len(black)} |",
        f"| FROZEN (no frontend touch) | {len(frozen)} |",
        f"| Total issues | {len(all_issues)} |",
        f"| Frontend modified | 0 |",
        "",
    ]

    lines.append(f"## GREEN Projects ({len(green)})")
    for p in sorted(green, key=lambda x: x.name):
        lines.append(f"- **{p.name}** [{p.category}] score={p.score()} files={p.file_count}")

    lines.append(f"\n## YELLOW Projects ({len(yellow)})")
    for p in sorted(yellow, key=lambda x: x.name):
        issues_str = ", ".join(p.issues[:3]) if p.issues else "minor"
        lines.append(f"- **{p.name}** [{p.category}] score={p.score()} — {issues_str}")

    lines.append(f"\n## RED Projects ({len(red)})")
    for p in sorted(red, key=lambda x: x.name):
        issues_str = ", ".join(p.issues[:3]) if p.issues else "critical"
        lines.append(f"- **{p.name}** [{p.category}] score={p.score()} — {issues_str}")

    lines.append(f"\n## FROZEN (frontend untouchable)")
    for p in frozen:
        lines.append(f"- **{p.name}**")

    lines.append(f"\n## Repair Queue")
    for prio in ["P0_SECURITY", "P1_NOT_EXECUTABLE", "P2_BACKEND_BROKEN",
                 "P3_TOOLING_BROKEN", "P4_TESTS_DOCS", "P5_ORGANIZATION"]:
        prio_issues = [i for i in all_issues if i.priority == prio]
        if prio_issues:
            lines.append(f"\n### {prio} ({len(prio_issues)})")
            for i in prio_issues[:20]:
                lines.append(f"- [{i.project}] {i.description}")

    lines.append(f"\n## Category Map")
    cats = {}
    for p in projects:
        cats.setdefault(p.category, []).append(p.name)
    for cat, names in sorted(cats.items()):
        lines.append(f"\n### {cat} ({len(names)})")
        for n in sorted(names):
            lines.append(f"- {n}")

    lines.append(f"\n## Tech Stack Map")
    stacks = {}
    for p in projects:
        s = p.stack or "unknown"
        stacks.setdefault(s, []).append(p.name)
    for s, names in sorted(stacks.items()):
        lines.append(f"- **{s}**: {', '.join(sorted(names))}")

    dirty = [p for p in projects if p.git.dirty > 0]
    if dirty:
        lines.append(f"\n## Dirty Repos ({len(dirty)})")
        for p in sorted(dirty, key=lambda x: -x.git.dirty):
            lines.append(f"- **{p.name}**: {p.git.dirty} uncommitted files")

    content = "\n".join(lines)
    path = config.REPORTS_DIR / "PROJECT_STATUS.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def generate_ecosystem_map(projects: list) -> Path:
    cats = {}
    for p in projects:
        cats.setdefault(p.category, []).append(p)

    lines = [
        "BELENTANI ECOSYSTEM MAP",
        f"Generated: {datetime.now().isoformat()}",
        f"{len(projects)} projects across {len(cats)} categories",
        "",
        "BELENTANI ECOSYSTEM",
        "|",
    ]
    cat_list = sorted(cats.keys())
    for i, cat in enumerate(cat_list):
        prjs = cats[cat]
        prefix = "+" if i < len(cat_list) - 1 else "`"
        g = sum(1 for p in prjs if p.status == "GREEN")
        y = sum(1 for p in prjs if p.status == "YELLOW")
        r = sum(1 for p in prjs if p.status == "RED")
        lines.append(f"{prefix}-- {cat} ({len(prjs)} projects) [G:{g} Y:{y} R:{r}]")
        for j, p in enumerate(sorted(prjs, key=lambda x: x.name)):
            sub = "|" if i < len(cat_list) - 1 else " "
            connector = "+" if j < len(prjs) - 1 else "`"
            frozen_mark = " FROZEN" if p.frozen else ""
            lines.append(f"{sub}   {connector}-- [{p.status[0]}] {p.name} (score:{p.score()}){frozen_mark}")

    content = "\n".join(lines)
    path = config.REPORTS_DIR / "ECOSYSTEM_MAP.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def generate_forge_report(projects, github_repos, all_issues, files_created) -> Path:
    report = ForgeReport(
        timestamp=datetime.now().isoformat(),
        repos_scanned_local=len(projects),
        repos_scanned_github=len(github_repos),
        projects_green=sum(1 for p in projects if p.status == "GREEN"),
        projects_yellow=sum(1 for p in projects if p.status == "YELLOW"),
        projects_red=sum(1 for p in projects if p.status == "RED"),
        projects_black=sum(1 for p in projects if p.status == "BLACK"),
        issues_found=len(all_issues),
        issues_fixed=0,
        issues_pending=len(all_issues),
        files_created=files_created,
        frontend_modified=0,
    )

    lines = [
        "# BELENTANI FORGE REPORT",
        f"Timestamp: {report.timestamp}",
        "",
        "## Scan Results",
        f"- Repos scanned (local): **{report.repos_scanned_local}**",
        f"- Repos scanned (GitHub): **{report.repos_scanned_github}**",
        f"- GREEN: **{report.projects_green}**",
        f"- YELLOW: **{report.projects_yellow}**",
        f"- RED: **{report.projects_red}**",
        f"- BLACK: **{report.projects_black}**",
        "",
        "## Issues",
        f"- Found: **{report.issues_found}**",
        f"- Fixed: **{report.issues_fixed}**",
        f"- Pending: **{report.issues_pending}**",
        "",
        "## Files Created",
    ]
    for f in files_created:
        lines.append(f"- `{f}`")

    lines.extend([
        "",
        f"## Frontend modified: **{report.frontend_modified}**",
    ])

    content = "\n".join(lines)
    path = config.REPORTS_DIR / "FORGE_REPORT.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    save_json(report.to_dict(), "FORGE_REPORT.json")
    return path

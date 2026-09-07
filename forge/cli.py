"""CLI — pipeline commands on top of the monolithic engine.

New commands (``inventory``, ``plan``, ``verify``, ``deps``, ``skills``,
``caps``) are handled here. Anything else is delegated untouched to
:func:`forge.engine.main`, so every existing command keeps working.

Everything here is read-only. Nothing writes outside ``$FORGE_HOME``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import (__version__, capabilities, config, engine, graph, inventory,
               repairer, skills_router)
from .safety import redact

PIPELINE_COMMANDS = {"inventory", "plan", "verify", "deps", "skills", "caps",
                     "repair", "graph"}


def _out(msg: str = "") -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _emit(payload: dict, as_json: bool, path: Optional[Path] = None) -> None:
    if as_json:
        _out(redact(json.dumps(payload, indent=2, sort_keys=True, default=str)))
    if path:
        _out("written: %s" % path)


# ------------------------------------------------------------------ commands
def cmd_inventory(args) -> int:
    inv = inventory.build(deep=args.deep, track_state=not args.no_state)
    path = inv.save()

    totals = inv.to_dict()["totals"]
    _out("FORGE INVENTORY  %s" % inv.generated)
    _out("-" * 52)
    _out("local projects      %d" % totals["local_projects"])
    _out("github repos        %d" % totals["github_repos"])
    _out("orphan gh repos     %d" % totals["orphan_github_repos"])
    _out("issues              %d" % totals["issues"])
    _out("frozen (untouched)  %d" % totals["frozen"])
    _out("")
    for status, count in inv.by_status().items():
        if count:
            _out("  %-6s %d" % (status, count))
    if inv.state_changes:
        _out("")
        _out("state: %s" % ", ".join("%s=%d" % kv for kv in inv.state_changes.items()))
    if inv.regressions:
        _out("REGRESSIONS: %s" % "; ".join(inv.regressions))
    if inv.duplicates:
        _out("")
        _out("DUPLICATE NAMES  %d" % len(inv.duplicates))
        for name, paths in sorted(inv.duplicates.items()):
            _out("  %s" % name)
            for p in paths:
                _out("      %s" % p)

    _emit(inv.to_dict(), args.json, path)
    return 0


def cmd_plan(args) -> int:
    inv = inventory.build(track_state=False)
    path = inventory.save_plan(inv, limit=args.limit)
    actions = inventory.plan(inv, limit=args.limit)

    _out("REPAIR PLAN  (%d actions, worst priority first)" % len(actions))
    _out("-" * 52)
    for i, action in enumerate(actions, 1):
        _out("%2d. [%s] %s  (score %d)" % (
            i, action["priority"] or "-", action["project"], action["score"]))
        for issue in action["issues"][:3]:
            _out("      %s" % issue)
        if action["skills"]:
            _out("      skills: %s" % ", ".join(action["skills"][:3]))

    _emit({"actions": actions}, args.json, path)
    return 0


def cmd_verify(args) -> int:
    inv = inventory.build(deep=args.deep, track_state=False)
    done = inv.finished()
    todo = inv.needs_work()
    frozen = inv.do_not_touch()

    _out("DEFINITION OF DONE")
    _out("-" * 52)
    _out("FINISHED       %d" % len(done))
    for p in done[:args.limit]:
        _out("  + %-32s %d/100" % (p.name, p.score()))
    _out("NEEDS WORK     %d" % len(todo))
    for p in todo[:args.limit]:
        blockers = next((v.blockers for v in inv.verdicts if v.project == p.name), [])
        _out("  - %-32s %d/100  %s" % (
            p.name, p.score(), ", ".join(b.name for b in blockers[:3])))
    _out("DO NOT TOUCH   %d" % len(frozen))
    for p in frozen[:args.limit]:
        _out("  ! %s" % p.name)

    _emit({"finished": [p.name for p in done],
           "needs_work": [p.name for p in todo],
           "do_not_touch": [p.name for p in frozen]}, args.json)
    return 0


def cmd_deps(args) -> int:
    inv = inventory.build(track_state=False)
    dmap = inv.dependencies
    if dmap is None or not dmap.by_project:
        _out("no dependency manifests found")
        return 0

    shared = dmap.shared(minimum=args.min)
    conflicts = dmap.conflicts()

    _out("DEPENDENCY MAP")
    _out("-" * 52)
    _out("projects with manifests  %d" % len(dmap.by_project))
    _out("ecosystems               %s" % dmap.ecosystems())
    _out("")
    _out("SHARED (used by >= %d projects)" % args.min)
    for key, users in list(shared.items())[:args.limit]:
        _out("  %-34s %d" % (key, len(users)))
    if conflicts:
        _out("")
        _out("VERSION CONFLICTS  %d" % len(conflicts))
        for key, pairs in list(conflicts.items())[:args.limit]:
            versions = sorted({v for _p, v in pairs})
            _out("  %-34s %s" % (key, " | ".join(versions[:4])))

    _emit(dmap.to_dict(), args.json)
    return 0


def cmd_skills(args) -> int:
    if args.task:
        route = skills_router.route(" ".join(args.task))
        _out("intent    %s" % route.intent.value)
        if route.blocked:
            _out("BLOCKED   %s" % route.reason)
            _emit(route.to_dict(), args.json)
            return 0
        _out("available %s" % (", ".join(route.available) or "none"))
        _out("missing   %s" % (", ".join(route.missing) or "none"))
        _emit(route.to_dict(), args.json)
        return 0

    cov = skills_router.coverage()
    _out("SKILL ROUTER COVERAGE")
    _out("-" * 52)
    _out("installed on machine  %d" % cov["installed_total"])
    _out("referenced by router  %d" % cov["referenced"])
    _out("available             %d" % len(cov["available"]))
    _out("missing               %d" % len(cov["missing"]))
    if cov["missing"]:
        _out("")
        _out("not installed: %s" % ", ".join(cov["missing"]))
    _emit(cov, args.json)
    return 0


def cmd_caps(args) -> int:
    caps = capabilities.audit()
    _out("MACHINE CAPABILITIES")
    _out("-" * 52)
    for tool in caps.tools:
        mark = "+" if tool.installed else "-"
        _out("  %s %-10s %s" % (mark, tool.name, tool.version[:48]))
    _out("")
    _out("providers configured  %d  (%s)" % (
        len(caps.providers), ", ".join(sorted(caps.providers)) or "none"))
    _out("local models          %s" % (", ".join(caps.local_models) or "none"))
    _out("delegation target     %s" % (caps.delegation_target() or "none"))

    path = config.REPORTS_DIR / "CAPABILITIES.json"
    path.write_text(redact(json.dumps(caps.to_dict(), indent=2, sort_keys=True)),
                    encoding="utf-8")
    _emit(caps.to_dict(), args.json, path)
    return 0


def cmd_repair(args) -> int:
    inv = inventory.build(track_state=False)
    targets = [p for p in inv.repair_queue()][:args.limit]
    repairs = repairer.repair_all(targets, apply=args.apply, limit=args.limit)
    counts = repairer.summarise(repairs)

    _out("REPAIR  %s" % ("APPLIED" if args.apply else "DRY RUN — nothing written"))
    _out("-" * 52)
    _out("projects considered  %d" % len(targets))
    for outcome, count in sorted(counts.items()):
        _out("  %-16s %d" % (outcome, count))

    work = repairer.actionable(repairs)
    if work:
        _out("")
        current = None
        for r in work:
            if r.project != current:
                current = r.project
                _out("  %s" % current)
            _out("      %-14s %-16s %s" % (r.fix, r.outcome, r.detail))

    path = config.REPORTS_DIR / "REPAIRS.json"
    path.write_text(redact(json.dumps(
        {"applied": args.apply, "summary": counts,
         "repairs": [r.to_dict() for r in repairs]},
        indent=2, sort_keys=True)), encoding="utf-8")

    if not args.apply:
        _out("")
        _out("re-run with --apply to write these files")
    _emit({"summary": counts}, args.json, path)
    return 0


def cmd_graph(args) -> int:
    inv = inventory.build(track_state=False)
    paths = graph.generate_all(inv)

    _out(graph.ascii_tree(inv))
    _out("")
    for p in paths:
        _out("written: %s" % p)
    return 0


# -------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forge",
        description="BELENTANI FORGE — pipeline commands (read-only).")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("inventory", help="scan, classify, verify and persist")
    inv.add_argument("--deep", action="store_true", help="run tests and builds")
    inv.add_argument("--no-state", action="store_true", help="skip state tracking")
    inv.add_argument("--json", action="store_true")
    inv.set_defaults(func=cmd_inventory)

    pl = sub.add_parser("plan", help="prioritised repair queue")
    pl.add_argument("--limit", type=int, default=20)
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_plan)

    ver = sub.add_parser("verify", help="apply the Definition of Done")
    ver.add_argument("--deep", action="store_true")
    ver.add_argument("--limit", type=int, default=15)
    ver.add_argument("--json", action="store_true")
    ver.set_defaults(func=cmd_verify)

    dep = sub.add_parser("deps", help="dependency map and version conflicts")
    dep.add_argument("--min", type=int, default=3)
    dep.add_argument("--limit", type=int, default=25)
    dep.add_argument("--json", action="store_true")
    dep.set_defaults(func=cmd_deps)

    sk = sub.add_parser("skills", help="route a task to skills")
    sk.add_argument("task", nargs="*", help="task description")
    sk.add_argument("--json", action="store_true")
    sk.set_defaults(func=cmd_skills)

    cp = sub.add_parser("caps", help="audit machine tooling and providers")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_caps)

    rp = sub.add_parser("repair", help="close structural gaps (create-only)")
    rp.add_argument("--apply", action="store_true", help="actually write files")
    rp.add_argument("--limit", type=int, default=20)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_repair)

    gr = sub.add_parser("graph", help="draw the ecosystem — JSON, Mermaid, ASCII")
    gr.set_defaults(func=cmd_graph)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Dispatch pipeline commands; delegate everything else to the engine."""
    args: List[str] = list(argv if argv is not None else sys.argv[1:])

    if args and args[0] in PIPELINE_COMMANDS:
        parsed = build_parser().parse_args(args)
        try:
            return int(parsed.func(parsed) or 0)
        except KeyboardInterrupt:
            _out("\ninterrupted")
            return 130

    return engine.main(args)


if __name__ == "__main__":
    raise SystemExit(main())

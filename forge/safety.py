"""Safety — secret redaction, frozen-frontend guard, destructive command blocking.

Every write path in FORGE routes through this module. The rules are hard:

  * secrets are masked before anything reaches a log, report or manifest;
  * frozen frontend paths cannot be written to;
  * destructive git/shell commands are refused unless explicitly authorized.

Nothing here deletes, rotates or rewrites user credentials — detection only.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from . import config

REDACTED = "[SECRET_REDACTED]"

# Same corpus the monolithic engine uses, kept in sync deliberately.
SECRET_PATTERNS = (
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("google_key", re.compile(r"AIza[0-9A-Za-z\-_]{30,}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")),
    ("generic", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*"
        r"['\"][A-Za-z0-9\-_/+]{16,}['\"]")),
)

SECRET_SAFE = re.compile(
    r"(?i)(example|sample|placeholder|your[_-]?key|xxx+|<[^>]+>|changeme|dummy|"
    r"process\.env|os\.environ|getenv|\$\{)")

# Personal identifiers that must never leave the machine in a commit or report.
PRIVATE_IDENTIFIERS = (
    re.compile(r"(?i)[a-z0-9._%+-]+@gmail\.com"),
    re.compile(r"(?i)\b[a-z0-9_-]+-beep\b"),
)

# Visual assets frozen during the engineering phase.
FRONTEND_SUFFIXES = {
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".jsx", ".tsx", ".vue", ".svelte",
    ".glsl", ".frag", ".vert", ".shader",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mov",
}

DESTRUCTIVE_GIT = (
    ("reset", "--hard"),
    ("clean", "-fd"),
    ("clean", "-fdx"),
    ("push", "--force"),
    ("push", "-f"),
    ("push", "--force-with-lease"),
    ("branch", "-D"),
    ("filter-branch",),
)

DESTRUCTIVE_SHELL = ("rm", "rmdir", "del", "format", "mkfs", "dd", "shred")


class SafetyViolation(Exception):
    """Raised when an operation would break a hard safety rule."""


def redact(text: str) -> str:
    """Replace every credential-looking span with ``[SECRET_REDACTED]``.

    Placeholders (``your_key_here``, ``os.environ[...]``) are left intact so
    ``.env.example`` files stay readable.
    """
    if not text:
        return text

    out = text
    for _name, pattern in SECRET_PATTERNS:
        def _sub(match: "re.Match[str]") -> str:
            return match.group(0) if SECRET_SAFE.search(match.group(0)) else REDACTED
        out = pattern.sub(_sub, out)

    for pattern in PRIVATE_IDENTIFIERS:
        out = pattern.sub(REDACTED, out)
    return out


def redact_all(values: Iterable[str]) -> List[str]:
    return [redact(v) for v in values]


def find_secrets(text: str) -> List[Tuple[str, int]]:
    """Return ``(kind, line_number)`` for each real secret found in *text*."""
    hits: List[Tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if SECRET_SAFE.search(line):
            continue
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                hits.append((name, lineno))
                break
    return hits


def is_frontend_path(path) -> bool:
    """True when *path* points at a visual asset frozen for this phase."""
    return Path(path).suffix.lower() in FRONTEND_SUFFIXES


def is_frozen_project(name: str) -> bool:
    return name in config.FROZEN_FRONTEND


def guard_write(path, project_name: Optional[str] = None) -> None:
    """Raise :class:`SafetyViolation` if writing *path* would touch frozen work."""
    p = Path(path)
    if is_frontend_path(p):
        raise SafetyViolation(
            "frontend frozen: refusing to write %s" % p.name)
    if project_name and is_frozen_project(project_name):
        raise SafetyViolation(
            "project '%s' is frozen: refusing to write %s" % (project_name, p.name))


def guard_command(cmd: Sequence[str], authorized: bool = False) -> None:
    """Raise :class:`SafetyViolation` for destructive commands.

    Set *authorized* only when the user has explicitly approved this exact
    operation. There is no global override.
    """
    if not cmd:
        raise SafetyViolation("empty command")

    exe = Path(str(cmd[0])).stem.lower()
    rest = [str(a).lower() for a in cmd[1:]]

    if exe == "git":
        for signature in DESTRUCTIVE_GIT:
            if all(token in rest for token in signature):
                if authorized:
                    return
                raise SafetyViolation(
                    "destructive git command blocked: git %s" % " ".join(signature))
        return

    if exe == "gh":
        # --apply is not authorization to delete, publish or transfer repos.
        dangerous = False
        if rest[:1] == ["repo"] and len(rest) > 1:
            dangerous = rest[1] in {
                "delete", "archive", "create", "fork", "rename", "transfer",
            } or (rest[1] == "edit" and any(
                a == "--visibility" or a.startswith("--visibility=")
                for a in rest[2:]
            ))
        elif rest[:1] == ["auth"]:
            dangerous = len(rest) > 1 and rest[1] in {"logout", "refresh"}
        elif rest[:1] == ["api"]:
            args = rest[1:]
            dangerous = "graphql" in args
            for index, flag in enumerate(args):
                if (
                    flag.startswith("-f")
                    or flag in {"--field", "--raw-field", "--input"}
                    or flag.startswith(("--field=", "--raw-field=", "--input="))
                ):
                    dangerous = True
                if flag in {"-x", "--method"}:
                    if index + 1 >= len(args) or args[index + 1] != "get":
                        dangerous = True
                if flag.startswith("--method=") and flag != "--method=get":
                    dangerous = True
                if flag.startswith("-x") and len(flag) > 2 and flag != "-xget":
                    dangerous = True
        if dangerous and not authorized:
            raise SafetyViolation(
                "state-changing GitHub command requires explicit authorization"
            )
        return

    if exe in DESTRUCTIVE_SHELL and not authorized:
        raise SafetyViolation("destructive shell command blocked: %s" % exe)


def safe_to_commit(paths: Iterable[Path]) -> List[str]:
    """Return human-readable reasons why *paths* must not be committed."""
    problems: List[str] = []
    for path in paths:
        p = Path(path)
        if p.name in (".env", ".env.local", ".env.production"):
            problems.append("%s: environment file must never be committed" % p.name)
            continue
        if p.suffix in (".pem", ".key", ".p12", ".pfx"):
            problems.append("%s: private key material" % p.name)
            continue
        try:
            if p.is_file() and p.stat().st_size < 1_000_000:
                text = p.read_text(encoding="utf-8", errors="replace")
                for kind, lineno in find_secrets(text):
                    problems.append("%s:%d: %s detected" % (p.name, lineno, kind))
        except OSError:
            continue
    return problems

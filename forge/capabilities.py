"""Capabilities — what tooling this machine can actually use.

Detects installed CLIs, configured model providers and local models, so the
router can delegate mechanical work to a cheap or local model instead of
burning tokens on it.

Security: credential VALUES are never read, printed, stored or transmitted.
This module reports only whether a variable is set, plus a masked prefix, and
that masking happens before the value ever reaches a return value.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# CLIs worth knowing about, and what each is good for.
KNOWN_CLIS = {
    "aider": "repo-aware pair programming against any model",
    "opencode": "terminal coding agent",
    "ollama": "local model runtime — zero token cost",
    "llm": "scriptable one-shot model calls",
    "gh": "GitHub API and repo operations",
    "git": "version control",
    "code": "VS Code",
    "python": "orchestration runtime",
    "node": "JS runtime",
    "npm": "JS package manager",
    "docker": "containers",
    "gemini": "Gemini CLI",
    "qwen": "Qwen CLI",
}

# Provider env vars. Names only — values are masked on read.
PROVIDER_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
    "MISTRAL_API_KEY", "TOGETHER_API_KEY", "OPENROUTER_API_KEY",
    "DASHSCOPE_API_KEY", "QWEN_API_KEY", "HF_TOKEN",
    "XAI_API_KEY", "PERPLEXITY_API_KEY",
)

# Work that should be delegated away from an expensive model when possible.
DELEGATABLE = (
    "bulk renames", "import fixes", "docstring generation", "type annotations",
    "test scaffolding", "changelog drafts", "commit messages",
)


def mask(value: str) -> str:
    """Return a non-reversible hint of *value*. Never the value itself."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return "%s…%s" % (value[:4], value[-2:])


@dataclass
class Tool:
    name: str
    installed: bool = False
    version: str = ""
    purpose: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Capabilities:
    generated: str = ""
    tools: List[Tool] = field(default_factory=list)
    providers: Dict[str, str] = field(default_factory=dict)
    local_models: List[str] = field(default_factory=list)

    def installed(self) -> List[str]:
        return [t.name for t in self.tools if t.installed]

    def missing(self) -> List[str]:
        return [t.name for t in self.tools if not t.installed]

    def has_local_inference(self) -> bool:
        return bool(self.local_models)

    def delegation_target(self) -> Optional[str]:
        """Best place to send mechanical work, cheapest first."""
        if self.local_models:
            return "ollama:%s" % self.local_models[0]
        if "aider" in self.installed() and self.providers:
            return "aider"
        return None

    def to_dict(self) -> dict:
        return {
            "generated": self.generated,
            "tools": [t.to_dict() for t in self.tools],
            "providers_configured": sorted(self.providers),
            "providers_masked": self.providers,
            "local_models": self.local_models,
            "delegation_target": self.delegation_target(),
            "delegatable_work": list(DELEGATABLE),
        }


def _version(exe: str) -> str:
    path = shutil.which(exe)
    if not path:
        return ""
    for flag in ("--version", "-v", "version"):
        try:
            proc = subprocess.run([path, flag], capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = (proc.stdout + proc.stderr).decode("utf-8", "replace").strip()
        if text:
            return text.splitlines()[0][:80]
    return "installed"


def detect_tools(names: Optional[List[str]] = None) -> List[Tool]:
    tools = []
    for name in (names or list(KNOWN_CLIS)):
        present = shutil.which(name) is not None
        tools.append(Tool(name=name, installed=present,
                          version=_version(name) if present else "",
                          purpose=KNOWN_CLIS.get(name, "")))
    return tools


def detect_providers(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Which providers are configured. Values are masked immediately."""
    source = env if env is not None else os.environ
    found = {}
    for var in PROVIDER_VARS:
        value = source.get(var, "")
        if value:
            found[var] = mask(value)
    return found


def detect_local_models() -> List[str]:
    if not shutil.which("ollama"):
        return []
    try:
        proc = subprocess.run([shutil.which("ollama"), "list"],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    return [ln.split()[0] for ln in lines[1:] if ln.strip()]


def audit() -> Capabilities:
    """Full read-only capability audit of this machine."""
    return Capabilities(
        generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        tools=detect_tools(),
        providers=detect_providers(),
        local_models=detect_local_models(),
    )

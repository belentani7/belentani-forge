"""Tests for the core engine functions."""
import os
import tempfile
from pathlib import Path

from forge.engine import (
    slug, pkg_name, render, human, readiness,
    detect_stack, categorize, scan_secrets,
    VERSION,
)


def test_version():
    assert VERSION == "11.0.0"


def test_slug():
    assert slug("My Cool Project!") == "my-cool-project"
    assert slug("  hello world  ") == "hello-world"
    assert slug("") == "proyecto"


def test_pkg_name():
    assert pkg_name("my-cool-project") == "my_cool_project"


def test_render():
    assert render("hello {{NAME}}", NAME="world") == "hello world"
    assert render("{{A}} + {{B}}", A="1", B="2") == "1 + 2"


def test_human():
    assert "B" in human(500)
    assert "KB" in human(2048)
    assert "MB" in human(5_000_000)
    assert "GB" in human(5_000_000_000)


def test_readiness_empty():
    p = {"readme": False, "license": False, "gitignore": False, "deps": False,
         "tests": False, "ci": False, "env_example": False, "git": {}, "loc": 0,
         "secrets": []}
    assert readiness(p) == 0


def test_readiness_full():
    p = {"readme": True, "license": True, "gitignore": True, "deps": True,
         "tests": True, "ci": True, "env_example": True,
         "git": {"repo": True, "remote": "x", "commits": 10, "unpushed": 0},
         "loc": 500, "secrets": []}
    assert readiness(p) >= 90


def test_readiness_secrets_penalty():
    base = {"readme": True, "license": True, "gitignore": True, "deps": True,
            "tests": True, "ci": True, "env_example": True,
            "git": {"repo": True, "remote": "x", "commits": 10, "unpushed": 0},
            "loc": 500}
    clean = {**base, "secrets": []}
    dirty = {**base, "secrets": [{"kind": "generic", "file": "x.py", "line": 1}]}
    assert readiness(clean) > readiness(dirty)


def test_detect_stack_python(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    assert detect_stack(tmp_path) == "python"


def test_detect_stack_node(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x"}')
    assert detect_stack(tmp_path) == "node"


def test_detect_stack_node_ts(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x","devDependencies":{"typescript":"^5"}}')
    (tmp_path / "tsconfig.json").write_text("{}")
    assert detect_stack(tmp_path) == "node-ts"


def test_detect_stack_next(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"14"}}')
    assert detect_stack(tmp_path) == "next"


def test_detect_stack_go(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    assert detect_stack(tmp_path) == "go"


def test_detect_stack_static(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    assert detect_stack(tmp_path) == "static-web"


def test_detect_stack_unknown(tmp_path):
    (tmp_path / "random.txt").write_text("hello")
    assert detect_stack(tmp_path) == "unknown"


def test_categorize():
    assert categorize("aion-workforce", "node-ts") == "ai-agents"
    assert categorize("duck-hub", "node") == "web"
    assert categorize("my-website", "next") == "web"
    assert categorize("belentani-core", "python") == "automation"


def test_scan_secrets_clean(tmp_path):
    (tmp_path / "app.py").write_text('x = 42\nname = "hello"\n')
    assert scan_secrets(tmp_path) == []


def test_scan_secrets_finds_key(tmp_path):
    (tmp_path / "config.py").write_text('API_KEY = "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ123456"\n')  # gitleaks:allow
    hits = scan_secrets(tmp_path)
    assert len(hits) >= 1
    assert hits[0]["kind"] in ("openai_key", "generic")


def test_scan_secrets_ignores_example(tmp_path):
    (tmp_path / "config.py").write_text('API_KEY = os.environ.get("API_KEY")\n')
    assert scan_secrets(tmp_path) == []

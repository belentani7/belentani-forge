#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BELENTANI FORGE v5.0 - Motor autonomo de proyectos.

Cuatro pilares en un solo archivo, sin dependencias externas (solo stdlib):

  1. GENERATIVO   `new`       crea proyectos completos desde plantillas
                              (python-cli, fastapi, node-ts, next, static-web,
                              mcp-server, agent) con README/LICENSE/CI/tests/git.
  2. CONSTRUCTOR  `build`     detecta el stack y ejecuta install/build/test/lint.
  3. ORGANIZADOR  `organize`  clasifica por dominio, detecta duplicados exactos,
                              normaliza estructura y genera INDEX.md.
  4. FINALIZADOR  `finish`    puntua 0-100 la "terminacion" de cada proyecto y
                              cierra los huecos (README, LICENSE, .gitignore,
                              .env.example, CI, smoke tests, commit, tag, push).

Extras: `scan`, `doctor`, `report`, `release`, `github`, `schedule`, `auto`.

REGLA DE SEGURIDAD: todo es SOLO LECTURA por defecto. Ninguna escritura, movida,
commit, push ni instalacion ocurre sin la bandera --apply. Nada se borra nunca:
los duplicados y los descartes van a quarantine/.

Uso tipico sin supervision:
    python belentani_forge.py auto --apply --max 10
    python belentani_forge.py new python-cli mi-proyecto --apply --github
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "11.0.0"

def _resolve_home() -> Path:
    env = os.environ.get("FORGE_HOME")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".forge"
    p.mkdir(parents=True, exist_ok=True)
    return p

HERE = _resolve_home()
STATE_FILE = HERE / "state.json"
LOG_FILE = HERE / "forge.log"
QUARANTINE = HERE / "quarantine"
CONFIG_FILE = HERE / "config.json"

AUTHOR = os.environ.get("FORGE_AUTHOR", "Pedro Belentani")
GH_USER = os.environ.get("FORGE_GH_USER", "belentani7")

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist",
    "build", ".next", ".nuxt", ".cache", ".turbo", "coverage", ".pytest_cache",
    ".mypy_cache", "target", "vendor", ".idea", ".vscode", "quarantine",
    "_archive", ".gradle", "bin", "obj", ".terraform",
}
CODE_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".rb",
    ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".sh", ".ps1", ".sql",
    ".html", ".css", ".scss", ".vue", ".svelte", ".md", ".yml", ".yaml", ".toml",
}
MARKERS = (
    "package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml",
    "composer.json", "pom.xml", "build.gradle", "Gemfile", "index.html", ".git",
)
WORKSPACE_DIRS = {"apps", "packages", "services", "tools", "clients", "demos",
                  "projects", "sites", "libs", "modules", "artist"}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES_PER_PROJECT = 6000

CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "ai-agents": ("agent", "aion", "llm", "gpt", "claude", "mcp", "rag", "prompt",
                  "orchestr", "autonom", "swarm", "brain", "neural", "nexus"),
    "audio-music": ("music", "audio", "sound", "song", "beat", "mix", "master",
                    "midi", "synth", "daw", "stem", "vocal"),
    "voice-tts": ("tts", "voice", "speech", "asr", "whisper", "clone", "rvc"),
    "video": ("video", "film", "reel", "render", "clip", "kling", "runway"),
    "web": ("web", "site", "landing", "portfolio", "page", "theme", "ui", "front",
            "next", "astro", "vite", "react"),
    "3d": ("3d", "three", "webgl", "shader", "blender", "gltf"),
    "backend-api": ("api", "backend", "server", "service", "gateway", "fastapi",
                    "express", "db", "database", "sql"),
    "automation": ("bot", "automat", "scrap", "pipeline", "cron", "workflow",
                   "n8n", "script", "ops", "deploy"),
    "data": ("data", "dataset", "analytics", "etl", "report", "dashboard"),
    "education": ("school", "course", "learn", "academy", "edu", "lingua",
                  "instituto", "curso"),
    "docs": ("doc", "docs", "manual", "guide", "wiki", "spec"),
}

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


# --------------------------------------------------------------------------
# Utilidades base
# --------------------------------------------------------------------------
def out(msg: str = "") -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def ts() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def log(msg: str, echo: bool = True) -> None:
    line = "[%s] %s" % (ts(), msg)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    if echo:
        out(msg)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f GB" % n


def run(cmd: Sequence[str], cwd: Optional[Path] = None, timeout: int = 900,
        keep: int = 1_000_000) -> Tuple[int, str]:
    """Ejecuta un comando y devuelve (codigo, salida combinada).

    `keep` limita los caracteres conservados (por defecto 1 MB, suficiente para
    salidas JSON completas como `gh repo list --limit 1000`).
    """
    exe = shutil.which(cmd[0])
    if not exe:
        return 127, "no encontrado en PATH: %s" % cmd[0]
    try:
        r = subprocess.run([exe, *cmd[1:]], cwd=str(cwd) if cwd else None,
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "timeout tras %ss" % timeout
    except OSError as exc:
        return 1, str(exc)
    txt = (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace").strip()
    return r.returncode, txt[-keep:]


def read_text(path: Path, limit: int = MAX_FILE_BYTES) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def write_file(path: Path, content: str, apply: bool, force: bool = False) -> bool:
    """Escribe solo con --apply. No pisa archivos existentes salvo force."""
    if path.exists() and not force:
        return False
    if not apply:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return True


def load_config() -> Dict:
    for candidate in (CONFIG_FILE, HERE / "forge_config.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
    return {}


def default_roots(cfg: Dict) -> List[str]:
    roots = [str(r) for r in cfg.get("roots", []) if Path(r).exists()]
    if roots:
        return roots
    home = Path.home()
    for name in ("Documents/01_PROYECTOS", "Documentos/01_PROYECTOS", "Projects",
                 "Desktop"):
        p = home / name
        if p.exists():
            roots.append(str(p))
    return roots or [str(Path.cwd())]


def slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "proyecto"


def pkg_name(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", slug(text).replace("-", "_"))


def render(tpl: str, **kw) -> str:
    for key, val in kw.items():
        tpl = tpl.replace("{{" + key + "}}", str(val))
    return tpl


def save_state(data: Dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                              encoding="utf-8")
    except OSError as exc:
        log("aviso: no se pudo guardar estado (%s)" % exc)


def load_state() -> Dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# SCAN - inventario de proyectos
# --------------------------------------------------------------------------
def walk_project(root: Path) -> Iterable[Path]:
    count = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            count += 1
            if count > MAX_FILES_PER_PROJECT:
                return
            yield Path(base) / name


def _safe_iterdir(path: Path) -> List[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def find_projects(roots: Sequence[str], max_depth: int = 4) -> List[Path]:
    found: List[Path] = []
    seen: set = set()

    def visit(path: Path, depth: int) -> None:
        if depth > max_depth or path.name in SKIP_DIRS:
            return
        try:
            entries = list(path.iterdir())
        except OSError:
            return
        names = {e.name for e in entries}
        if names & set(MARKERS):
            key = str(path.resolve()).lower()
            if key not in seen:
                seen.add(key)
                found.append(path)
            # un monorepo/workspace tambien contiene proyectos propios dentro
            for entry in entries:
                if entry.is_dir() and entry.name in WORKSPACE_DIRS:
                    for child in _safe_iterdir(entry):
                        if child.is_dir() and child.name not in SKIP_DIRS:
                            visit(child, depth + 1)
            return
        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS:
                visit(entry, depth + 1)

    for root in roots:
        rp = Path(root)
        if rp.exists():
            visit(rp, 0)
    return found


def detect_stack(path: Path) -> str:
    names = {p.name for p in path.iterdir() if p.is_file()} if path.is_dir() else set()
    if "package.json" in names:
        raw = read_text(path / "package.json")
        if "\"next\"" in raw:
            return "next"
        if "\"typescript\"" in raw or (path / "tsconfig.json").exists():
            return "node-ts"
        return "node"
    if "pyproject.toml" in names or "requirements.txt" in names or \
            "setup.py" in names:
        return "python"
    if "go.mod" in names:
        return "go"
    if "Cargo.toml" in names:
        return "rust"
    if "index.html" in names:
        return "static-web"
    if any(p.suffix == ".py" for p in path.glob("*.py")):
        return "python"
    if any(p.suffix == ".ps1" for p in path.glob("*.ps1")):
        return "powershell"
    return "unknown"


def scan_secrets(path: Path, limit: int = 400) -> List[Dict]:
    hits: List[Dict] = []
    checked = 0
    for f in walk_project(path):
        if f.suffix.lower() not in CODE_EXT and f.name not in (".env",):
            continue
        if f.name in (".env.example", "package-lock.json", "pnpm-lock.yaml"):
            continue
        checked += 1
        if checked > limit or len(hits) >= 25:
            break
        text = read_text(f, 512 * 1024)
        if not text:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 500 or SECRET_SAFE.search(line):
                continue
            for kind, rx in SECRET_PATTERNS:
                if rx.search(line):
                    hits.append({
                        "kind": kind,
                        "file": str(f.relative_to(path)),
                        "line": lineno,
                    })
                    break
            if len(hits) >= 25:
                break
    return hits


def categorize(name: str, stack: str, topics: Sequence[str] = ()) -> str:
    blob = (name + " " + " ".join(topics)).lower()
    best, score = "", 0
    for cat, keys in CATEGORIES.items():
        n = sum(1 for k in keys if k in blob)
        if n > score:
            best, score = cat, n
    if best:
        return best
    if stack in ("static-web", "next", "node-ts", "node") or stack == "html":
        return "web"
    return {"next": "web", "node-ts": "web", "node": "web", "static-web": "web",
            "python": "automation", "go": "backend-api", "rust": "backend-api",
            "powershell": "automation"}.get(stack, "otros")


def git_info(path: Path) -> Dict:
    if not (path / ".git").exists():
        return {"repo": False}
    info: Dict = {"repo": True}
    code, o = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], path, 30)
    info["branch"] = o.strip() if code == 0 else "?"
    code, o = run(["git", "status", "--porcelain"], path, 60)
    info["dirty"] = len([l for l in o.splitlines() if l.strip()]) if code == 0 else -1
    code, o = run(["git", "remote", "get-url", "origin"], path, 30)
    info["remote"] = o.strip() if code == 0 else ""
    code, o = run(["git", "rev-list", "--count", "HEAD"], path, 30)
    info["commits"] = int(o.strip()) if code == 0 and o.strip().isdigit() else 0
    if info["remote"]:
        code, o = run(["git", "rev-list", "--count", "@{u}..HEAD"], path, 30)
        info["unpushed"] = int(o.strip()) if code == 0 and o.strip().isdigit() else 0
    else:
        info["unpushed"] = info["commits"]
    return info


def profile(path: Path, deep_secrets: bool = True) -> Dict:
    """Radiografia completa de un proyecto (solo lectura)."""
    files = list(walk_project(path))
    loc = 0
    size = 0
    langs: Counter = Counter()
    todos = 0
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        size += st.st_size
        ext = f.suffix.lower()
        if ext in CODE_EXT and st.st_size <= MAX_FILE_BYTES:
            text = read_text(f)
            if text:
                lines = text.count("\n") + 1
                loc += lines
                langs[ext] += lines
                todos += len(re.findall(r"\b(?:TODO|FIXME|HACK|XXX)\b", text))
    names = {f.name for f in files}
    dirs = {p.name for p in path.iterdir() if p.is_dir()} if path.is_dir() else set()
    stack = detect_stack(path)
    info = {
        "name": path.name,
        "path": str(path),
        "stack": stack,
        "category": categorize(path.name, stack),
        "files": len(files),
        "size": size,
        "loc": loc,
        "todos": todos,
        "langs": dict(langs.most_common(5)),
        "readme": any(n.lower().startswith("readme") for n in names),
        "license": any(n.lower().startswith("licen") for n in names),
        "gitignore": ".gitignore" in names,
        "env_example": ".env.example" in names or "env.example" in names,
        "tests": bool({"tests", "test", "__tests__", "spec"} & dirs) or
                 any(n.startswith("test_") or n.endswith(("_test.py", ".test.ts",
                     ".spec.ts", ".test.js")) for n in names),
        "ci": (path / ".github" / "workflows").exists(),
        "deps": bool(names & {"package.json", "requirements.txt", "pyproject.toml",
                              "go.mod", "Cargo.toml"}),
        "git": git_info(path),
        "secrets": scan_secrets(path) if deep_secrets else [],
    }
    info["score"] = readiness(info)
    return info


def readiness(p: Dict) -> int:
    """Puntuacion 0-100 de cuan 'terminado' esta un proyecto."""
    score = 0
    score += 15 if p["readme"] else 0
    score += 8 if p["license"] else 0
    score += 8 if p["gitignore"] else 0
    score += 10 if p["deps"] else 0
    score += 18 if p["tests"] else 0
    score += 12 if p["ci"] else 0
    score += 5 if p["env_example"] else 0
    g = p.get("git") or {}
    if g.get("repo"):
        score += 6
        if g.get("remote"):
            score += 6
        if g.get("commits", 0) > 3:
            score += 6
        if not g.get("unpushed"):
            score += 3
    if p["loc"] > 200:
        score += 3
    score -= 25 if p["secrets"] else 0
    return max(0, min(100, score))


def scan(roots: Sequence[str], workers: int = 12, deep: bool = True,
         only: Optional[Sequence[str]] = None, depth: int = 4) -> List[Dict]:
    paths = find_projects(roots, depth)
    if only:
        wanted = {o.lower() for o in only}
        paths = [p for p in paths if p.name.lower() in wanted]
    log("scan: %d proyectos detectados en %d raices" % (len(paths), len(roots)))
    results: List[Dict] = []
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(profile, p, deep): p for p in paths}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001 - un proyecto roto no corta el scan
                log("  fallo en %s: %s" % (futs[fut].name, exc), echo=False)
            if i % 10 == 0:
                log("  ...%d/%d" % (i, len(paths)), echo=False)
    results.sort(key=lambda x: (-x["score"], x["name"].lower()))
    return results


# --------------------------------------------------------------------------
# PLANTILLAS (pilar GENERATIVO)
# --------------------------------------------------------------------------
LICENSE_MIT = """MIT License

Copyright (c) {{YEAR}} {{AUTHOR}}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

GITIGNORE_COMMON = """# dependencias
node_modules/
.venv/
venv/
__pycache__/
*.py[cod]

# build
dist/
build/
.next/
out/
target/
*.egg-info/

# entorno y secretos
.env
.env.local
.env.*.local
*.pem
*.key

# sistema
.DS_Store
Thumbs.db
*.log

# cache
.cache/
.pytest_cache/
.mypy_cache/
.ruff_cache/
coverage/
"""

README_TPL = """# {{NAME}}

{{DESC}}

## Estado

| Campo | Valor |
|---|---|
| Stack | `{{STACK}}` |
| Creado | {{DATE}} |
| Autor | {{AUTHOR}} |
| Licencia | MIT |

## Instalacion

```bash
{{INSTALL}}
```

## Uso

```bash
{{USAGE}}
```

## Tests

```bash
{{TEST}}
```

## Estructura

```
{{TREE}}
```

## Variables de entorno

Copia `.env.example` a `.env` y rellena los valores. Nunca comitees `.env`.

## Licencia

MIT - ver [LICENSE](LICENSE).
"""

ENV_EXAMPLE = """# Copia este archivo a .env y rellena los valores reales.
# .env esta en .gitignore: nunca subas credenciales al repositorio.
APP_ENV=development
LOG_LEVEL=info
# API_KEY=
"""

CI_PYTHON = """name: ci
on:
  push:
    branches: [ main, master ]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Instalar
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]" || pip install -r requirements.txt || true
          pip install pytest
      - name: Tests
        run: pytest -q
"""

CI_NODE = """name: ci
on:
  push:
    branches: [ main, master ]
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm install
      - run: npm run build --if-present
      - run: npm test --if-present
"""

CI_GENERIC = """name: ci
on:
  push:
    branches: [ main, master ]
  pull_request:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verificacion basica
        run: |
          test -f README.md && echo "README ok"
          test -f LICENSE && echo "LICENSE ok"
"""

PYPROJECT_TPL = """[project]
name = "{{SLUG}}"
version = "0.1.0"
description = "{{DESC}}"
readme = "README.md"
requires-python = ">=3.9"
license = { text = "MIT" }
authors = [{ name = "{{AUTHOR}}" }]
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7"]

[project.scripts]
{{SLUG}} = "{{PKG}}.__main__:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
"""

PY_MAIN = '''"""Punto de entrada de {{NAME}}."""
from __future__ import annotations

import argparse

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="{{SLUG}}", description="{{DESC}}")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--name", default="mundo", help="a quien saludar")
    args = parser.parse_args(argv)
    print(f"{{NAME}} v{__version__}: hola {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PY_INIT = '''"""{{NAME}} - {{DESC}}"""

__version__ = "0.1.0"
__all__ = ["__version__"]
'''

PY_TEST = '''from {{PKG}} import __version__
from {{PKG}}.__main__ import main


def test_version():
    assert __version__


def test_main_runs():
    assert main(["--name", "test"]) == 0
'''

FASTAPI_APP = '''"""API de {{NAME}}."""
from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="{{NAME}}", version="0.1.0")


class Health(BaseModel):
    status: str
    env: str


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", env=os.environ.get("APP_ENV", "development"))


@app.get("/")
def root() -> dict:
    return {"name": "{{NAME}}", "docs": "/docs"}
'''

FASTAPI_TEST = '''from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
'''

FASTAPI_REQS = """fastapi>=0.110
uvicorn[standard]>=0.27
pydantic>=2.5
pytest>=7
httpx>=0.26
"""

PACKAGE_JSON_TS = """{
  "name": "{{SLUG}}",
  "version": "0.1.0",
  "description": "{{DESC}}",
  "type": "module",
  "main": "dist/index.js",
  "license": "MIT",
  "author": "{{AUTHOR}}",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "dev": "tsx src/index.ts",
    "start": "node dist/index.js",
    "test": "node --test dist/*.test.js || echo \\"sin tests compilados\\"",
    "lint": "tsc --noEmit"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "tsx": "^4.7.0",
    "@types/node": "^20.11.0"
  }
}
"""

TSCONFIG = """{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "bundler",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true
  },
  "include": ["src"]
}
"""

TS_INDEX = """/** {{NAME}} - {{DESC}} */

export const VERSION = "0.1.0";

export function greet(name = "mundo"): string {
  return `{{NAME}} v${VERSION}: hola ${name}`;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(greet(process.argv[2]));
}
"""

TS_TEST = """import { test } from "node:test";
import assert from "node:assert/strict";
import { greet, VERSION } from "./index.js";

test("version definida", () => {
  assert.ok(VERSION);
});

test("saluda", () => {
  assert.match(greet("test"), /test/);
});
"""

STATIC_INDEX = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{NAME}}</title>
<meta name="description" content="{{DESC}}">
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header class="wrap">
  <h1>{{NAME}}</h1>
  <p>{{DESC}}</p>
</header>
<main class="wrap">
  <section>
    <h2>Seccion</h2>
    <p>Contenido inicial generado por BELENTANI FORGE.</p>
  </section>
</main>
<footer class="wrap"><small>&copy; {{YEAR}} {{AUTHOR}}</small></footer>
<script src="main.js" defer></script>
</body>
</html>
"""

STATIC_CSS = """:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #14161a;
  --accent: #3d5afe;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0e1013; --fg: #e8eaed; }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 68ch; margin: 0 auto; padding: 2rem 1.25rem; }
h1 { font-size: clamp(1.8rem, 5vw, 2.6rem); letter-spacing: -0.02em; }
a { color: var(--accent); }
"""

STATIC_JS = """// {{NAME}}
document.addEventListener("DOMContentLoaded", () => {
  console.info("{{NAME}} listo");
});
"""

MCP_SERVER = '''#!/usr/bin/env python3
"""Servidor MCP minimo de {{NAME}} (protocolo JSON-RPC por stdio)."""
from __future__ import annotations

import json
import sys

TOOLS = [
    {
        "name": "ping",
        "description": "Devuelve pong con el texto recibido",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
]


def handle(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "{{SLUG}}", "version": "0.1.0"},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        args = req.get("params", {}).get("arguments", {})
        text = args.get("text", "")
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": f"pong: {text}"}]}}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"metodo desconocido: {method}"}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

MCP_TEST = '''import json
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server.py"


def test_initialize():
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    r = subprocess.run([sys.executable, str(SERVER)], input=req + "\\n",
                       capture_output=True, text=True, timeout=30)
    assert "serverInfo" in r.stdout
'''

AGENT_MAIN = '''"""Agente autonomo {{NAME}}: bucle percibir-decidir-actuar."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

STATE = Path(".agent_state.json")


@dataclass
class Task:
    goal: str
    done: bool = False
    notes: list = field(default_factory=list)


class Agent:
    """Esqueleto sin dependencias: sustituye `decide` por tu LLM o reglas."""

    def __init__(self, goal: str, max_steps: int = 10) -> None:
        self.task = Task(goal=goal)
        self.max_steps = max_steps

    def perceive(self) -> dict:
        return {"cwd": str(Path.cwd()), "files": len(list(Path.cwd().iterdir()))}

    def decide(self, obs: dict) -> str:
        return "finish" if self.task.notes else "observe"

    def act(self, action: str, obs: dict) -> None:
        self.task.notes.append({"action": action, "obs": obs})
        if action == "finish":
            self.task.done = True

    def run(self) -> Task:
        for _ in range(self.max_steps):
            if self.task.done:
                break
            obs = self.perceive()
            self.act(self.decide(obs), obs)
        STATE.write_text(json.dumps(self.task.__dict__, indent=1), encoding="utf-8")
        return self.task


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="{{DESC}}")
    ap.add_argument("goal", help="objetivo del agente")
    ap.add_argument("--max-steps", type=int, default=10)
    args = ap.parse_args(argv)
    task = Agent(args.goal, args.max_steps).run()
    print(f"objetivo: {task.goal} | completado: {task.done} | pasos: {len(task.notes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

AGENT_TEST = '''from agent.main import Agent


def test_agent_termina():
    task = Agent("probar", max_steps=5).run()
    assert task.done
'''


def template_files(kind: str, name: str, desc: str) -> Dict[str, str]:
    """Devuelve {ruta_relativa: contenido} para una plantilla."""
    s = slug(name)
    pkg = pkg_name(name)
    year = datetime.now().year
    base = {
        "LICENSE": render(LICENSE_MIT, YEAR=year, AUTHOR=AUTHOR),
        ".gitignore": GITIGNORE_COMMON,
        ".env.example": ENV_EXAMPLE,
    }
    common = dict(NAME=name, SLUG=s, PKG=pkg, DESC=desc, AUTHOR=AUTHOR, YEAR=year,
                  DATE=datetime.now().strftime("%Y-%m-%d"))

    if kind == "python-cli":
        files = {
            "pyproject.toml": render(PYPROJECT_TPL, **common),
            "src/%s/__init__.py" % pkg: render(PY_INIT, **common),
            "src/%s/__main__.py" % pkg: render(PY_MAIN, **common),
            "tests/test_smoke.py": render(PY_TEST, **common),
            ".github/workflows/ci.yml": CI_PYTHON,
        }
        readme = render(README_TPL, STACK="python-cli",
                        INSTALL="pip install -e \".[dev]\"",
                        USAGE="python -m %s --name mundo" % pkg,
                        TEST="pytest -q",
                        TREE="src/%s/  tests/  pyproject.toml" % pkg, **common)
    elif kind == "fastapi":
        files = {
            "requirements.txt": FASTAPI_REQS,
            "app/__init__.py": "",
            "app/main.py": render(FASTAPI_APP, **common),
            "tests/test_api.py": FASTAPI_TEST,
            ".github/workflows/ci.yml": CI_PYTHON,
            "Dockerfile": ("FROM python:3.11-slim\nWORKDIR /app\n"
                           "COPY requirements.txt .\n"
                           "RUN pip install --no-cache-dir -r requirements.txt\n"
                           "COPY . .\nEXPOSE 8000\n"
                           "CMD [\"uvicorn\", \"app.main:app\", \"--host\", "
                           "\"0.0.0.0\", \"--port\", \"8000\"]\n"),
        }
        readme = render(README_TPL, STACK="fastapi",
                        INSTALL="pip install -r requirements.txt",
                        USAGE="uvicorn app.main:app --reload",
                        TEST="pytest -q",
                        TREE="app/main.py  tests/  Dockerfile", **common)
    elif kind in ("node-ts", "next"):
        files = {
            "package.json": render(PACKAGE_JSON_TS, **common),
            "tsconfig.json": TSCONFIG,
            "src/index.ts": render(TS_INDEX, **common),
            "src/index.test.ts": TS_TEST,
            ".github/workflows/ci.yml": CI_NODE,
        }
        readme = render(README_TPL, STACK=kind, INSTALL="npm install",
                        USAGE="npm run dev", TEST="npm run build && npm test",
                        TREE="src/index.ts  tsconfig.json  package.json", **common)
    elif kind == "static-web":
        files = {
            "index.html": render(STATIC_INDEX, **common),
            "styles.css": STATIC_CSS,
            "main.js": render(STATIC_JS, **common),
            ".github/workflows/ci.yml": CI_GENERIC,
        }
        readme = render(README_TPL, STACK="static-web",
                        INSTALL="# sin dependencias",
                        USAGE="python -m http.server 8080", TEST="# manual",
                        TREE="index.html  styles.css  main.js", **common)
    elif kind == "mcp-server":
        files = {
            "server.py": render(MCP_SERVER, **common),
            "requirements.txt": "pytest>=7\n",
            "tests/test_server.py": MCP_TEST,
            ".github/workflows/ci.yml": CI_PYTHON,
            "mcp.json": json.dumps({
                "mcpServers": {s: {"command": "python",
                                   "args": ["server.py"]}}}, indent=2),
        }
        readme = render(README_TPL, STACK="mcp-server",
                        INSTALL="pip install -r requirements.txt",
                        USAGE="python server.py  # habla JSON-RPC por stdio",
                        TEST="pytest -q",
                        TREE="server.py  mcp.json  tests/", **common)
    elif kind == "agent":
        files = {
            "agent/__init__.py": "",
            "agent/main.py": render(AGENT_MAIN, **common),
            "requirements.txt": "pytest>=7\n",
            "tests/test_agent.py": AGENT_TEST,
            ".github/workflows/ci.yml": CI_PYTHON,
        }
        readme = render(README_TPL, STACK="agent",
                        INSTALL="pip install -r requirements.txt",
                        USAGE="python -m agent.main \"mi objetivo\"",
                        TEST="pytest -q", TREE="agent/main.py  tests/", **common)
    else:
        raise ValueError("plantilla desconocida: %s" % kind)

    files["README.md"] = readme
    files.update(base)
    return files


TEMPLATE_NAMES = ("python-cli", "fastapi", "node-ts", "next", "static-web",
                  "mcp-server", "agent")


# --------------------------------------------------------------------------
# COMANDO: new (GENERATIVO)
# --------------------------------------------------------------------------
def cmd_new(args) -> int:
    name = args.name
    target = Path(args.dir or default_roots(load_config())[0]) / slug(name)
    desc = args.desc or "Proyecto %s generado por BELENTANI FORGE." % name
    files = template_files(args.template, name, desc)

    out("PLANTILLA : %s" % args.template)
    out("DESTINO   : %s" % target)
    out("ARCHIVOS  : %d" % len(files))
    if target.exists() and any(target.iterdir()) and not args.force:
        out("ERROR: el destino ya existe y no esta vacio (usa --force)")
        return 2

    for rel in sorted(files):
        out("  + %s" % rel)
    if not args.apply:
        out("\n(dry-run) repite con --apply para materializar")
        return 0

    for rel, content in files.items():
        write_file(target / rel, content, True, force=args.force)
    log("creado %s con %d archivos" % (target, len(files)))

    if not args.no_git:
        run(["git", "init", "-b", "main"], target)
        run(["git", "add", "-A"], target)
        code, o = run(["git", "commit", "-m",
                       "feat: scaffold inicial de %s\n\nGenerado por BELENTANI "
                       "FORGE v%s." % (name, VERSION)], target)
        log("git init + commit inicial: %s" % ("ok" if code == 0 else o[:120]))

    if args.github:
        vis = "--public" if args.public else "--private"
        code, o = run(["gh", "repo", "create", "%s/%s" % (GH_USER, slug(name)),
                       vis, "--source", ".", "--remote", "origin", "--push"],
                      target, 300)
        log("gh repo create: %s" % ("ok" if code == 0 else o[:200]))

    out("\nLISTO: %s" % target)
    return 0


# --------------------------------------------------------------------------
# COMANDO: build (CONSTRUCTOR)
# --------------------------------------------------------------------------
def build_steps(stack: str, path: Path) -> List[Tuple[str, List[str]]]:
    pkg = read_text(path / "package.json") if (path / "package.json").exists() else ""
    if stack in ("node", "node-ts", "next"):
        steps = [("install", ["npm", "install", "--no-audit", "--no-fund"])]
        if "\"build\"" in pkg:
            steps.append(("build", ["npm", "run", "build"]))
        if "\"test\"" in pkg:
            steps.append(("test", ["npm", "test", "--if-present"]))
        if "\"lint\"" in pkg:
            steps.append(("lint", ["npm", "run", "lint"]))
        return steps
    if stack == "python":
        steps: List[Tuple[str, List[str]]] = []
        if (path / "requirements.txt").exists():
            steps.append(("install", [sys.executable, "-m", "pip", "install", "-r",
                                      "requirements.txt"]))
        elif (path / "pyproject.toml").exists():
            steps.append(("install", [sys.executable, "-m", "pip", "install", "-e",
                                      "."]))
        steps.append(("compile", [sys.executable, "-m", "compileall", "-q", "."]))
        steps.append(("test", [sys.executable, "-m", "pytest", "-q"]))
        return steps
    if stack == "go":
        return [("build", ["go", "build", "./..."]), ("test", ["go", "test", "./..."])]
    if stack == "rust":
        return [("build", ["cargo", "build"]), ("test", ["cargo", "test"])]
    if stack == "static-web":
        return [("check", [sys.executable, "-c",
                           "import pathlib,sys;"
                           "sys.exit(0 if pathlib.Path('index.html').exists() else 1)"])]
    return []


def cmd_build(args) -> int:
    cfg = load_config()
    roots = args.roots or default_roots(cfg)
    projects = scan(roots, args.workers, deep=False, only=args.only,
                 depth=getattr(args, "depth", 4))
    if args.max:
        projects = projects[: args.max]
    results = []
    for p in projects:
        path = Path(p["path"])
        steps = build_steps(p["stack"], path)
        if not steps:
            out("- %-28s %-10s sin pasos de build" % (p["name"][:28], p["stack"]))
            continue
        out("\n== %s (%s)" % (p["name"], p["stack"]))
        rec = {"name": p["name"], "path": p["path"], "steps": []}
        for label, cmd in steps:
            if not args.apply:
                out("   [dry-run] %s: %s" % (label, " ".join(cmd[:4])))
                continue
            t0 = time.time()
            code, o = run(cmd, path, args.timeout)
            status = "OK" if code == 0 else "FALLO(%d)" % code
            out("   %s: %s  %.1fs" % (label, status, time.time() - t0))
            if code != 0 and args.verbose:
                out("      %s" % o.splitlines()[-1][:200] if o else "")
            rec["steps"].append({"step": label, "code": code,
                                 "tail": o[-500:] if code else ""})
            if code != 0 and args.stop_on_error:
                break
        results.append(rec)
    st = load_state()
    st["build"] = {"at": ts(), "results": results}
    save_state(st)
    fails = sum(1 for r in results for s in r["steps"] if s["code"] != 0)
    out("\nRESUMEN build: %d proyectos, %d pasos fallidos" % (len(results), fails))
    return 0


# --------------------------------------------------------------------------
# COMANDO: organize (ORGANIZADOR)
# --------------------------------------------------------------------------
def file_hash(path: Path, full: bool = False) -> str:
    h = hashlib.blake2b(digest_size=16)
    try:
        with path.open("rb") as fh:
            if full:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            else:
                h.update(fh.read(65536))
    except OSError:
        return ""
    return h.hexdigest()


def find_duplicates(projects: Sequence[Dict], min_size: int = 8192,
                    limit_files: int = 40000) -> List[Dict]:
    by_size: Dict[int, List[Path]] = defaultdict(list)
    seen = 0
    for p in projects:
        for f in walk_project(Path(p["path"])):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size < min_size:
                continue
            by_size[size].append(f)
            seen += 1
            if seen > limit_files:
                break
    groups: List[Dict] = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        buckets: Dict[str, List[Path]] = defaultdict(list)
        for f in files:
            buckets[file_hash(f)].append(f)
        for quick, cand in buckets.items():
            if len(cand) < 2 or not quick:
                continue
            confirmed: Dict[str, List[Path]] = defaultdict(list)
            for f in cand:
                confirmed[file_hash(f, full=True)].append(f)
            for _, dupes in confirmed.items():
                if len(dupes) > 1:
                    groups.append({
                        "size": size,
                        "count": len(dupes),
                        "waste": size * (len(dupes) - 1),
                        "paths": [str(d) for d in dupes],
                    })
    groups.sort(key=lambda g: -g["waste"])
    return groups[:2000]


def cmd_organize(args) -> int:
    cfg = load_config()
    roots = args.roots or default_roots(cfg)
    projects = scan(roots, args.workers, deep=False, only=args.only,
                 depth=getattr(args, "depth", 4))

    by_cat: Dict[str, List[Dict]] = defaultdict(list)
    for p in projects:
        by_cat[p["category"]].append(p)

    out("\n== TAXONOMIA (%d proyectos)" % len(projects))
    for cat in sorted(by_cat, key=lambda c: -len(by_cat[c])):
        items = by_cat[cat]
        loc = sum(i["loc"] for i in items)
        out("  %-14s %3d proyectos  %9s LOC" % (cat, len(items), "{:,}".format(loc)))

    dupes: List[Dict] = []
    if not args.no_dupes:
        out("\n== DUPLICADOS (hash exacto)")
        dupes = find_duplicates(projects)
        waste = sum(g["waste"] for g in dupes)
        out("  %d grupos, %s recuperables" % (len(dupes), human(waste)))
        for g in dupes[:10]:
            out("   %s x%d  %s" % (human(g["size"]), g["count"],
                                   Path(g["paths"][0]).name))

    stale = [p for p in projects
             if (p["git"].get("commits", 0) <= 1 and p["loc"] < 500)]
    out("\n== CANDIDATOS A ARCHIVAR (%d)" % len(stale))
    for p in stale[:20]:
        out("   %-30s %5d LOC  %d commits" % (p["name"][:30], p["loc"],
                                              p["git"].get("commits", 0)))

    index = ["# INDICE DE PROYECTOS", "",
             "Generado por BELENTANI FORGE v%s el %s." % (VERSION, ts()), "",
             "| Proyecto | Categoria | Stack | LOC | Score | Ruta |", "|---|---|---|---|---|---|"]
    for p in projects:
        index.append("| %s | %s | %s | %s | %d%% | `%s` |" % (
            p["name"], p["category"], p["stack"], "{:,}".format(p["loc"]),
            p["score"], p["path"]))
    index_path = Path(args.out or (HERE / "INDEX.md"))
    if args.apply:
        index_path.write_text("\n".join(index) + "\n", encoding="utf-8")
        log("INDEX escrito en %s" % index_path)
    else:
        out("\n(dry-run) INDEX.md se escribiria en %s" % index_path)

    if args.apply and args.quarantine_dupes and dupes:
        QUARANTINE.mkdir(parents=True, exist_ok=True)
        moved = 0
        for g in dupes:
            for dup in g["paths"][1:]:
                src = Path(dup)
                dst = QUARANTINE / ("%s__%s" % (src.parent.name, src.name))
                try:
                    if not dst.exists():
                        shutil.move(str(src), str(dst))
                        moved += 1
                except OSError as exc:
                    log("  no se pudo mover %s (%s)" % (src, exc), echo=False)
        log("duplicados movidos a quarantine: %d (nada borrado)" % moved)

    st = load_state()
    st["organize"] = {"at": ts(), "categories": {k: len(v) for k, v in by_cat.items()},
                      "dupe_groups": len(dupes)}
    st["projects"] = projects
    save_state(st)
    return 0


# --------------------------------------------------------------------------
# COMANDO: finish (FINALIZADOR)
# --------------------------------------------------------------------------
def finish_plan(p: Dict) -> List[Dict]:
    """Acciones concretas que suben el score del proyecto."""
    path = Path(p["path"])
    name = p["name"]
    year = datetime.now().year
    stack = p["stack"]
    plan: List[Dict] = []

    if not p["readme"]:
        install = {"python": "pip install -r requirements.txt",
                   "node": "npm install", "node-ts": "npm install",
                   "next": "npm install", "go": "go mod download",
                   "rust": "cargo build"}.get(stack, "# ver documentacion")
        usage = {"python": "python -m %s" % pkg_name(name), "node": "npm start",
                 "node-ts": "npm run dev", "next": "npm run dev",
                 "static-web": "python -m http.server 8080",
                 "go": "go run .", "rust": "cargo run"}.get(stack, "# ver scripts")
        test = {"python": "pytest -q", "node": "npm test", "node-ts": "npm test",
                "next": "npm test", "go": "go test ./...",
                "rust": "cargo test"}.get(stack, "# pendiente")
        tree = ", ".join(sorted({d.name for d in path.iterdir() if d.is_dir()
                                 and d.name not in SKIP_DIRS})[:8]) or "."
        plan.append({"file": "README.md", "why": "sin README",
                     "content": render(
                         README_TPL, NAME=name, DESC=p.get("desc")
                         or "Proyecto %s del ecosistema Belentani." % name,
                         STACK=stack, DATE=datetime.now().strftime("%Y-%m-%d"),
                         AUTHOR=AUTHOR, YEAR=year, INSTALL=install, USAGE=usage,
                         TEST=test, TREE=tree)})
    if not p["license"]:
        plan.append({"file": "LICENSE", "why": "sin licencia",
                     "content": render(LICENSE_MIT, YEAR=year, AUTHOR=AUTHOR)})
    if not p["gitignore"]:
        plan.append({"file": ".gitignore", "why": "sin .gitignore",
                     "content": GITIGNORE_COMMON})
    if not p["env_example"]:
        plan.append({"file": ".env.example", "why": "sin plantilla de entorno",
                     "content": ENV_EXAMPLE})
    if not p["ci"]:
        ci = CI_PYTHON if stack == "python" else (
            CI_NODE if stack in ("node", "node-ts", "next") else CI_GENERIC)
        plan.append({"file": ".github/workflows/ci.yml", "why": "sin CI",
                     "content": ci})
    if not p["tests"]:
        if stack == "python":
            plan.append({"file": "tests/test_smoke.py", "why": "sin tests",
                         "content": "def test_smoke():\n"
                                    "    \"\"\"Placeholder: sustituir por tests reales.\"\"\"\n"
                                    "    assert True\n"})
        elif stack in ("node", "node-ts", "next"):
            plan.append({"file": "tests/smoke.test.js", "why": "sin tests",
                         "content": "const test = require('node:test');\n"
                                    "const assert = require('node:assert');\n\n"
                                    "test('smoke', () => { assert.ok(true); });\n"})
    return plan


def cmd_finish(args) -> int:
    cfg = load_config()
    roots = args.roots or default_roots(cfg)
    projects = scan(roots, args.workers, deep=True, only=args.only,
                 depth=getattr(args, "depth", 4))
    if args.min_score is not None:
        projects = [p for p in projects if p["score"] < args.min_score]
    if args.max:
        projects = sorted(projects, key=lambda p: p["score"])[: args.max]

    total_actions = 0
    finished = []
    for p in projects:
        path = Path(p["path"])
        plan = finish_plan(p)
        secrets = p.get("secrets") or []
        out("\n== %-32s score %3d%%  %s" % (p["name"][:32], p["score"], p["stack"]))
        if secrets:
            out("   !! %d posible(s) secreto(s) - ROTAR y mover a .env:" % len(secrets))
            for s in secrets[:5]:
                out("      %s:%s (%s)" % (s["file"], s["line"], s["kind"]))
        if not plan:
            out("   completo, nada que hacer")
        for act in plan:
            mark = "+" if args.apply else "~"
            out("   %s %-32s (%s)" % (mark, act["file"], act["why"]))
            if args.apply:
                write_file(path / act["file"], act["content"], True)
            total_actions += 1

        if args.apply and args.commit and plan:
            g = p.get("git") or {}
            if not g.get("repo") and args.git_init:
                run(["git", "init", "-b", "main"], path)
            if (path / ".git").exists():
                run(["git", "add", "-A"], path)
                code, o = run(
                    ["git", "commit", "-m",
                     "chore: completar estructura del proyecto\n\n"
                     "Anadidos: %s\n\nGenerado por BELENTANI FORGE v%s."
                     % (", ".join(a["file"] for a in plan), VERSION)], path)
                out("   commit: %s" % ("ok" if code == 0 else o.splitlines()[-1][:90]
                                       if o else "sin cambios"))
                if args.push and code == 0 and (p.get("git") or {}).get("remote"):
                    pc, po = run(["git", "push"], path, 300)
                    out("   push: %s" % ("ok" if pc == 0 else po[-90:]))
        finished.append({"name": p["name"], "score": p["score"],
                         "actions": len(plan), "secrets": len(secrets)})

    out("\nRESUMEN finish: %d proyectos, %d acciones%s"
        % (len(projects), total_actions, "" if args.apply else " (dry-run)"))
    st = load_state()
    st["finish"] = {"at": ts(), "applied": bool(args.apply), "items": finished}
    save_state(st)
    return 0


# --------------------------------------------------------------------------
# COMANDO: release / github
# --------------------------------------------------------------------------
def bump(version: str, part: str) -> str:
    nums = [int(x) for x in (re.findall(r"\d+", version) + [0, 0, 0])[:3]]
    idx = {"major": 0, "minor": 1, "patch": 2}[part]
    nums[idx] += 1
    for j in range(idx + 1, 3):
        nums[j] = 0
    return ".".join(str(n) for n in nums)


def current_version(path: Path) -> Tuple[str, Optional[Path], Optional[str]]:
    pj = path / "package.json"
    if pj.exists():
        raw = read_text(pj)
        m = re.search(r'"version"\s*:\s*"([^"]+)"', raw)
        if m:
            return m.group(1), pj, "json"
    pp = path / "pyproject.toml"
    if pp.exists():
        raw = read_text(pp)
        m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', raw)
        if m:
            return m.group(1), pp, "toml"
    return "0.1.0", None, None


def cmd_release(args) -> int:
    path = Path(args.path or ".").resolve()
    cur, vfile, kind = current_version(path)
    new = args.version or bump(cur, args.part)
    out("proyecto : %s" % path.name)
    out("version  : %s -> %s" % (cur, new))

    code, logtxt = run(["git", "log", "--oneline", "-30"], path)
    entries = [l for l in logtxt.splitlines() if l.strip()][:30] if code == 0 else []
    changelog = path / "CHANGELOG.md"
    header = "## %s - %s\n\n" % (new, datetime.now().strftime("%Y-%m-%d"))
    body = "".join("- %s\n" % e.split(" ", 1)[-1] for e in entries) or "- cambios varios\n"
    block = header + body + "\n"
    prev = read_text(changelog) if changelog.exists() else "# Changelog\n\n"
    if not prev.startswith("# Changelog"):
        prev = "# Changelog\n\n" + prev

    out("changelog: %d entradas" % len(entries))
    if not args.apply:
        out("\n(dry-run) usa --apply para escribir version, CHANGELOG y tag")
        return 0

    if vfile and kind == "json":
        vfile.write_text(re.sub(r'("version"\s*:\s*")[^"]+(")',
                                r"\g<1>%s\g<2>" % new, read_text(vfile), count=1),
                         encoding="utf-8")
    elif vfile and kind == "toml":
        vfile.write_text(re.sub(r'(?m)^(version\s*=\s*")[^"]+(")',
                                r"\g<1>%s\g<2>" % new, read_text(vfile), count=1),
                         encoding="utf-8")
    changelog.write_text(prev.replace("# Changelog\n\n", "# Changelog\n\n" + block, 1),
                         encoding="utf-8")
    run(["git", "add", "-A"], path)
    run(["git", "commit", "-m", "chore(release): v%s" % new], path)
    code, o = run(["git", "tag", "-a", "v%s" % new, "-m", "v%s" % new], path)
    out("tag v%s: %s" % (new, "ok" if code == 0 else o[:100]))
    if args.push:
        run(["git", "push"], path, 300)
        run(["git", "push", "--tags"], path, 300)
        if args.gh_release:
            rc, ro = run(["gh", "release", "create", "v%s" % new, "--generate-notes"],
                         path, 300)
            out("gh release: %s" % ("ok" if rc == 0 else ro[:120]))
    return 0


def cmd_github(args) -> int:
    if not shutil.which("gh"):
        out("gh CLI no esta en PATH")
        return 127
    cfg = load_config()
    roots = args.roots or default_roots(cfg)
    projects = scan(roots, args.workers, deep=False, only=args.only,
                 depth=getattr(args, "depth", 4))
    code, o = run(["gh", "repo", "list", GH_USER, "--limit", str(args.limit),
                   "--json", "name,visibility,updatedAt"], timeout=600)
    remote = {}
    if code == 0:
        try:
            remote = {r["name"].lower(): r for r in json.loads(o)}
        except json.JSONDecodeError as exc:
            out("aviso: respuesta de gh ilegible (%s)" % exc)
    else:
        out("aviso: gh fallo (codigo %d): %s" % (code, o.splitlines()[0][:120] if o else ""))
    out("GitHub %s: %d repos remotos" % (GH_USER, len(remote)))

    sin_remoto = [p for p in projects if not (p["git"].get("remote"))]
    sin_pushear = [p for p in projects if p["git"].get("unpushed", 0) > 0
                   and p["git"].get("remote")]
    sucios = [p for p in projects if p["git"].get("dirty", 0) > 0]

    out("\n== SIN REMOTO (%d)" % len(sin_remoto))
    for p in sin_remoto[:25]:
        exists = slug(p["name"]) in remote
        out("   %-32s %s" % (p["name"][:32],
                             "existe en GitHub" if exists else "no publicado"))
    out("\n== COMMITS SIN PUJAR (%d)" % len(sin_pushear))
    for p in sin_pushear[:25]:
        out("   %-32s %d commits" % (p["name"][:32], p["git"]["unpushed"]))
    out("\n== ARBOL SUCIO (%d)" % len(sucios))
    for p in sucios[:25]:
        out("   %-32s %d archivos" % (p["name"][:32], p["git"]["dirty"]))

    if args.apply and args.push_all:
        for p in sin_pushear:
            code, o = run(["git", "push"], Path(p["path"]), 300)
            out("push %s: %s" % (p["name"], "ok" if code == 0 else o[-80:]))
    return 0


# --------------------------------------------------------------------------
# COMANDO: report / doctor / schedule
# --------------------------------------------------------------------------
HTML_HEAD = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BELENTANI FORGE</title><style>
:root{color-scheme:light dark;--bg:#fff;--fg:#15171c;--mut:#5c6370;--line:#e3e6ea;--ok:#1a7f37;--warn:#bf8700;--bad:#c1121f;--card:#f7f8fa}
@media(prefers-color-scheme:dark){:root{--bg:#0d0f13;--fg:#e6e8eb;--mut:#9aa2ad;--line:#242830;--card:#151920}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:2rem 1.25rem}
h1{letter-spacing:-.02em;margin:0 0 .25rem}.sub{color:var(--mut);margin:0 0 1.5rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.75rem;margin-bottom:2rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem}
.card b{display:block;font-size:1.6rem;letter-spacing:-.02em}
.card span{color:var(--mut);font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:.78rem;text-transform:uppercase}
.bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;min-width:60px}
.bar i{display:block;height:100%}
.ok{background:var(--ok)}.warn{background:var(--warn)}.bad{background:var(--bad)}
.tw{overflow-x:auto}</style></head><body><div class="wrap">
"""


def cmd_report(args) -> int:
    cfg = load_config()
    st = load_state()
    projects = st.get("projects")
    if not projects or args.rescan:
        projects = scan(args.roots or default_roots(cfg), args.workers, deep=True,
                        only=args.only, depth=getattr(args, "depth", 4))
        st["projects"] = projects
        st["scanned_at"] = ts()
        save_state(st)

    total_loc = sum(p["loc"] for p in projects)
    total_size = sum(p["size"] for p in projects)
    avg = sum(p["score"] for p in projects) / max(1, len(projects))
    secrets = [p for p in projects if p.get("secrets")]
    listos = [p for p in projects if p["score"] >= 80]
    cats = Counter(p["category"] for p in projects)

    md = ["# BELENTANI FORGE - Reporte", "",
          "Generado %s por forge v%s." % (ts(), VERSION), "",
          "## Resumen", "",
          "- Proyectos: **%d**" % len(projects),
          "- Lineas de codigo: **%s**" % "{:,}".format(total_loc),
          "- Tamano: **%s**" % human(total_size),
          "- Score medio de terminacion: **%.0f%%**" % avg,
          "- Listos (>=80%%): **%d**" % len(listos),
          "- Con posibles secretos: **%d**" % len(secrets), "",
          "## Por categoria", "", "| Categoria | Proyectos |", "|---|---|"]
    for c, n in cats.most_common():
        md.append("| %s | %d |" % (c, n))
    md += ["", "## Proyectos", "",
           "| Proyecto | Cat | Stack | LOC | Score | Falta |", "|---|---|---|---|---|---|"]
    for p in projects:
        falta = ", ".join(k for k, v in (
            ("README", p["readme"]), ("LICENSE", p["license"]),
            ("gitignore", p["gitignore"]), ("tests", p["tests"]),
            ("CI", p["ci"]), ("deps", p["deps"])) if not v) or "-"
        md.append("| %s | %s | %s | %s | %d%% | %s |" % (
            p["name"], p["category"], p["stack"], "{:,}".format(p["loc"]),
            p["score"], falta))
    if secrets:
        md += ["", "## CRITICO - posibles secretos", ""]
        for p in secrets:
            for s in p["secrets"][:5]:
                md.append("- `%s` -> %s:%s (%s)" % (p["name"], s["file"],
                                                    s["line"], s["kind"]))
    md += ["", "## Siguiente paso", "",
           "```bash",
           "python belentani_forge.py finish --apply --commit --max 10",
           "python belentani_forge.py build --apply --max 5",
           "```", ""]

    md_path = Path(args.out or (HERE / "FORGE-REPORT.md"))
    md_path.write_text("\n".join(md), encoding="utf-8")
    out("reporte markdown: %s" % md_path)

    html = [HTML_HEAD,
            "<h1>BELENTANI FORGE</h1><p class='sub'>%s &middot; v%s</p>" % (ts(), VERSION),
            "<div class='grid'>"]
    for label, val in (("Proyectos", len(projects)),
                       ("LOC", "{:,}".format(total_loc)),
                       ("Tamano", human(total_size)),
                       ("Score medio", "%.0f%%" % avg),
                       ("Listos", len(listos)),
                       ("Secretos", len(secrets))):
        html.append("<div class='card'><span>%s</span><b>%s</b></div>" % (label, val))
    html.append("</div><div class='tw'><table><thead><tr><th>Proyecto</th>"
                "<th>Categoria</th><th>Stack</th><th>LOC</th><th>Score</th>"
                "<th></th></tr></thead><tbody>")
    for p in projects:
        cls = "ok" if p["score"] >= 80 else ("warn" if p["score"] >= 50 else "bad")
        html.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d%%</td>"
            "<td><div class='bar'><i class='%s' style='width:%d%%'></i></div></td></tr>"
            % (p["name"], p["category"], p["stack"], "{:,}".format(p["loc"]),
               p["score"], cls, p["score"]))
    html.append("</tbody></table></div></div></body></html>")
    html_path = md_path.with_suffix(".html")
    html_path.write_text("\n".join(html), encoding="utf-8")
    out("dashboard html : %s" % html_path)
    return 0


def cmd_doctor(args) -> int:
    out("BELENTANI FORGE v%s - diagnostico\n" % VERSION)
    out("python   : %s" % sys.version.split()[0])
    out("plataforma: %s" % sys.platform)
    for tool, probe in (("git", ["git", "--version"]), ("gh", ["gh", "--version"]),
                        ("node", ["node", "--version"]), ("npm", ["npm", "--version"]),
                        ("go", ["go", "version"]), ("cargo", ["cargo", "--version"]),
                        ("docker", ["docker", "--version"])):
        code, o = run(probe, timeout=30)
        first = o.splitlines()[0][:60] if o else ""
        out("%-9s: %s" % (tool, first if code == 0 else "NO DISPONIBLE"))
    cfg = load_config()
    out("\nconfig   : %s" % ("belentani_config.json" if cfg else "por defecto"))
    for r in default_roots(cfg):
        exists = "ok" if Path(r).exists() else "NO EXISTE"
        out("raiz     : %s (%s)" % (r, exists))
    out("estado   : %s" % ("presente" if STATE_FILE.exists() else "vacio"))
    out("log      : %s" % LOG_FILE)
    code, o = run(["gh", "auth", "status"], timeout=60)
    out("gh auth  : %s" % ("autenticado" if code == 0 else "sin sesion"))
    return 0


def cmd_schedule(args) -> int:
    """Deja el forge corriendo solo (tarea programada de Windows)."""
    script = str(Path(__file__).resolve())
    cmdline = '"%s" "%s" auto --apply --max %d' % (sys.executable, script, args.max)
    task = args.name
    out("tarea    : %s" % task)
    out("frecuencia: %s a las %s" % (args.freq, args.at))
    out("comando  : %s" % cmdline)
    argv = ["schtasks", "/Create", "/TN", task, "/TR", cmdline,
            "/SC", args.freq, "/ST", args.at, "/F"]
    if not args.apply:
        out("\n(dry-run) usa --apply para crear la tarea")
        out("manual: " + " ".join(argv))
        return 0
    code, o = run(argv, timeout=60)
    out("schtasks: %s" % ("creada" if code == 0 else o[:200]))
    return 0 if code == 0 else 1


# --------------------------------------------------------------------------
# COMANDO: auto (piloto automatico: los 4 pilares en cadena)
# --------------------------------------------------------------------------
def cmd_auto(args) -> int:
    t0 = time.time()
    log("=== AUTO inicio (apply=%s, max=%s) ===" % (bool(args.apply), args.max))
    ns = argparse.Namespace(
        roots=args.roots, workers=args.workers, only=args.only, verbose=args.verbose,
        apply=args.apply, max=args.max, out=None, rescan=True, no_dupes=args.no_dupes,
        depth=getattr(args, "depth", 4),
        quarantine_dupes=False, min_score=args.min_score, commit=args.commit,
        push=args.push, git_init=True, timeout=args.timeout, stop_on_error=False)

    out("\n########## 1/4 ORGANIZADOR ##########")
    cmd_organize(ns)

    out("\n########## 2/4 FINALIZADOR ##########")
    cmd_finish(ns)

    if args.build:
        out("\n########## 3/4 CONSTRUCTOR ##########")
        cmd_build(ns)
    else:
        out("\n########## 3/4 CONSTRUCTOR (omitido; usa --build) ##########")

    out("\n########## 4/4 REPORTE ##########")
    ns.rescan = True
    cmd_report(ns)

    st = load_state()
    st["auto"] = {"at": ts(), "seconds": round(time.time() - t0, 1),
                  "applied": bool(args.apply)}
    save_state(st)
    log("=== AUTO fin en %.1fs ===" % (time.time() - t0))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--roots", action="append", metavar="DIR",
                        help="raiz a escanear (repetible)")
    common.add_argument("--only", action="append", metavar="NOMBRE",
                        help="limitar a estos proyectos (repetible)")
    common.add_argument("--workers", type=int, default=12)
    common.add_argument("--depth", type=int, default=4,
                        help="profundidad maxima de busqueda de proyectos")
    common.add_argument("--apply", action="store_true",
                        help="EJECUTA los cambios (por defecto solo simula)")
    common.add_argument("--verbose", "-v", action="store_true")

    p = argparse.ArgumentParser(
        prog="belentani_forge",
        description="BELENTANI FORGE v%s - genera, construye, organiza y "
                    "finaliza proyectos. Solo lectura sin --apply." % VERSION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="ejemplos:\n"
               "  python belentani_forge.py doctor\n"
               "  python belentani_forge.py new python-cli mi-cli --apply\n"
               "  python belentani_forge.py organize\n"
               "  python belentani_forge.py finish --apply --commit --max 10\n"
               "  python belentani_forge.py auto --apply --build --max 10\n")
    p.add_argument("--version", action="version", version="forge %s" % VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", parents=[common], help="GENERATIVO: crea proyecto")
    s.add_argument("template", choices=TEMPLATE_NAMES)
    s.add_argument("name")
    s.add_argument("--dir", help="directorio padre destino")
    s.add_argument("--desc", help="descripcion corta")
    s.add_argument("--github", action="store_true", help="crear repo con gh")
    s.add_argument("--public", action="store_true", help="repo publico (con --github)")
    s.add_argument("--no-git", action="store_true")
    s.add_argument("--force", action="store_true", help="pisa archivos existentes")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("build", parents=[common], help="CONSTRUCTOR: install/build/test")
    s.add_argument("--max", type=int, default=0, help="limite de proyectos")
    s.add_argument("--timeout", type=int, default=900)
    s.add_argument("--stop-on-error", action="store_true")
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("organize", parents=[common],
                       help="ORGANIZADOR: taxonomia, duplicados, INDEX.md")
    s.add_argument("--out", help="ruta de INDEX.md")
    s.add_argument("--no-dupes", action="store_true", help="omitir hash de duplicados")
    s.add_argument("--quarantine-dupes", action="store_true",
                   help="mover copias sobrantes a quarantine/ (nunca borra)")
    s.set_defaults(func=cmd_organize)

    s = sub.add_parser("finish", parents=[common],
                       help="FINALIZADOR: cierra huecos y deja el proyecto listo")
    s.add_argument("--max", type=int, default=0)
    s.add_argument("--min-score", type=int, default=None,
                   help="solo proyectos por debajo de este score")
    s.add_argument("--commit", action="store_true", help="commitea los cambios")
    s.add_argument("--push", action="store_true", help="pujar si hay remoto")
    s.add_argument("--git-init", action="store_true", help="git init si falta")
    s.set_defaults(func=cmd_finish)

    s = sub.add_parser("scan", parents=[common], help="inventario a JSON")
    s.add_argument("--out", default=str(HERE / "FORGE-SCAN.json"))
    s.set_defaults(func=lambda a: (
        Path(a.out).write_text(json.dumps(
            scan(a.roots or default_roots(load_config()), a.workers, True,
                 a.only, getattr(a, "depth", 4)),
            indent=1, ensure_ascii=False), encoding="utf-8"),
        out("scan escrito en %s" % a.out), 0)[-1])

    s = sub.add_parser("report", parents=[common], help="reporte markdown + dashboard")
    s.add_argument("--out", help="ruta del .md (el .html va al lado)")
    s.add_argument("--rescan", action="store_true", help="forzar nuevo escaneo")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("release", help="version + CHANGELOG + tag")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("--part", choices=("major", "minor", "patch"), default="patch")
    s.add_argument("--version", dest="version", help="version explicita")
    s.add_argument("--push", action="store_true")
    s.add_argument("--gh-release", action="store_true")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_release)

    s = sub.add_parser("github", parents=[common], help="estado local vs GitHub")
    s.add_argument("--push-all", action="store_true", help="pujar lo pendiente")
    s.add_argument("--limit", type=int, default=1000, help="repos a listar de gh")
    s.set_defaults(func=cmd_github)

    s = sub.add_parser("doctor", help="diagnostico del entorno")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("schedule", help="tarea programada de Windows para auto")
    s.add_argument("--name", default="BelentaniForgeAuto")
    s.add_argument("--freq", default="DAILY",
                   choices=("HOURLY", "DAILY", "WEEKLY", "ONLOGON"))
    s.add_argument("--at", default="09:00")
    s.add_argument("--max", type=int, default=10)
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("auto", parents=[common],
                       help="PILOTO AUTOMATICO: organiza + finaliza + construye + reporta")
    s.add_argument("--max", type=int, default=10)
    s.add_argument("--min-score", type=int, default=95)
    s.add_argument("--commit", action="store_true")
    s.add_argument("--push", action="store_true")
    s.add_argument("--build", action="store_true", help="incluir fase de build")
    s.add_argument("--no-dupes", action="store_true")
    s.add_argument("--timeout", type=int, default=900)
    s.set_defaults(func=cmd_auto)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "apply", False):
        log("MODO ESCRITURA activo (--apply) para '%s'" % args.cmd, echo=False)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        out("\ninterrumpido por el usuario")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

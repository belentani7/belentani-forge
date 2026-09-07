# BELENTANI FORGE

Autonomous project engine. Scans, classifies, builds, finishes, and reports across an entire ecosystem of repositories — zero external dependencies, stdlib-only Python.

## What it does

| Pillar | Command | Purpose |
|--------|---------|---------|
| Scanner | `scan` | Read-only inventory of every project found under configurable root dirs |
| Generator | `new` | Creates projects from templates (python-cli, fastapi, node-ts, next, static-web, mcp-server, agent) |
| Builder | `build` | Detects stack and runs install / build / test / lint |
| Organizer | `organize` | Classifies by domain, detects exact duplicates, generates INDEX.md |
| Finisher | `finish` | Scores 0-100 and closes gaps (README, LICENSE, .gitignore, .env.example, CI, smoke tests) |
| Reporter | `report` | Markdown + HTML dashboard |
| GitHub | `github` | Cross-references local repos with GitHub, finds orphans and unpushed commits |
| Doctor | `doctor` | Diagnoses the environment (Python, Git, gh, Node, Docker, etc.) |
| Release | `release` | Version bump + CHANGELOG + tag + optional push + gh release |
| Auto | `auto` | Full autopilot: organize + finish + build + report in one run |

## Safety

Everything is **read-only by default**. No write, move, commit, push, or install happens without `--apply`. Nothing is ever deleted — duplicates and discards go to `quarantine/`.

## Install

```bash
pip install -e .
```

Or run directly:

```bash
python -m forge doctor
```

## Usage

```bash
# Diagnose environment
forge doctor

# Scan all projects (read-only)
forge scan

# Dry-run: see what finish would do
forge finish --max 10

# Actually apply changes
forge finish --apply --commit --max 10

# Full autopilot
forge auto --apply --build --commit --max 10

# Create a new project from template
forge new python-cli my-tool --apply

# Generate report
forge report
```

## Configuration

Set `FORGE_HOME` to control where state/logs/reports go (default: `~/.forge`).

```bash
export FORGE_HOME=~/.forge
export FORGE_AUTHOR="Pedro Belentani"
export FORGE_GH_USER=belentani7
```

Or create `~/.forge/config.json`:

```json
{
  "roots": ["~/Documents/01_PROYECTOS", "~/Desktop"],
  "author": "Pedro Belentani",
  "gh_user": "belentani7"
}
```

## Architecture

```
forge/
  __init__.py      # Package version
  __main__.py      # python -m forge entry point
  engine.py        # Core engine — all CLI commands (1900+ lines, zero deps)
  models.py        # Dataclass models (Project, Issue, ForgeReport, etc.)
  config.py        # Path and category configuration
  scanner.py       # Scan-data loader (reads JSON scan results into models)
  classifier.py    # Classification pipeline (status, category, priority)
  reporter.py      # Report generators (inventory, status, ecosystem map)
tests/
  test_models.py
  test_engine.py
  test_classifier.py
  test_scanner.py
  test_reporter.py
  test_cli.py
```

The **engine** (`engine.py`) is the battle-tested monolith — 1900+ lines of pure stdlib Python that handles everything from scanning the filesystem to generating HTML dashboards. The **modular package** (`models.py`, `scanner.py`, `classifier.py`, `reporter.py`) provides a clean API for programmatic use.

## Project status scoring

Each project is scored 0-100 based on:

| Criterion | Points |
|-----------|--------|
| README | 15 |
| Tests | 18 |
| CI/CD | 12 |
| Dependencies declared | 10 |
| LICENSE | 8 |
| .gitignore | 8 |
| Git repo with remote | 12 |
| >3 commits + pushed | 9 |
| .env.example | 5 |
| >200 LOC | 3 |
| Secrets found | -25 |

## License

MIT

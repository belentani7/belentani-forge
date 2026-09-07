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

### Pipeline commands

| Command | Purpose |
|---------|---------|
| `inventory` | Full pass: scan → classify → verify → dependencies → state → persist |
| `plan` | Prioritised repair queue (P0 security → P6 optimisation), with routed skills |
| `verify` | Definition of Done: what is finished, what needs work, what must not be touched |
| `deps` | Cross-repo dependency map and version conflicts |
| `skills` | Route a task to the few skills it needs |
| `caps` | Audit installed CLIs, configured providers and local models |

## Safety

Everything is **read-only by default**. No write, move, commit, push, or install happens without `--apply`. Nothing is ever deleted — duplicates and discards go to `quarantine/`.

Four rules are enforced in code, not by convention:

- **Secrets are masked** before anything reaches a log, report or manifest. Placeholders (`your_key_here`, `os.environ[...]`) are left readable.
- **Frozen frontend.** Writes to `.css`, `.html`, `.tsx`, `.glsl`, image and font files are refused, as are any writes to the five frozen projects.
- **Destructive commands are blocked.** `git reset --hard`, `git clean -fd` and force pushes raise `SafetyViolation` unless explicitly authorized. There is no global override.
- **Commits are pre-flighted.** `safe_commit` refuses when the tree carries a `.env`, a private key, or a credential-shaped string.

## Idempotency

`forge inventory` can run once or a hundred times. State is keyed on a content
fingerprint, not a timestamp, so unchanged inputs produce byte-identical output
and no spurious diffs.

Project identity is `name + path`, because the same project often exists both
standalone and vendored inside a monorepo. Those are tracked as distinct entries
and reported under `duplicate_names` rather than overwriting each other.

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
  __init__.py         # Package version and public surface
  __main__.py         # python -m forge entry point
  cli.py              # Pipeline commands; delegates the rest to the engine
  engine.py           # Battle-tested monolith — all original CLI commands

  # Foundation
  models.py           # Project, Issue, GitState, ForgeReport
  config.py           # Paths, frozen set, category patterns
  safety.py           # Secret redaction, frozen-frontend and command guards
  executor.py         # Subprocess execution, read-only until --apply

  # Pipeline
  scanner.py          # Loads scan JSON into models, cross-references GitHub
  classifier.py       # Status, category, classification, priority
  verifier.py         # Definition of Done
  dependency_map.py   # Manifest parsing and the cross-repo graph
  project_state.py    # Idempotent state tracking with content fingerprints
  inventory.py        # Orchestrates the full pass and the repair plan

  # Routing
  skills_router.py    # Task intent → the few skills it needs
  capabilities.py     # Installed CLIs, configured providers, local models
  git_manager.py      # Safe git operations
  reporter.py         # Inventory, status, ecosystem map, report
tests/                # 243 tests, stdlib + pytest only
```

The **engine** (`engine.py`) is the battle-tested monolith that handles everything
from scanning the filesystem to generating HTML dashboards. The **modular package**
provides a clean, tested API for programmatic use — every write path routes through
`safety.py` and `executor.py`.

### Data flow

```
scan JSON ──► scanner ──► classifier ──► verifier ──┐
                                                     ├──► inventory ──► reports
GitHub ──────► scanner ──► dependency_map ──────────┤
                           project_state ───────────┘
                                  │
                                  └──► skills_router ──► repair plan
```

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

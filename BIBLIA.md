# BIBLIA.md — belentani-forge

Doctrina del producto del repositorio `belentani-forge` del ecosistema belentani7.

## Visión
BELENTANI FORGE — motor autónomo de proyectos. Escanea, clasifica, construye, finaliza e informa sobre todo un ecosistema de repositorios. Python puro (stdlib-only), cero dependencias externas.

## Misión
Ofrecer un motor autónomo (scanner, generador, builder, organizador, finish, reporter, GitHub, doctor, release, auto) que ponga en orden y verifique repositorios del ecosistema Belentani, con escritura solo bajo `--apply`, nada borrado nunca y secretos enmascarados antes de cualquier log/reporte/manifiesto.

## Stack tecnológico
- Python 3.9+ (`pyproject.toml`, setuptools), stdlib-only (sin dependencias externas en runtime).
- CLI: `forge = "forge.cli:main"` (`python -m forge`, comando `forge`).
- Pruebas: pytest (`testpaths = ["tests"]`, 341 tests, stdlib + pytest).
- Paquete `forge/`: cli.py, engine.py, models.py, config.py, safety.py, executor.py, scanner.py, classifier.py, verifier.py, dependency_map.py, project_state.py, inventory.py, repairer.py, graph.py, skills_router.py, capabilities.py, git_manager.py, reporter.py.
- Carpeta `tests/`: 299+ pruebas.
- Licencia: MIT.

## Reglas de desarrollo
- Protocolo spec-first: PRD → SRS → Design Doc → ADR → Plan → Tests GWT.
- Impeccable: N/A (CLI sin HTML en el motor); pre-ship checklist si se añade dashboard HTML en el reporter.
- Microsoft rules: N/A (Python).
- Seguridad: todo es read-only por defecto; nada se escribe/mueve/commitea/pushea/instala sin `--apply`; secretos enmascarados antes de log/reporte/manifiesto; frontend congelado (no escribir `.css`, `.html`, `.tsx`, `.glsl`, imágenes, fuentes); comandos destructivos bloqueados (`git reset --hard`, `git clean -fd`, push forzado); commits pre-flighted (`safe_commit` rechaza `.env`, claves privadas, credenciales).
- `forge repair` es create-only, idempotente y `--apply`-gateado.
- `gitleaks` antes de cada push; CODEOWNERS `@belentani7`.
- Convenciones de commit: `type(scope): summary` (Conventional Commits).

## Arquitectura
```
belentani-forge/
├── forge/                  # motor (cli, engine, models, config, safety, executor, scanner, classifier, verifier, dependency_map, project_state, inventory, repairer, graph, skills_router, capabilities, git_manager, reporter)
├── tests/                  # pruebas pytest (341 passed)
├── pyproject.toml          # proyecto, script forge, pytest config
├── README.md, LICENSE, CONTRIBUTING.md
├── .env.example
├── AGENTS.md, .gitleaks.toml, CODEOWNERS, SECURITY.md, CODE_OF_CONDUCT.md, CHANGELOG.md
└── .editorconfig, .gitignore
```

## Decisiones de diseño
- Read-only por defecto; `--apply` necesario para cualquier escritura.
- Safe commit: no commitear `.env`, claves privadas ni credenciales.
- Duplicados y descartados van a `quarantine/` (nunca se borra).
- Idempotencia: `forge inventory` y `forge repair --apply` son no-op en segunda ejecución.
- Puntuación de proyectos 0-100 (README, Tests, CI/CD, Dependencias, LICENSE, .gitignore, remoto, commits+pushed, .env.example, LOC, secreto = -25).

## Convenciones de commit
`type(scope): summary` — tipos: feat, fix, docs, chore, refactor, test, perf, style.

## Seguridad
- Reportar vulnerabilidades por el canal privado de GitHub Security (no issues públicos).
- Nunca commitear claves, tokens ni ficheros `.env`.
- Ejecutar `gitleaks` antes de cada push.

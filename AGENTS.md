# Repository Guidelines

## Project Structure & Module Organization

`dtflow/` contains the Python package. Core transformation behavior lives in `core.py`,
`streaming.py`, `pipeline.py`, and `schema.py`; format adapters live in `converters.py` and
`storage/`; reusable helpers belong in `utils/`. The Typer command entry point is
`dtflow/__main__.py`, while command implementations are split under `dtflow/cli/`. Add tests under
`tests/`, mirroring the feature area with names such as `test_pipeline.py` or
`test_cli_transform.py`. User documentation lives in `README.md` and `docs/`; release tooling is in
`scripts/`.

## Build, Test, and Development Commands

- `python -m pip install -e ".[dev]" hatch` installs the package, development tools, and Hatch.
- `dt --help` verifies the local CLI and lists available commands.
- `hatch run test` runs the configured pytest suite; append a path to narrow the run.
- `hatch run test-cov` reports branch-aware coverage and missing lines.
- `hatch run lint:all` runs Flake8, Black and isort checks, plus mypy.
- `hatch run lint:fmt` applies Black and isort formatting.
- `hatch build` creates source and wheel distributions through Hatchling.

Start with a targeted check, for example `pytest tests/test_io.py -v`, before running the full
suite.

## Coding Style & Naming Conventions

Support Python 3.10 and newer. Use four-space indentation, Black's 100-character line length, and
isort's Black profile. Name modules, functions, and variables with `snake_case`; classes with
`PascalCase`; constants with `UPPER_SNAKE_CASE`. Keep the existing functional, chainable API style
and prefer small helpers over new inheritance hierarchies. CLI changes must preserve the documented
stdout/stderr and exit-code contracts. Update `README.md`, `docs/`, or `dtflow/SKILL.md` when public
behavior changes.

## Testing Guidelines

Pytest discovers `test_*.py`/`*_test.py`, `Test*` classes, and `test_*` functions. Mark slow,
integration, and unit tests with the registered markers; async tests use `pytest.mark.asyncio` in
strict mode. Warnings are treated as errors, so address new warnings rather than suppressing them
globally. There is no configured coverage minimum, but new behavior and regressions should include
focused tests.

## Quality Review

Run risk-appropriate local checks. Use `qa_reviewer` only when the user explicitly requests
independent QA; release changes do not require it by default.

## Commit & Pull Request Guidelines

Follow the repository's Conventional Commit style, such as `feat(view): ...`, `fix: ...`,
`docs: ...`, or `chore: ...`; keep each commit focused. Pull requests should explain the user-visible
change, list verification commands, and link relevant issues. Include sample CLI input/output for
command changes and screenshots for TUI changes. Keep generated datasets, credentials, and local
benchmark artifacts out of commits.

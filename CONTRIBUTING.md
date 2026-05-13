# Contributing

Thanks for improving this toolkit.

## Local Setup

Runtime usage has no third-party dependencies:

```bash
python scripts/github_project_crud.py --help
```

For development tooling:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Checks

Run tests with the standard library:

```bash
python -B -m unittest discover -s tests
```

Validate syntax without writing bytecode:

```bash
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in ('scripts/github_project_crud.py', 'tests/test_github_project_crud.py')]"
```

Run linting when optional dev dependencies are installed:

```bash
ruff check .
```

## Security

Do not commit real GitHub tokens, `.env` files, GraphQL responses containing
private repository data, or logs with Authorization headers.

# GitHub Project CRUD Toolkit

Open-source Python CLI tooling for CRUD operations on GitHub Projects v2 boards.

The implementation lives in [`scripts/github_project_crud.py`](scripts/github_project_crud.py)
and is documented in [`scripts/README.md`](scripts/README.md).

## Quick Start

```bash
export GITHUB_TOKEN=github_pat_or_ghp_token
export GITHUB_OWNER=my-org-or-user
export GITHUB_OWNER_TYPE=org
export GITHUB_PROJECT_NUMBER=1
export GITHUB_REPOSITORY=owner/repo

python scripts/github_project_crud.py list-items
```

When installed as a package, the console command is:

```bash
github-project-toolkit --project-version v2 list-items
```

`--project-version` defaults to `v2`, so this is equivalent:

```bash
github-project-toolkit list-items
```

There are no third-party runtime dependencies. `requirements.txt` is present to
make that explicit for users and automation.

The CLI writes best-effort JSON lifecycle and API failure events to syslog under
the `github-project-toolkit` identity. Secrets and command values are not logged.

## Development

Create a local environment if desired:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the standard-library test suite:

```bash
python -m unittest discover -s tests
```

Validate syntax without writing bytecode:

```bash
python -B -m py_compile scripts/github_project_crud.py tests/test_github_project_crud.py
```

Run optional linting when dev dependencies are installed:

```bash
ruff check .
```

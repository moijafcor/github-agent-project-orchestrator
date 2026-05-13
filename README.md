# GitHub Project CRUD Toolkit

A zero-dependency Python 3.11+ CLI for creating, reading, updating, and archiving items on a GitHub Projects v2 board via the GraphQL API.

All configuration is read from environment variables, making it straightforward to wire into CI pipelines, GitHub Actions workflows, and shell scripts without modifying any code.

---

## Features

- Create draft project items
- List all project items with their field values
- List all project fields and single-select options
- Update text, number, and single-select fields
- Archive project items
- Link existing issues or pull requests to the project
- Zero runtime dependencies (Python standard library only)
- All output is newline-terminated JSON — easy to pipe into `jq`
- Best-effort JSON lifecycle events written to syslog (tokens and response bodies are never logged)

---

## Requirements

- Python 3.11 or later
- A GitHub personal access token (classic or fine-grained) with project access

---

## Installation

**Run directly without installing:**

```bash
python scripts/github_project_crud.py --help
```

**Install as a package (exposes the `github-project-toolkit` command):**

```bash
pip install -e .
github-project-toolkit --help
```

**Install dev dependencies for testing and linting:**

```bash
pip install -e ".[dev]"
```

---

## Configuration

All settings are read from environment variables. Copy `.env.example` to `.env` and fill in your values — the script does not load `.env` automatically; use `source .env` or a tool like `direnv`.

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | Yes | Personal access token (classic or fine-grained) |
| `GITHUB_OWNER` | Yes | Organization login or GitHub username that owns the project |
| `GITHUB_OWNER_TYPE` | Yes | `org` for an organization, `user` for a personal account |
| `GITHUB_PROJECT_NUMBER` | Yes | Integer project number shown in the project URL |
| `GITHUB_REPOSITORY` | Yes | Default repository context in `owner/repo` format |
| `GITHUB_API_URL` | No | GraphQL endpoint (default: `https://api.github.com/graphql`) |

`GITHUB_REPOSITORY` sets the repository context for environment validation. Issue and pull request linking resolves content from the URL you provide, so you can link items from any repository your token can reach.

### Token Permissions

**Fine-grained personal access tokens** — grant access to the relevant owner and repositories, then enable:

- Projects: read and write
- Issues: read (when linking issues)
- Pull requests: read (when linking pull requests)
- Metadata: read

**Classic personal access tokens** — the `project` scope is required. Add `repo` when the project or linked content is in a private repository.

Organization projects may also require the organization to allow personal access token access under *Settings > Third-party access*.

---

## Quick Start

```bash
export GITHUB_TOKEN=github_pat_...
export GITHUB_OWNER=my-org
export GITHUB_OWNER_TYPE=org
export GITHUB_PROJECT_NUMBER=1
export GITHUB_REPOSITORY=my-org/my-repo

# List all items
python scripts/github_project_crud.py list-items

# Create a draft item
python scripts/github_project_crud.py create-item --title "OR-0001: Example"

# Move an item to a different status
python scripts/github_project_crud.py update-field \
  --item-id PVTI_xxx \
  --field "Status" \
  --value "In Progress"
```

---

## Commands

All commands print JSON to stdout and exit `0` on success. On failure they print `{"error": "..."}` to stdout and exit `1`.

### `list-items`

Returns all visible project items with their field values.

```bash
python scripts/github_project_crud.py list-items
```

```json
[
  {
    "content": {
      "__typename": "Issue",
      "id": "I_kwDO...",
      "number": 42,
      "state": "OPEN",
      "title": "Fix login bug",
      "url": "https://github.com/my-org/my-repo/issues/42"
    },
    "fields": {
      "Estimate": 3.0,
      "Status": { "name": "In Progress", "option_id": "abc123" },
      "Title": "Fix login bug"
    },
    "id": "PVTI_lADOBdq...",
    "is_archived": false,
    "type": "ISSUE"
  }
]
```

Item types are `ISSUE`, `PULL_REQUEST`, or `DRAFT_ISSUE`. Draft items have a `content` object with `id`, `title`, and `body`; linked items include `url`, `number`, and `state`.

### `list-fields`

Returns all project fields keyed by name, including single-select option names and their IDs.

```bash
python scripts/github_project_crud.py list-fields
```

```json
{
  "Estimate": {
    "data_type": "NUMBER",
    "id": "PVTF_lADOBdq...",
    "name": "Estimate",
    "type": "ProjectV2Field"
  },
  "Status": {
    "data_type": "SINGLE_SELECT",
    "id": "PVTSSF_lADOBdq...",
    "name": "Status",
    "options": {
      "Done": "opt_done_id",
      "In Progress": "opt_in_progress_id",
      "Todo": "opt_todo_id"
    },
    "type": "ProjectV2SingleSelectField"
  }
}
```

Use `list-fields` to find exact field names and option strings before calling `update-field`.

### `create-item`

Creates a draft project item.

```bash
python scripts/github_project_crud.py create-item --title "OR-0001: Example"
python scripts/github_project_crud.py create-item --title "OR-0002: Example" --body "Initial notes"
```

```json
{
  "content": {
    "body": "Initial notes",
    "id": "DI_kwDO...",
    "title": "OR-0002: Example"
  },
  "id": "PVTI_lADOBdq...",
  "isArchived": false,
  "type": "DRAFT_ISSUE"
}
```

### `update-field`

Updates a single field on a project item. Use `--type` to specify the field type (default: `single-select`).

**Single-select field** (default):

```bash
python scripts/github_project_crud.py update-field \
  --item-id PVTI_lADOBdq... \
  --field "Status" \
  --value "Done"
```

**Text field:**

```bash
python scripts/github_project_crud.py update-field \
  --item-id PVTI_lADOBdq... \
  --field "Summary" \
  --type text \
  --value "Updated description"
```

**Number field:**

```bash
python scripts/github_project_crud.py update-field \
  --item-id PVTI_lADOBdq... \
  --field "Estimate" \
  --type number \
  --value 5
```

Option matching is case-sensitive. Run `list-fields` to see exact option names.

### `archive-item`

Archives a project item by its node ID.

```bash
python scripts/github_project_crud.py archive-item --item-id PVTI_lADOBdq...
```

```json
{
  "id": "PVTI_lADOBdq...",
  "isArchived": true
}
```

### `link-issue`

Adds an existing issue to the project.

```bash
python scripts/github_project_crud.py link-issue \
  --issue-url "https://github.com/owner/repo/issues/123"
```

### `link-pr`

Adds an existing pull request to the project.

```bash
python scripts/github_project_crud.py link-pr \
  --pr-url "https://github.com/owner/repo/pull/456"
```

### Error output

All error conditions produce JSON on stdout with a non-zero exit code:

```json
{ "error": "Field not found: Statuss. Available fields: Estimate, Status, Title" }
```

Common errors and their causes:

| Error message | Cause |
|---|---|
| `Missing required environment variable` | One or more required env vars are unset or empty |
| `Could not resolve GitHub Project v2` | Wrong owner, project number, or insufficient token permissions |
| `GitHub API request failed with HTTP 401` | Token missing, expired, or not permitted |
| `GitHub API request failed with HTTP 403` | Token lacks project or repository access |
| `Field not found` | Field name does not match exactly — run `list-fields` |
| `Option not found` | Single-select value does not match exactly — run `list-fields` |
| `Could not resolve issue / pull request` | URL is incorrect or token cannot read that repository |

---

## GitHub Actions Integration

Store your token as a repository or organization secret (e.g. `GH_PROJECT_TOKEN`), then use the script directly in a workflow step.

**Move an issue to "In Progress" when a pull request is opened:**

```yaml
name: Sync project status

on:
  pull_request:
    types: [opened, reopened]

jobs:
  update-board:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Link PR to project
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PROJECT_TOKEN }}
          GITHUB_OWNER: my-org
          GITHUB_OWNER_TYPE: org
          GITHUB_PROJECT_NUMBER: 1
          GITHUB_REPOSITORY: ${{ github.repository }}
        run: |
          python scripts/github_project_crud.py link-pr \
            --pr-url "${{ github.event.pull_request.html_url }}"
```

**Create a draft item from a workflow input:**

```yaml
on:
  workflow_dispatch:
    inputs:
      title:
        required: true
        description: Item title

jobs:
  create-item:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Create project item
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PROJECT_TOKEN }}
          GITHUB_OWNER: my-org
          GITHUB_OWNER_TYPE: org
          GITHUB_PROJECT_NUMBER: 1
          GITHUB_REPOSITORY: my-org/my-repo
        run: |
          python scripts/github_project_crud.py create-item \
            --title "${{ inputs.title }}"
```

**Pipe output into `jq` to extract values for downstream steps:**

```bash
ITEM_ID=$(python scripts/github_project_crud.py create-item --title "New item" | jq -r '.id')
python scripts/github_project_crud.py update-field \
  --item-id "$ITEM_ID" \
  --field "Status" \
  --value "In Progress"
```

---

## Using Multiple Projects

Switch between projects by changing the environment variables — no code changes required:

```bash
GITHUB_OWNER=another-org GITHUB_PROJECT_NUMBER=7 \
  python scripts/github_project_crud.py list-items
```

For user-owned projects:

```bash
export GITHUB_OWNER=my-user
export GITHUB_OWNER_TYPE=user
export GITHUB_PROJECT_NUMBER=2
export GITHUB_REPOSITORY=my-user/my-repo
python scripts/github_project_crud.py list-fields
```

---

## Architecture

The entire implementation is a single file: [`scripts/github_project_crud.py`](scripts/github_project_crud.py).

**Request flow:**

1. CLI arguments are parsed by `argparse`; all required env vars are validated before any API call is made.
2. Every command resolves the project's node ID via `get_project_id()`, which caches the result in-process so subsequent calls within the same invocation are free.
3. All GitHub API calls go through `graphql_request()`, which handles authentication, JSON encoding, timeout (30 s), and error classification.
4. `get_project_items()` and `get_project_fields()` implement cursor-based pagination and follow all `hasNextPage` signals until the full result set is fetched.
5. Results are printed as indented JSON to stdout.

**Logging:**

The CLI writes best-effort JSON events to syslog under the `github-project-toolkit` identity when `syslog` is available (Linux/macOS). Events cover command lifecycle, API error categories, and pagination warnings. The following are never logged: tokens, GraphQL variables, item titles, field values, issue or pull request URLs, and raw API response bodies.

---

## Known Limitations

| Limitation | Detail |
|---|---|
| Assignee and label pagination | Up to 20 assignees and 20 labels are returned per item field value. Items hitting this limit trigger a `user_field_may_be_truncated` or `label_field_may_be_truncated` syslog warning. |
| GitHub Projects v2 only | GitHub Projects v1 (classic) is not supported. |
| Supported field types | `text`, `number`, `single-select`. Date and iteration fields can be read but not written. |
| No bulk operations | Each command targets a single item. Loop in shell or CI for bulk updates. |

---

## Development

```bash
# Create and activate a virtual environment
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

# Run the test suite (41 tests, no network required)
python -m pytest tests/ -v

# Validate syntax without running tests
python -B -m py_compile scripts/github_project_crud.py tests/test_github_project_crud.py

# Lint
ruff check .
```

Tests use only `unittest.mock` — no real GitHub API calls are made. The test suite covers environment validation, URL parsing, API response parsing, error message sanitization, pagination truncation warnings, cache behaviour, and CLI argument handling.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and the contribution checklist.

## Security

See [SECURITY.md](SECURITY.md) for the security policy and responsible disclosure guidance.

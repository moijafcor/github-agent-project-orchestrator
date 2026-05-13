# GitHub Project CRUD Toolkit

A Python 3.11+ toolkit for creating, reading, updating, and archiving items on a GitHub Projects v2 board via the GraphQL API.

It ships in two modes:

- **CLI** (`scripts/github_project_crud.py`) — zero runtime dependencies, pipes JSON to stdout, integrates with CI and shell scripts.
- **MCP server** (`scripts/mcp_server.py`) — wraps the CLI as a local [Model Context Protocol](https://modelcontextprotocol.io) server so Claude Desktop can manage your project board in plain language.

Project identity (owner, type, and board number) is passed as CLI flags or per-call MCP parameters, so the same binary can target different boards without touching any config file. Only `GITHUB_TOKEN` must be set in the environment.

---

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [MCP Server](#mcp-server)
- [GitHub Actions Integration](#github-actions-integration)
- [Using Multiple Projects](#using-multiple-projects)
- [Architecture](#architecture)
- [Known Limitations](#known-limitations)
- [Development](#development)
- [Contributing](#contributing)
- [Security](#security)

---

## Features

### CLI

- Create draft project items
- List all project items with their field values
- List all project fields and single-select options
- Update text, number, and single-select fields
- Archive project items
- Link existing issues or pull requests to the project
- Zero runtime dependencies (Python standard library only)
- All output is newline-terminated JSON — easy to pipe into `jq`
- Best-effort JSON lifecycle events written to syslog (tokens and response bodies are never logged)

### MCP server

- Exposes every CLI operation as an MCP tool callable by Claude Desktop
- Runs entirely on localhost — no public exposure, no external services
- Loads `.env` automatically so the token never appears in conversation history

---

## Requirements

- Python 3.11 or later
- A GitHub personal access token (classic or fine-grained) with project access

---

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).

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

**Install MCP server dependencies (required only for `scripts/mcp_server.py`):**

```bash
pip install -e ".[mcp]"
```

---

## Configuration

### Token (environment variable — required)

| Variable | Required | Description |
| --- | --- | --- |
| `GITHUB_TOKEN` | Yes | Personal access token (classic or fine-grained) |
| `GITHUB_API_URL` | No | GraphQL endpoint (default: `https://api.github.com/graphql`) |

Set `GITHUB_TOKEN` in your shell, a `.env` file (MCP server loads it automatically), or as a CI secret.

### Project identity (CLI flags or environment variables)

| CLI flag | Env var fallback | Description |
| --- | --- | --- |
| `--owner` | `GITHUB_OWNER` | Organization login or GitHub username that owns the project |
| `--owner-type` | `GITHUB_OWNER_TYPE` | `org` for an organization, `user` for a personal account |
| `--project-number` | `GITHUB_PROJECT_NUMBER` | Integer project number shown in the project URL |

CLI flags take precedence over environment variables when both are present. The MCP server receives these as explicit parameters on every tool call.

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

# List all items on project board #1 in my-org
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  list-items

# Create a draft item
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  create-item --title "OR-0001: Example"

# Move an item to a different status
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  update-field \
  --item-id PVTI_xxx \
  --field "Status" \
  --value "In Progress"
```

Flags can go before or after the subcommand name. If you always work against the same board, set the env var equivalents and omit the flags.

---

## Commands

All commands print JSON to stdout and exit `0` on success. On failure they print `{"error": "..."}` to stdout and exit `1`.

### `list-items`

Returns all visible project items with their field values.

```bash
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  list-items
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
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  list-fields
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
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  create-item --title "OR-0001: Example"

python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  create-item --title "OR-0002: Example" --body "Initial notes"
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
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  update-field \
  --item-id PVTI_lADOBdq... \
  --field "Status" \
  --value "Done"
```

**Text field:**

```bash
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  update-field \
  --item-id PVTI_lADOBdq... \
  --field "Summary" \
  --type text \
  --value "Updated description"
```

**Number field:**

```bash
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  update-field \
  --item-id PVTI_lADOBdq... \
  --field "Estimate" \
  --type number \
  --value 5
```

Option matching is case-sensitive. Run `list-fields` to see exact option names.

### `archive-item`

Archives a project item by its node ID.

```bash
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  archive-item --item-id PVTI_lADOBdq...
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
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  link-issue --issue-url "https://github.com/owner/repo/issues/123"
```

### `link-pr`

Adds an existing pull request to the project.

```bash
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  link-pr --pr-url "https://github.com/owner/repo/pull/456"
```

### Error output

All error conditions produce JSON on stdout with a non-zero exit code:

```json
{ "error": "Field not found: Statuss. Available fields: Estimate, Status, Title" }
```

Common errors and their causes:

| Error message | Cause |
| --- | --- |
| `Missing required environment variable` | `GITHUB_TOKEN` is unset or empty |
| `Missing required environment variable(s): GITHUB_OWNER` | Flags not passed and env var not set |
| `Could not resolve GitHub Project v2` | Wrong owner, project number, or insufficient token permissions |
| `GitHub API request failed with HTTP 401` | Token missing, expired, or not permitted |
| `GitHub API request failed with HTTP 403` | Token lacks project or repository access |
| `Field not found` | Field name does not match exactly — run `list-fields` |
| `Option not found` | Single-select value does not match exactly — run `list-fields` |
| `Could not resolve issue / pull request` | URL is incorrect or token cannot read that repository |

---

## MCP Server

`scripts/mcp_server.py` wraps the toolkit as a [Model Context Protocol](https://modelcontextprotocol.io) server. Once running, Claude Desktop on the same machine can create items, update fields, link issues, and archive cards using plain English — no command-line required.

**Connection model:**

```text
Claude Desktop (your workstation)
        ↓ http://127.0.0.1:8765/sse   (never leaves the machine)
  MCP server — scripts/mcp_server.py
        ↓
  github_project_crud.py
        ↓
  GitHub GraphQL API (api.github.com)
```

### Prerequisites

Install the two extra dependencies (not needed for the plain CLI):

```bash
pip install "mcp[cli]>=1.0" "python-dotenv>=1.0"
# or via the package extra:
pip install -e ".[mcp]"
```

### Environment setup

The MCP server loads `.env` from the project root automatically. Only `GITHUB_TOKEN` is required there — owner and project context are passed as parameters on each tool call.

```bash
# .env
GITHUB_TOKEN=github_pat_...
```

### Running the server

```bash
cd /path/to/github-agent-project-orchestrator
python scripts/mcp_server.py
# Serving on http://127.0.0.1:8765 (SSE)
```

Keep this terminal open while using Claude Desktop.

### Claude Desktop configuration

Add the server to your Claude Desktop config. Default locations by platform:

| Platform | Path |
| --- | --- |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "github_projects": {
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

Restart Claude Desktop after saving. You should see **GitHub Projects** appear in the tool list.

### Available MCP tools

Every tool requires `owner`, `owner_type`, and `project_number` — pass them on every call.

| Tool | Description |
| --- | --- |
| `list_project_items` | Return all items on the board with their field values |
| `list_project_fields` | Return all fields and single-select options |
| `create_project_item` | Create a new draft item (`title`, optional `body`) |
| `update_project_item_field` | Update a field by item ID (`field_type`: `text`, `number`, `single-select`) |
| `archive_project_item` | Archive an item by its node ID |
| `link_issue_to_project` | Add an existing issue to the board by URL |
| `link_pr_to_project` | Add an existing pull request to the board by URL |

### Example prompts

Once connected, you can say things like:

- "Show me everything on the AdsWireIO project board #1."
- "Create a task called 'Migrate auth service to OAuth 2.1' with a description of the acceptance criteria."
- "Move item PVTI_xxx to Done."
- "Archive all items with status Cancelled." *(Claude will call `list_project_items` then loop over matching IDs)*
- "Link `https://github.com/my-org/my-repo/issues/99` to the project and set its status to In Progress."

The server always returns structured JSON; Claude formats it in the conversation.

### Security notes

- The server binds to `127.0.0.1` only and is never reachable from the internet.
- `GITHUB_TOKEN` is read from the local `.env` file and is never sent to Claude or logged.
- SSE connections are unauthenticated on localhost — do not change the bind address.

---

## GitHub Actions Integration

Store your token as a repository or organization secret (e.g. `GH_PROJECT_TOKEN`), then use the script directly in a workflow step. Pass owner and project identity as CLI flags so each workflow controls its own target board.

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
        run: |
          python scripts/github_project_crud.py \
            --owner my-org --owner-type org --project-number 1 \
            link-pr --pr-url "${{ github.event.pull_request.html_url }}"
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
        run: |
          python scripts/github_project_crud.py \
            --owner my-org --owner-type org --project-number 1 \
            create-item --title "${{ inputs.title }}"
```

**Pipe output into `jq` to extract values for downstream steps:**

```bash
ITEM_ID=$(python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  create-item --title "New item" | jq -r '.id')

python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  update-field --item-id "$ITEM_ID" --field "Status" --value "In Progress"
```

---

## Using Multiple Projects

Pass different flags per invocation — no env var changes required:

```bash
# Org project
python scripts/github_project_crud.py \
  --owner my-org --owner-type org --project-number 1 \
  list-items

# Another org, different board
python scripts/github_project_crud.py \
  --owner another-org --owner-type org --project-number 7 \
  list-items

# User-owned project
python scripts/github_project_crud.py \
  --owner my-user --owner-type user --project-number 2 \
  list-fields
```

If you always target the same board, set `GITHUB_OWNER`, `GITHUB_OWNER_TYPE`, and `GITHUB_PROJECT_NUMBER` as env vars and omit the flags entirely.

---

## Architecture

The toolkit has two entry points that share the same core library:

| File | Role |
| --- | --- |
| [`scripts/github_project_crud.py`](scripts/github_project_crud.py) | Core library + CLI (`argparse`) |
| [`scripts/mcp_server.py`](scripts/mcp_server.py) | MCP server thin wrapper (`FastMCP`) |

### CLI request flow

1. CLI arguments are parsed by `argparse`; `--owner`, `--owner-type`, and `--project-number` flags are applied to the environment before validation, overriding any corresponding env vars.
2. Every command resolves the project's node ID via `get_project_id()`, which caches the result in-process so subsequent calls within the same invocation are free.
3. All GitHub API calls go through `graphql_request()`, which handles authentication, JSON encoding, timeout (30 s), and error classification.
4. `get_project_items()` and `get_project_fields()` implement cursor-based pagination and follow all `hasNextPage` signals until the full result set is fetched.
5. Results are printed as indented JSON to stdout.

### MCP server flow

`mcp_server.py` imports `github_project_crud` directly and registers each public function as a `FastMCP` tool. Each tool call invokes `_apply_context()`, which sets the three project env vars and clears the in-process cache — making it safe to target different boards in the same server session. Tool return values are serialized JSON strings so Claude can read and summarize them. The server runs a persistent SSE loop on `127.0.0.1:8765`; Claude Desktop connects once and reuses the connection for the lifetime of the conversation.

### Logging

The CLI writes best-effort JSON events to syslog under the `github-project-toolkit` identity when `syslog` is available (Linux/macOS). Events cover command lifecycle, API error categories, and pagination warnings. The following are never logged: tokens, GraphQL variables, item titles, field values, issue or pull request URLs, and raw API response bodies.

---

## Known Limitations

| Limitation | Detail |
| --- | --- |
| Assignee and label pagination | Up to 20 assignees and 20 labels are returned per item field value. Items hitting this limit trigger a `user_field_may_be_truncated` or `label_field_may_be_truncated` syslog warning. |
| GitHub Projects v2 only | GitHub Projects v1 (classic) is not supported. |
| Supported field types | `text`, `number`, `single-select`. Date and iteration fields can be read but not written. |
| No bulk operations | Each command targets a single item. Loop in shell or CI for bulk updates. |

---

## Development

```bash
# Create and activate a virtual environment
python3 -m venv .venv
. .venv/bin/activate

# CLI only
pip install -e ".[dev]"

# CLI + MCP server
pip install -e ".[dev,mcp]"

# Run the test suite (40 tests, no network required)
python -m pytest tests/ -v

# Validate syntax without running tests
python -B -m py_compile scripts/github_project_crud.py scripts/mcp_server.py tests/test_github_project_crud.py

# Lint
ruff check .
```

Tests use only `unittest.mock` — no real GitHub API calls are made. The test suite covers environment validation, URL parsing, API response parsing, error message sanitization, pagination truncation warnings, cache behaviour, and CLI argument handling.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and the contribution checklist.

## Security

See [SECURITY.md](SECURITY.md) for the security policy and responsible disclosure guidance.

# Agent Instructions — GitHub Project CRUD Toolkit

This file tells AI agents how to use this repository to manage a GitHub Projects v2 board.

---

## What this repository provides

Two interfaces to the same GitHub GraphQL API:

| Interface | Entry point | When to use |
| --- | --- | --- |
| CLI | `scripts/github_project_crud.py` | CI pipelines, shell scripts, one-off commands |
| MCP server | `scripts/mcp_server.py` | Conversational agents via Claude Desktop (SSE on `127.0.0.1:8765`) |

All responses are JSON. All mutations target the board configured in environment variables.

---

## Environment variables

The following must be set before any tool or CLI call will succeed:

| Variable | Example | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | `github_pat_...` | PAT with Projects read+write scope |
| `GITHUB_OWNER` | `my-org` | Owner login (org or user) |
| `GITHUB_OWNER_TYPE` | `org` or `user` | Determines GraphQL query shape |
| `GITHUB_PROJECT_NUMBER` | `1` | Integer from the project URL |
| `GITHUB_REPOSITORY` | `my-org/my-repo` | Repository context for validation |

The MCP server loads `.env` from the project root automatically. The CLI does not — export variables or use `source .env`.

---

## MCP tools (preferred interface for conversational agents)

Connect to `http://127.0.0.1:8765/sse` when the server is running. The following tools are available:

### `list_project_items`

Returns all items on the board as a JSON array.

**Always call this first** before any mutation so you know what exists and can obtain the item node IDs (`PVTI_...`) required by other tools.

```json
[
  {
    "id": "PVTI_lADOBdq...",
    "type": "ISSUE",
    "is_archived": false,
    "content": { "title": "Fix login bug", "number": 42, "state": "OPEN", "url": "..." },
    "fields": {
      "Status": { "name": "In Progress", "option_id": "abc123" },
      "Estimate": 3.0
    }
  }
]
```

Item types: `ISSUE`, `PULL_REQUEST`, `DRAFT_ISSUE`.

---

### `list_project_fields`

Returns all field definitions keyed by name, including option IDs for single-select fields.

Call this before `update_project_item_field` to confirm exact field names and option strings (both are case-sensitive).

```json
{
  "Status": {
    "id": "PVTSSF_...",
    "data_type": "SINGLE_SELECT",
    "options": { "Todo": "opt_1", "In Progress": "opt_2", "Done": "opt_3" }
  },
  "Estimate": { "id": "PVTF_...", "data_type": "NUMBER" }
}
```

---

### `create_project_item`

Creates a new draft item. Returns the created item including its `id`.

Parameters:
- `title` (required) — item title
- `body` (optional) — markdown description

```json
{ "id": "PVTI_...", "type": "DRAFT_ISSUE", "content": { "title": "...", "body": "..." } }
```

---

### `update_project_item_field`

Updates one field on one item. Requires the item node ID from `list_project_items`.

Parameters:
- `item_id` — `PVTI_...` node ID
- `field` — exact field name (case-sensitive)
- `value` — new value
- `field_type` — `single-select` (default), `text`, or `number`

For `single-select`, `value` must be an exact option name from `list_project_fields`. To update multiple fields, call this tool once per field.

---

### `archive_project_item`

Soft-deletes an item. Archived items no longer appear in `list_project_items` results.

Parameters:
- `item_id` — `PVTI_...` node ID

---

### `link_issue_to_project`

Adds an existing GitHub Issue to the board.

Parameters:
- `issue_url` — full URL, e.g. `https://github.com/owner/repo/issues/42`

---

### `link_pr_to_project`

Adds an existing Pull Request to the board.

Parameters:
- `pr_url` — full URL, e.g. `https://github.com/owner/repo/pull/7`

---

## Recommended workflows

### Moving an item to a new status

```
1. list_project_fields          → confirm exact option name for Status field
2. list_project_items           → find the item, copy its id
3. update_project_item_field    → field="Status", value="Done", field_type="single-select"
```

### Creating and configuring a new task

```
1. list_project_fields          → confirm field names and option values
2. create_project_item          → capture returned id
3. update_project_item_field    → set Status
4. update_project_item_field    → set Estimate or other fields (one call per field)
```

### Bulk status updates (e.g. archive all Cancelled items)

```
1. list_project_items           → filter locally for items where fields.Status.name == "Cancelled"
2. archive_project_item         → call once per matching item id
```

There is no bulk mutation endpoint — loop over individual IDs.

---

## Error handling

Every tool returns a plain string. On failure the string begins with `Error:` followed by a human-readable message. Do not treat these as exceptions; check the return value.

| Error prefix | Meaning | Recovery |
| --- | --- | --- |
| `Error: Missing required environment variable` | Env not configured | Check `.env` / environment |
| `Error: Could not resolve GitHub Project v2` | Wrong owner or project number | Verify `GITHUB_OWNER` and `GITHUB_PROJECT_NUMBER` |
| `Error: GitHub API request failed with HTTP 401` | Token invalid or expired | Rotate `GITHUB_TOKEN` |
| `Error: GitHub API request failed with HTTP 403` | Token lacks project scope | Add Projects read+write permission |
| `Error: Field not found: X` | Field name mismatch | Call `list_project_fields` and use exact name |
| `Error: Option not found for field 'X': Y` | Option name mismatch | Call `list_project_fields` and use exact option string |

---

## CLI quick reference (when MCP server is not available)

```bash
# List items
python scripts/github_project_crud.py list-items

# Create draft item
python scripts/github_project_crud.py create-item --title "Task title" --body "Details"

# Update a single-select field
python scripts/github_project_crud.py update-field \
  --item-id PVTI_... --field "Status" --value "Done"

# Archive an item
python scripts/github_project_crud.py archive-item --item-id PVTI_...

# Link an issue
python scripts/github_project_crud.py link-issue \
  --issue-url "https://github.com/owner/repo/issues/42"
```

All commands exit `0` on success and `1` on failure. Output is always JSON.

---

## Constraints and limits

- **No bulk mutations** — every write targets a single item; loop for bulk operations.
- **Field types** — only `text`, `number`, and `single-select` fields can be written; date and iteration fields are read-only.
- **Option matching is case-sensitive** — `"in progress"` will fail if the option is `"In Progress"`.
- **Assignee and label fields** — capped at 20 entries per item; a syslog warning is emitted when the limit is hit.
- **Projects v2 only** — GitHub Projects v1 (classic) is not supported.
- **MCP server is localhost-only** — do not change the bind address or expose it publicly.

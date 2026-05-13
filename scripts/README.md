# GitHub Project CRUD Toolkit

`github_project_crud.py` is a small Python 3.11+ CLI for creating, listing,
updating, archiving, and linking items in a GitHub Projects v2 board.

It uses only the Python standard library and reads all target configuration from
environment variables.

The installed console command is `github-project-toolkit`. The
`--project-version` flag defaults to `v2`; only GitHub Projects v2 is currently
supported.

## Required Environment Variables

```bash
export GITHUB_TOKEN=github_pat_or_ghp_token
export GITHUB_OWNER=my-org-or-user
export GITHUB_OWNER_TYPE=org
export GITHUB_PROJECT_NUMBER=1
export GITHUB_REPOSITORY=owner/repo
```

`GITHUB_OWNER_TYPE` must be either `org` or `user`.

`GITHUB_REPOSITORY` is used as the default repository context for validation and
future reuse. Issue and pull request linking commands resolve content from the
URL you provide, so they can link items from any repository your token can read.

Optional:

```bash
export GITHUB_API_URL=https://api.github.com/graphql
```

## Token Permissions

Use a token that can read and write the target Project v2 board.

For fine-grained personal access tokens, grant access to the relevant owner and
repositories, then enable permissions that cover:

- Projects: read and write
- Issues: read, when linking issues
- Pull requests: read, when linking pull requests
- Metadata: read

For classic tokens, `project` is required for project access. Add `repo` when
the project or linked issues and pull requests are private.

Organization projects may also require the organization to allow personal access
token access.

## Commands

Create a draft Project item:

```bash
python scripts/github_project_crud.py create-item --title "OR-0001: Example"
python scripts/github_project_crud.py create-item --title "OR-0002: Example" --body "Notes"
github-project-toolkit --project-version v2 create-item --title "OR-0001: Example"
```

List Project items:

```bash
python scripts/github_project_crud.py list-items
```

List fields and single-select options:

```bash
python scripts/github_project_crud.py list-fields
```

Update a text field:

```bash
python scripts/github_project_crud.py update-field \
  --item-id ITEM_ID \
  --field "Summary" \
  --type text \
  --value "New summary"
```

Update a number field:

```bash
python scripts/github_project_crud.py update-field \
  --item-id ITEM_ID \
  --field "Estimate" \
  --type number \
  --value 3
```

Update a single-select field:

```bash
python scripts/github_project_crud.py update-field \
  --item-id ITEM_ID \
  --field "Status" \
  --value "EIPM Approved"
```

Archive a Project item:

```bash
python scripts/github_project_crud.py archive-item --item-id ITEM_ID
```

Add an existing issue to the Project:

```bash
python scripts/github_project_crud.py link-issue \
  --issue-url "https://github.com/owner/repo/issues/123"
```

Add an existing pull request to the Project:

```bash
python scripts/github_project_crud.py link-pr \
  --pr-url "https://github.com/owner/repo/pull/456"
```

All commands print JSON. Failures also print JSON and exit with a non-zero
status code.

## Using Multiple Projects

Point the same script at a different Project v2 board by changing the
environment variables:

```bash
export GITHUB_OWNER=another-org
export GITHUB_OWNER_TYPE=org
export GITHUB_PROJECT_NUMBER=7
export GITHUB_REPOSITORY=another-org/service-api
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

No project IDs, owner names, repository names, field names, or option IDs are
hardcoded. Field IDs and single-select option IDs are resolved from the target
project during each execution.

## Troubleshooting

`Missing required environment variable`

Set every required variable before running the command. `GITHUB_PROJECT_NUMBER`
must be a number, and `GITHUB_REPOSITORY` must use `owner/repo` format.

`Could not resolve GitHub Project v2`

Check `GITHUB_OWNER`, `GITHUB_OWNER_TYPE`, and `GITHUB_PROJECT_NUMBER`. Also
confirm the token can access the project.

`Field not found`

Run `list-fields` and use the exact field name shown in the JSON output.

`Option not found`

Run `list-fields` and use the exact single-select option name. Option matching
is case-sensitive.

`GitHub API HTTP 401` or `403`

The token is missing, expired, blocked by organization policy, or does not have
the required project/repository permissions.

`Could not resolve issue` or `Could not resolve pull request`

Confirm the URL is correct and that the token can read the repository containing
the issue or pull request.

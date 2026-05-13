#!/usr/bin/env python3
"""Small GitHub Projects v2 CRUD toolkit.

Configuration is read from environment variables so the same script can be used
across repositories, organizations, users, and project boards.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

try:
    import syslog
except ImportError:  # pragma: no cover - syslog is Unix-specific.
    syslog = None  # type: ignore[assignment]


DEFAULT_API_URL = "https://api.github.com/graphql"
DEFAULT_PROJECT_VERSION = "v2"
SYSLOG_IDENT = "github-project-toolkit"
SUPPORTED_PROJECT_VERSIONS = {DEFAULT_PROJECT_VERSION}
REQUIRED_ENV = (
    "GITHUB_TOKEN",
    "GITHUB_OWNER",
    "GITHUB_OWNER_TYPE",
    "GITHUB_PROJECT_NUMBER",
    "GITHUB_REPOSITORY",
)

_cache: dict[str, Any] = {}
_syslog_opened = False
GITHUB_CONTENT_URL_RE = re.compile(
    r"^https://github\.com/([^/\s]+)/([^/\s]+)/(issues|pull)/([0-9]+)(?:[/?#].*)?$"
)


class ProjectCrudError(Exception):
    """Raised for user-facing command failures."""


def log_event(level: str, event: str, **fields: Any) -> None:
    """Write a compact JSON event to syslog when syslog is available."""

    if syslog is None:
        return

    global _syslog_opened
    priority_by_level = {
        "debug": syslog.LOG_DEBUG,
        "info": syslog.LOG_INFO,
        "warning": syslog.LOG_WARNING,
        "error": syslog.LOG_ERR,
    }
    priority = priority_by_level.get(level, syslog.LOG_INFO)
    payload = {"event": event, **fields}
    try:
        if not _syslog_opened:
            syslog.openlog(SYSLOG_IDENT, syslog.LOG_PID, syslog.LOG_USER)
            _syslog_opened = True
        syslog.syslog(priority, json.dumps(payload, sort_keys=True, separators=(",", ":")))
    except Exception:
        # Logging must never break CLI behavior.
        return


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise ProjectCrudError(f"Missing required environment variable: {name}")
    return value


def validate_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise ProjectCrudError(f"Missing required environment variable(s): {joined}")

    owner_type = env("GITHUB_OWNER_TYPE").lower()
    if owner_type not in {"org", "user"}:
        raise ProjectCrudError("GITHUB_OWNER_TYPE must be either 'org' or 'user'")

    project_number = env("GITHUB_PROJECT_NUMBER")
    if not project_number.isdigit():
        raise ProjectCrudError("GITHUB_PROJECT_NUMBER must be an integer")

    repository = env("GITHUB_REPOSITORY")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise ProjectCrudError("GITHUB_REPOSITORY must be in owner/repo format")


def validate_project_version(project_version: str) -> None:
    normalized = project_version.lower()
    if normalized not in SUPPORTED_PROJECT_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_PROJECT_VERSIONS))
        raise ProjectCrudError(
            f"Unsupported GitHub Project version: {project_version}. "
            f"Supported version(s): {supported}"
        )


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def graphql_request(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a GraphQL request to GitHub and return the response data object."""

    validate_env()
    payload = json.dumps(
        {"query": query, "variables": variables or {}},
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        env("GITHUB_API_URL", DEFAULT_API_URL),
        data=payload,
        headers={
            "Authorization": f"Bearer {env('GITHUB_TOKEN')}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-project-toolkit",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        log_event("warning", "github_api_http_error", status_code=exc.code, response_size=len(body))
        raise ProjectCrudError(f"GitHub API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        log_event("warning", "github_api_url_error", reason_type=type(exc.reason).__name__)
        raise ProjectCrudError(f"Could not reach GitHub API: {exc.reason}") from exc

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        log_event("warning", "github_api_invalid_json", response_size=len(body))
        raise ProjectCrudError("GitHub API returned invalid JSON") from exc

    if decoded.get("errors"):
        log_event("warning", "github_api_graphql_errors", error_count=len(decoded["errors"]))
        raise ProjectCrudError(json.dumps({"errors": decoded["errors"]}, indent=2))

    data = decoded.get("data")
    if data is None:
        log_event("warning", "github_api_missing_data", response_size=len(body))
        raise ProjectCrudError("GitHub API response did not include data")
    return data


def get_project_id() -> str:
    """Resolve the configured Project v2 ID."""

    if "project_id" in _cache:
        return _cache["project_id"]

    owner_type = env("GITHUB_OWNER_TYPE").lower()
    field = "organization" if owner_type == "org" else "user"
    query = f"""
    query($login: String!, $number: Int!) {{
      {field}(login: $login) {{
        projectV2(number: $number) {{
          id
          number
          title
        }}
      }}
    }}
    """
    data = graphql_request(
        query,
        {"login": env("GITHUB_OWNER"), "number": int(env("GITHUB_PROJECT_NUMBER"))},
    )
    owner = data.get(field) or {}
    project = owner.get("projectV2")
    if not project:
        raise ProjectCrudError(
            "Could not resolve GitHub Project v2 "
            f"{env('GITHUB_OWNER')}/{env('GITHUB_PROJECT_NUMBER')}"
        )

    _cache["project"] = project
    _cache["project_id"] = project["id"]
    return _cache["project_id"]


def _field_from_node(node: dict[str, Any]) -> dict[str, Any]:
    field = {
        "id": node["id"],
        "name": node["name"],
        "data_type": node.get("dataType"),
        "type": node.get("__typename"),
    }
    if node.get("options") is not None:
        field["options"] = {
            option["name"]: option["id"]
            for option in node["options"]
            if isinstance(option, dict) and "name" in option and "id" in option
        }
    return field


def get_project_fields() -> dict[str, dict[str, Any]]:
    """Return project fields keyed by field name."""

    if "fields" in _cache:
        return _cache["fields"]

    fields: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    query = """
    query($projectId: ID!, $cursor: String) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 100, after: $cursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              __typename
              ... on ProjectV2Field {
                id
                name
                dataType
              }
              ... on ProjectV2SingleSelectField {
                id
                name
                dataType
                options {
                  id
                  name
                }
              }
              ... on ProjectV2IterationField {
                id
                name
                dataType
              }
            }
          }
        }
      }
    }
    """

    while True:
        data = graphql_request(query, {"projectId": get_project_id(), "cursor": cursor})
        project = data.get("node") or {}
        field_connection = project.get("fields")
        if not field_connection:
            raise ProjectCrudError("Could not read project fields")

        for node in field_connection.get("nodes") or []:
            if node and node.get("name"):
                fields[node["name"]] = _field_from_node(node)

        page_info = field_connection["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    _cache["fields"] = fields
    return fields


def get_project_items() -> list[dict[str, Any]]:
    """Return all visible project items with field values."""

    items: list[dict[str, Any]] = []
    item_cursor: str | None = None
    query = """
    query($projectId: ID!, $itemCursor: String) {
      node(id: $projectId) {
        ... on ProjectV2 {
          items(first: 100, after: $itemCursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              id
              type
              isArchived
              content {
                __typename
                ... on Issue {
                  id
                  title
                  url
                  number
                  state
                }
                ... on PullRequest {
                  id
                  title
                  url
                  number
                  state
                }
                ... on DraftIssue {
                  id
                  title
                  body
                }
              }
              fieldValues(first: 100) {
                pageInfo {
                  hasNextPage
                  endCursor
                }
                nodes {
                  __typename
                  ... on ProjectV2ItemFieldTextValue {
                    text
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldNumberValue {
                    number
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    optionId
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldDateValue {
                    date
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldUserValue {
                    users(first: 20) {
                      nodes {
                        login
                      }
                    }
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldLabelValue {
                    labels(first: 20) {
                      nodes {
                        name
                      }
                    }
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldRepositoryValue {
                    repository {
                      nameWithOwner
                    }
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldMilestoneValue {
                    milestone {
                      title
                    }
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    while True:
        data = graphql_request(
            query,
            {"projectId": get_project_id(), "itemCursor": item_cursor},
        )
        project = data.get("node") or {}
        item_connection = project.get("items")
        if not item_connection:
            raise ProjectCrudError("Could not read project items")

        for node in item_connection.get("nodes") or []:
            if not node:
                continue
            items.append(_normalize_item(_hydrate_item_field_values(node)))

        page_info = item_connection["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        item_cursor = page_info["endCursor"]

    return items


def _hydrate_item_field_values(item: dict[str, Any]) -> dict[str, Any]:
    """Fetch additional fieldValues pages for an item when the first page was truncated."""
    field_values = item.get("fieldValues") or {}
    page_info = field_values.get("pageInfo") or {}
    if not page_info.get("hasNextPage"):
        return item

    nodes = list(field_values.get("nodes") or [])
    hydrated = {**item, "fieldValues": {**field_values, "nodes": nodes}}
    cursor = page_info.get("endCursor")
    query = """
    query($itemId: ID!, $cursor: String) {
      node(id: $itemId) {
        ... on ProjectV2Item {
          fieldValues(first: 100, after: $cursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              __typename
              ... on ProjectV2ItemFieldTextValue {
                text
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
              ... on ProjectV2ItemFieldNumberValue {
                number
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                optionId
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
              ... on ProjectV2ItemFieldDateValue {
                date
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
              ... on ProjectV2ItemFieldUserValue {
                users(first: 20) {
                  nodes {
                    login
                  }
                }
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
              ... on ProjectV2ItemFieldLabelValue {
                labels(first: 20) {
                  nodes {
                    name
                  }
                }
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
              ... on ProjectV2ItemFieldRepositoryValue {
                repository {
                  nameWithOwner
                }
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
              ... on ProjectV2ItemFieldMilestoneValue {
                milestone {
                  title
                }
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    while True:
        data = graphql_request(query, {"itemId": item["id"], "cursor": cursor})
        node = data.get("node") or {}
        connection = node.get("fieldValues")
        if not connection:
            raise ProjectCrudError(f"Could not read field values for item: {item['id']}")

        nodes.extend(connection.get("nodes") or [])
        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    hydrated["fieldValues"]["nodes"] = nodes
    hydrated["fieldValues"]["pageInfo"] = {"hasNextPage": False, "endCursor": None}
    return hydrated


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Transform a raw GraphQL project item node into a flat, consistent dict."""
    values: dict[str, Any] = {}
    for node in (item.get("fieldValues") or {}).get("nodes") or []:
        field = node.get("field") or {}
        name = field.get("name")
        if not name:
            continue

        typename = node.get("__typename")
        if typename == "ProjectV2ItemFieldTextValue":
            values[name] = node.get("text")
        elif typename == "ProjectV2ItemFieldNumberValue":
            values[name] = node.get("number")
        elif typename == "ProjectV2ItemFieldSingleSelectValue":
            values[name] = {"name": node.get("name"), "option_id": node.get("optionId")}
        elif typename == "ProjectV2ItemFieldDateValue":
            values[name] = node.get("date")
        elif typename == "ProjectV2ItemFieldUserValue":
            users = (node.get("users") or {}).get("nodes") or []
            if len(users) >= 20:
                log_event("warning", "user_field_may_be_truncated", item_id=item.get("id"), field=name)
            values[name] = [user.get("login") for user in users]
        elif typename == "ProjectV2ItemFieldLabelValue":
            labels = (node.get("labels") or {}).get("nodes") or []
            if len(labels) >= 20:
                log_event("warning", "label_field_may_be_truncated", item_id=item.get("id"), field=name)
            values[name] = [label.get("name") for label in labels]
        elif typename == "ProjectV2ItemFieldRepositoryValue":
            repository = node.get("repository") or {}
            values[name] = repository.get("nameWithOwner")
        elif typename == "ProjectV2ItemFieldMilestoneValue":
            milestone = node.get("milestone") or {}
            values[name] = milestone.get("title")

    content = item.get("content")
    return {
        "id": item["id"],
        "type": item.get("type"),
        "is_archived": item.get("isArchived"),
        "content": content,
        "fields": values,
    }


def create_draft_item(title: str, body: str | None = None) -> dict[str, Any]:
    """Create a new draft issue in the configured GitHub Project and return the created item."""
    mutation = """
    mutation($projectId: ID!, $title: String!, $body: String) {
      addProjectV2DraftIssue(input: {projectId: $projectId, title: $title, body: $body}) {
        projectItem {
          id
          type
          isArchived
          content {
            ... on DraftIssue {
              id
              title
              body
            }
          }
        }
      }
    }
    """
    data = graphql_request(mutation, {"projectId": get_project_id(), "title": title, "body": body})
    result = (data.get("addProjectV2DraftIssue") or {}).get("projectItem")
    if result is None:
        raise ProjectCrudError("GitHub API returned unexpected response for create-item")
    return result


def archive_item(item_id: str) -> dict[str, Any]:
    """Archive a project item by its node ID and return the updated item."""
    mutation = """
    mutation($projectId: ID!, $itemId: ID!) {
      archiveProjectV2Item(input: {projectId: $projectId, itemId: $itemId}) {
        item {
          id
          isArchived
        }
      }
    }
    """
    data = graphql_request(mutation, {"projectId": get_project_id(), "itemId": item_id})
    result = (data.get("archiveProjectV2Item") or {}).get("item")
    if result is None:
        raise ProjectCrudError("GitHub API returned unexpected response for archive-item")
    return result


def _get_field(field_name: str) -> dict[str, Any]:
    fields = get_project_fields()
    field = fields.get(field_name)
    if not field:
        available = ", ".join(sorted(fields)) or "(none)"
        raise ProjectCrudError(f"Field not found: {field_name}. Available fields: {available}")
    return field


def _update_field_value(item_id: str, field_name: str, value: dict[str, Any]) -> dict[str, Any]:
    field = _get_field(field_name)
    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
      updateProjectV2ItemFieldValue(
        input: {projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: $value}
      ) {
        projectV2Item {
          id
          type
          isArchived
        }
      }
    }
    """
    variables = {
        "projectId": get_project_id(),
        "itemId": item_id,
        "fieldId": field["id"],
        "value": value,
    }
    data = graphql_request(mutation, variables)
    result = (data.get("updateProjectV2ItemFieldValue") or {}).get("projectV2Item")
    if result is None:
        raise ProjectCrudError("GitHub API returned unexpected response for update-field")
    return result


def update_text_field(item_id: str, field_name: str, value: str) -> dict[str, Any]:
    return _update_field_value(item_id, field_name, {"text": value})


def update_number_field(item_id: str, field_name: str, value: float) -> dict[str, Any]:
    return _update_field_value(item_id, field_name, {"number": value})


def update_single_select_field(item_id: str, field_name: str, option_name: str) -> dict[str, Any]:
    field = _get_field(field_name)
    options = field.get("options")
    if not options:
        raise ProjectCrudError(f"Field is not a single-select field or has no options: {field_name}")

    option_id = options.get(option_name)
    if not option_id:
        available = ", ".join(sorted(options)) or "(none)"
        raise ProjectCrudError(
            f"Option not found for field '{field_name}': {option_name}. "
            f"Available options: {available}"
        )
    return _update_field_value(item_id, field_name, {"singleSelectOptionId": option_id})


def get_repository_id() -> str:
    if "repository_id" in _cache:
        return _cache["repository_id"]

    owner, name = env("GITHUB_REPOSITORY").split("/", 1)
    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        id
        nameWithOwner
      }
    }
    """
    data = graphql_request(query, {"owner": owner, "name": name})
    repository = data.get("repository")
    if not repository:
        raise ProjectCrudError(f"Could not resolve repository: {env('GITHUB_REPOSITORY')}")

    _cache["repository"] = repository
    _cache["repository_id"] = repository["id"]
    return _cache["repository_id"]


def _parse_github_url(url: str, expected_kind: str) -> tuple[str, str, int]:
    match = GITHUB_CONTENT_URL_RE.match(url)
    if not match:
        raise ProjectCrudError(
            "URL must look like "
            f"https://github.com/owner/repo/{expected_kind}/123"
        )

    owner, repo, kind, number = match.groups()
    if kind != expected_kind:
        raise ProjectCrudError(f"Expected a GitHub {expected_kind} URL, got: {url}")
    return owner, repo, int(number)


def get_issue_or_pr_node_id(url: str) -> str:
    """Resolve an Issue or Pull Request node ID from a github.com URL."""

    match = GITHUB_CONTENT_URL_RE.match(url)
    if not match:
        raise ProjectCrudError(
            "URL must look like https://github.com/owner/repo/issues/123 "
            "or https://github.com/owner/repo/pull/123"
        )

    owner, repo, kind, number = match.groups()
    cache_key = f"content:{owner}/{repo}:{kind}:{number}"
    if cache_key in _cache:
        return _cache[cache_key]

    field = "issue" if kind == "issues" else "pullRequest"
    query = f"""
    query($owner: String!, $repo: String!, $number: Int!) {{
      repository(owner: $owner, name: $repo) {{
        {field}(number: $number) {{
          id
          title
          url
        }}
      }}
    }}
    """
    data = graphql_request(
        query,
        {"owner": owner, "repo": repo, "number": int(number)},
    )
    repository = data.get("repository") or {}
    content = repository.get(field)
    if not content:
        label = "issue" if kind == "issues" else "pull request"
        raise ProjectCrudError(f"Could not resolve {label}: {url}")

    _cache[cache_key] = content["id"]
    return _cache[cache_key]


def add_content_item(content_node_id: str) -> dict[str, Any]:
    mutation = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
        item {
          id
          type
          isArchived
          content {
            __typename
            ... on Issue {
              id
              title
              url
            }
            ... on PullRequest {
              id
              title
              url
            }
          }
        }
      }
    }
    """
    data = graphql_request(mutation, {"projectId": get_project_id(), "contentId": content_node_id})
    result = (data.get("addProjectV2ItemById") or {}).get("item")
    if result is None:
        raise ProjectCrudError("GitHub API returned unexpected response for add-item")
    return result


def cmd_create_item(args: argparse.Namespace) -> dict[str, Any]:
    return create_draft_item(args.title, args.body)


def cmd_list_items(_: argparse.Namespace) -> list[dict[str, Any]]:
    return get_project_items()


def cmd_list_fields(_: argparse.Namespace) -> dict[str, dict[str, Any]]:
    return get_project_fields()


def cmd_update_field(args: argparse.Namespace) -> dict[str, Any]:
    if args.type == "text":
        return update_text_field(args.item_id, args.field, args.value)
    elif args.type == "number":
        try:
            value = float(args.value)
        except ValueError as exc:
            raise ProjectCrudError("--value must be numeric when --type number is used") from exc
        return update_number_field(args.item_id, args.field, value)
    elif args.type == "single-select":
        return update_single_select_field(args.item_id, args.field, args.value)
    else:
        raise ProjectCrudError(f"Unsupported field type: {args.type}")


def cmd_archive_item(args: argparse.Namespace) -> dict[str, Any]:
    return archive_item(args.item_id)


def cmd_link_issue(args: argparse.Namespace) -> dict[str, Any]:
    _parse_github_url(args.issue_url, "issues")
    return add_content_item(get_issue_or_pr_node_id(args.issue_url))


def cmd_link_pr(args: argparse.Namespace) -> dict[str, Any]:
    _parse_github_url(args.pr_url, "pull")
    return add_content_item(get_issue_or_pr_node_id(args.pr_url))


def build_parser() -> argparse.ArgumentParser:
    version_parent = argparse.ArgumentParser(add_help=False)
    version_parent.add_argument(
        "--project-version",
        default=argparse.SUPPRESS,
        help=f"GitHub Project API version to target (default: {DEFAULT_PROJECT_VERSION})",
    )

    parser = argparse.ArgumentParser(
        description="CRUD items in a GitHub Projects v2 board with the GraphQL API.",
        parents=[version_parent],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create-item",
        help="Create a draft Project item",
        parents=[version_parent],
    )
    create.add_argument("--title", required=True, help="Draft item title")
    create.add_argument("--body", default=None, help="Optional draft item body")
    create.set_defaults(func=cmd_create_item, requires_env=True)

    list_items = subparsers.add_parser(
        "list-items",
        help="List Project items",
        parents=[version_parent],
    )
    list_items.set_defaults(func=cmd_list_items, requires_env=True)

    list_fields = subparsers.add_parser(
        "list-fields",
        help="List Project fields and options",
        parents=[version_parent],
    )
    list_fields.set_defaults(func=cmd_list_fields, requires_env=True)

    update = subparsers.add_parser(
        "update-field",
        help="Update a Project item field",
        parents=[version_parent],
    )
    update.add_argument("--item-id", required=True, help="Project item node ID")
    update.add_argument("--field", required=True, help="Project field name")
    update.add_argument("--value", required=True, help="New field value or option name")
    update.add_argument(
        "--type",
        choices=("text", "number", "single-select"),
        default="single-select",
        help="Field value type to update (default: single-select)",
    )
    update.set_defaults(func=cmd_update_field, requires_env=True)

    archive = subparsers.add_parser(
        "archive-item",
        help="Archive/delete a Project item",
        parents=[version_parent],
    )
    archive.add_argument("--item-id", required=True, help="Project item node ID")
    archive.set_defaults(func=cmd_archive_item, requires_env=True)

    link_issue = subparsers.add_parser(
        "link-issue",
        help="Add an existing Issue to the Project",
        parents=[version_parent],
    )
    link_issue.add_argument("--issue-url", required=True, help="GitHub Issue URL")
    link_issue.set_defaults(func=cmd_link_issue, requires_env=True)

    link_pr = subparsers.add_parser(
        "link-pr",
        help="Add an existing Pull Request to the Project",
        parents=[version_parent],
    )
    link_pr.add_argument("--pr-url", required=True, help="GitHub Pull Request URL")
    link_pr.set_defaults(func=cmd_link_pr, requires_env=True)

    return parser


def get_project_version(args: argparse.Namespace) -> str:
    return getattr(args, "project_version", DEFAULT_PROJECT_VERSION)


def run_command(args: argparse.Namespace) -> Any:
    command: Callable[[argparse.Namespace], Any] = args.func
    validate_project_version(get_project_version(args))
    if getattr(args, "requires_env", False):
        validate_env()
    return command(args)


def command_log_fields(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "command": args.command,
        "project_version": get_project_version(args),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        log_event("info", "command_started", **command_log_fields(args))
        result = run_command(args)
        print_json(result)
        log_event("info", "command_succeeded", **command_log_fields(args), exit_status=0)
        return 0
    except ProjectCrudError as exc:
        print_json({"error": str(exc)})
        log_event(
            "error",
            "command_failed",
            **command_log_fields(args),
            error_type=type(exc).__name__,
            exit_status=1,
        )
        return 1
    except KeyboardInterrupt:
        print_json({"error": "Interrupted"})
        log_event("warning", "command_interrupted", **command_log_fields(args), exit_status=130)
        return 130


if __name__ == "__main__":
    sys.exit(main())

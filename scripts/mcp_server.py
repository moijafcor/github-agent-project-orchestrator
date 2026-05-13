#!/usr/bin/env python3
"""
MCP server wrapping github_project_crud.py.
Run: python scripts/mcp_server.py
Listens on localhost:8765 — Claude Desktop connects here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow direct execution: python scripts/mcp_server.py
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv  # noqa: E402

# Load .env from project root; fall back to the script's own directory.
_root_env = Path(__file__).parent.parent / ".env"
_local_env = Path(__file__).parent / ".env"
load_dotenv(_root_env if _root_env.exists() else _local_env)

import github_project_crud as crud  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "GitHub Projects",
    instructions=(
        "CRUD operations on a GitHub Projects v2 board. "
        "Always call list_project_items first to see what exists "
        "before creating or updating items."
    ),
)


@mcp.tool()
def list_project_items() -> str:
    """List all items in the configured GitHub Project board."""
    try:
        items = crud.get_project_items()
        return json.dumps(items, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def list_project_fields() -> str:
    """List all fields available on the GitHub Project board."""
    try:
        fields = crud.get_project_fields()
        return json.dumps(fields, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def create_project_item(title: str, body: str = "") -> str:
    """
    Create a new draft item on the GitHub Project board.

    Args:
        title: The item title.
        body:  Optional markdown body / description.
    """
    try:
        result = crud.create_draft_item(title, body or None)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def update_project_item_field(
    item_id: str,
    field: str,
    value: str,
    field_type: str = "single-select",
) -> str:
    """
    Update a field on an existing project item.

    Args:
        item_id:    The project item node ID (from list_project_items).
        field:      The field name (e.g. 'Status', 'Priority').
        value:      The new value or option name.
        field_type: One of 'text', 'number', 'single-select' (default).
    """
    try:
        if field_type == "text":
            result = crud.update_text_field(item_id, field, value)
        elif field_type == "number":
            result = crud.update_number_field(item_id, field, float(value))
        elif field_type == "single-select":
            result = crud.update_single_select_field(item_id, field, value)
        else:
            return f"Error: unsupported field_type '{field_type}'"
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def archive_project_item(item_id: str) -> str:
    """
    Archive (soft-delete) an item from the project board.

    Args:
        item_id: The project item node ID (from list_project_items).
    """
    try:
        result = crud.archive_item(item_id)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def link_issue_to_project(issue_url: str) -> str:
    """
    Add an existing GitHub Issue to the project board.

    Args:
        issue_url: Full GitHub issue URL, e.g.
                   https://github.com/owner/repo/issues/42
    """
    try:
        node_id = crud.get_issue_or_pr_node_id(issue_url)
        result = crud.add_content_item(node_id)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def link_pr_to_project(pr_url: str) -> str:
    """
    Add an existing Pull Request to the project board.

    Args:
        pr_url: Full GitHub PR URL, e.g.
                https://github.com/owner/repo/pull/7
    """
    try:
        node_id = crud.get_issue_or_pr_node_id(pr_url)
        result = crud.add_content_item(node_id)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=8765)

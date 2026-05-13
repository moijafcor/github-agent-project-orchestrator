#!/usr/bin/env python3
"""
MCP server wrapping github_project_crud.py.
Run: python scripts/mcp_server.py
Listens on localhost:8765 — Claude Desktop connects here.
"""

from __future__ import annotations

import json
import os
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
    host="127.0.0.1",
    port=8765,
    instructions=(
        "CRUD operations on a GitHub Projects v2 board. "
        "Always call list_project_items first to see what exists "
        "before creating or updating items. "
        "Every tool requires owner, owner_type, and project_number — "
        "pass them on every call."
    ),
)

_CONTEXT_KEYS = ("GITHUB_OWNER", "GITHUB_OWNER_TYPE", "GITHUB_PROJECT_NUMBER")


def _apply_context(owner: str, owner_type: str, project_number: int) -> None:
    """Set per-call project context and invalidate the module-level cache."""
    os.environ["GITHUB_OWNER"] = owner
    os.environ["GITHUB_OWNER_TYPE"] = owner_type
    os.environ["GITHUB_PROJECT_NUMBER"] = str(project_number)
    crud._cache.clear()


@mcp.tool()
def list_project_items(owner: str, owner_type: str, project_number: int) -> str:
    """
    List all items in a GitHub Project board.

    Args:
        owner:          GitHub org or user login (e.g. "AdsWireIO").
        owner_type:     "org" or "user".
        project_number: The project board number.
    """
    _apply_context(owner, owner_type, project_number)
    try:
        items = crud.get_project_items()
        return json.dumps(items, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def list_project_fields(owner: str, owner_type: str, project_number: int) -> str:
    """
    List all fields available on a GitHub Project board.

    Args:
        owner:          GitHub org or user login (e.g. "AdsWireIO").
        owner_type:     "org" or "user".
        project_number: The project board number.
    """
    _apply_context(owner, owner_type, project_number)
    try:
        fields = crud.get_project_fields()
        return json.dumps(fields, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def create_project_item(
    owner: str,
    owner_type: str,
    project_number: int,
    title: str,
    body: str = "",
) -> str:
    """
    Create a new draft item on a GitHub Project board.

    Args:
        owner:          GitHub org or user login (e.g. "AdsWireIO").
        owner_type:     "org" or "user".
        project_number: The project board number.
        title:          The item title.
        body:           Optional markdown body / description.
    """
    _apply_context(owner, owner_type, project_number)
    try:
        result = crud.create_draft_item(title, body or None)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def update_project_item_field(
    owner: str,
    owner_type: str,
    project_number: int,
    item_id: str,
    field: str,
    value: str,
    field_type: str = "single-select",
) -> str:
    """
    Update a field on an existing project item.

    Args:
        owner:          GitHub org or user login (e.g. "AdsWireIO").
        owner_type:     "org" or "user".
        project_number: The project board number.
        item_id:        The project item node ID (from list_project_items).
        field:          The field name (e.g. 'Status', 'Priority').
        value:          The new value or option name.
        field_type:     One of 'text', 'number', 'single-select' (default).
    """
    _apply_context(owner, owner_type, project_number)
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
def archive_project_item(owner: str, owner_type: str, project_number: int, item_id: str) -> str:
    """
    Archive (soft-delete) an item from the project board.

    Args:
        owner:          GitHub org or user login (e.g. "AdsWireIO").
        owner_type:     "org" or "user".
        project_number: The project board number.
        item_id:        The project item node ID (from list_project_items).
    """
    _apply_context(owner, owner_type, project_number)
    try:
        result = crud.archive_item(item_id)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def link_issue_to_project(owner: str, owner_type: str, project_number: int, issue_url: str) -> str:
    """
    Add an existing GitHub Issue to a project board.

    Args:
        owner:          GitHub org or user login (e.g. "AdsWireIO").
        owner_type:     "org" or "user".
        project_number: The project board number.
        issue_url:      Full GitHub issue URL, e.g.
                        https://github.com/owner/repo/issues/42
    """
    _apply_context(owner, owner_type, project_number)
    try:
        node_id = crud.get_issue_or_pr_node_id(issue_url)
        result = crud.add_content_item(node_id)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


@mcp.tool()
def link_pr_to_project(owner: str, owner_type: str, project_number: int, pr_url: str) -> str:
    """
    Add an existing Pull Request to a project board.

    Args:
        owner:          GitHub org or user login (e.g. "AdsWireIO").
        owner_type:     "org" or "user".
        project_number: The project board number.
        pr_url:         Full GitHub PR URL, e.g.
                        https://github.com/owner/repo/pull/7
    """
    _apply_context(owner, owner_type, project_number)
    try:
        node_id = crud.get_issue_or_pr_node_id(pr_url)
        result = crud.add_content_item(node_id)
        return json.dumps(result, indent=2)
    except crud.ProjectCrudError as e:
        return f"Error: {e}"


if __name__ == "__main__":
    import argparse as _argparse

    _p = _argparse.ArgumentParser(description="GitHub Projects MCP server")
    _p.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="Transport to use (default: stdio — Claude Desktop spawns this process)",
    )
    _args = _p.parse_args()

    mcp.run(transport=_args.transport)

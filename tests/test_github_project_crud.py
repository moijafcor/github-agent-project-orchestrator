from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from scripts import github_project_crud as crud


VALID_ENV = {
    "GITHUB_TOKEN": "token",
    "GITHUB_OWNER": "owner",
    "GITHUB_OWNER_TYPE": "org",
    "GITHUB_PROJECT_NUMBER": "1",
    "GITHUB_REPOSITORY": "owner/repo",
}


class EnvironmentTests(unittest.TestCase):
    def test_validate_env_reports_all_missing_values(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                crud.ProjectCrudError,
                "GITHUB_TOKEN, GITHUB_OWNER, GITHUB_OWNER_TYPE",
            ):
                crud.validate_env()

    def test_validate_env_rejects_bad_owner_type(self) -> None:
        env = {**VALID_ENV, "GITHUB_OWNER_TYPE": "team"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(crud.ProjectCrudError, "org' or 'user"):
                crud.validate_env()

    def test_validate_env_rejects_bad_repository_format(self) -> None:
        env = {**VALID_ENV, "GITHUB_REPOSITORY": "owner/repo/extra"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(crud.ProjectCrudError, "owner/repo"):
                crud.validate_env()


class UrlParsingTests(unittest.TestCase):
    def test_parse_issue_url(self) -> None:
        self.assertEqual(
            crud._parse_github_url("https://github.com/acme/widgets/issues/123", "issues"),
            ("acme", "widgets", 123),
        )

    def test_parse_pr_url_with_suffix(self) -> None:
        self.assertEqual(
            crud._parse_github_url("https://github.com/acme/widgets/pull/456#discussion", "pull"),
            ("acme", "widgets", 456),
        )

    def test_parse_rejects_wrong_kind(self) -> None:
        with self.assertRaisesRegex(crud.ProjectCrudError, "Expected a GitHub pull URL"):
            crud._parse_github_url("https://github.com/acme/widgets/issues/123", "pull")


class FieldUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._cache.clear()

    def tearDown(self) -> None:
        crud._cache.clear()

    def test_single_select_update_resolves_option_name(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        crud._cache["fields"] = {
            "Status": {
                "id": "field_status",
                "name": "Status",
                "options": {"Done": "option_done"},
            }
        }

        with mock.patch.object(
            crud,
            "graphql_request",
            return_value={
                "updateProjectV2ItemFieldValue": {
                    "projectV2Item": {"id": "item_1", "type": "DRAFT_ISSUE", "isArchived": False}
                }
            },
        ) as request:
            result = crud.update_single_select_field("item_1", "Status", "Done")

        self.assertEqual(result["id"], "item_1")
        variables = request.call_args.args[1]
        self.assertEqual(variables["fieldId"], "field_status")
        self.assertEqual(variables["value"], {"singleSelectOptionId": "option_done"})

    def test_number_update_rejects_non_numeric_cli_value(self) -> None:
        args = argparse.Namespace(type="number", item_id="item_1", field="Estimate", value="many")
        with self.assertRaisesRegex(crud.ProjectCrudError, "must be numeric"):
            crud.cmd_update_field(args)


class ItemNormalizationTests(unittest.TestCase):
    def test_normalize_item_maps_known_field_value_types(self) -> None:
        item = {
            "id": "item_1",
            "type": "ISSUE",
            "isArchived": False,
            "content": {"title": "Example"},
            "fieldValues": {
                "nodes": [
                    {
                        "__typename": "ProjectV2ItemFieldTextValue",
                        "text": "hello",
                        "field": {"name": "Summary"},
                    },
                    {
                        "__typename": "ProjectV2ItemFieldNumberValue",
                        "number": 5.0,
                        "field": {"name": "Estimate"},
                    },
                    {
                        "__typename": "ProjectV2ItemFieldSingleSelectValue",
                        "name": "Todo",
                        "optionId": "option_todo",
                        "field": {"name": "Status"},
                    },
                ]
            },
        }

        normalized = crud._normalize_item(item)

        self.assertEqual(normalized["fields"]["Summary"], "hello")
        self.assertEqual(normalized["fields"]["Estimate"], 5.0)
        self.assertEqual(
            normalized["fields"]["Status"],
            {"name": "Todo", "option_id": "option_todo"},
        )


class CliTests(unittest.TestCase):
    def test_main_prints_json_error_and_nonzero_status(self) -> None:
        output = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stdout(output):
                status = crud.main(["list-items"])

        self.assertEqual(status, 1)
        parsed = json.loads(output.getvalue())
        self.assertIn("Missing required environment variable", parsed["error"])

    def test_main_prints_json_result(self) -> None:
        output = io.StringIO()
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            with mock.patch.object(crud, "get_project_items", return_value=[]):
                with contextlib.redirect_stdout(output):
                    status = crud.main(["list-items"])

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), [])

    def test_project_version_defaults_to_v2(self) -> None:
        parser = crud.build_parser()
        args = parser.parse_args(["list-items"])
        self.assertEqual(crud.get_project_version(args), "v2")

    def test_project_version_can_be_passed_before_subcommand(self) -> None:
        parser = crud.build_parser()
        args = parser.parse_args(["--project-version", "v2", "list-items"])
        self.assertEqual(args.project_version, "v2")

    def test_project_version_can_be_passed_after_subcommand(self) -> None:
        parser = crud.build_parser()
        args = parser.parse_args(["list-items", "--project-version", "v2"])
        self.assertEqual(args.project_version, "v2")

    def test_unsupported_project_version_returns_json_error(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = crud.main(["--project-version", "v1", "list-items"])

        self.assertEqual(status, 1)
        parsed = json.loads(output.getvalue())
        self.assertIn("Unsupported GitHub Project version: v1", parsed["error"])


class SyslogTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._syslog_opened = False

    def tearDown(self) -> None:
        crud._syslog_opened = False

    def test_log_event_writes_json_to_syslog(self) -> None:
        fake_syslog = mock.Mock()
        fake_syslog.LOG_DEBUG = 7
        fake_syslog.LOG_INFO = 6
        fake_syslog.LOG_WARNING = 4
        fake_syslog.LOG_ERR = 3
        fake_syslog.LOG_PID = 1
        fake_syslog.LOG_USER = 8

        with mock.patch.object(crud, "syslog", fake_syslog):
            crud.log_event("info", "example_event", command="list-items")

        fake_syslog.openlog.assert_called_once_with("github-project-toolkit", 1, 8)
        priority, message = fake_syslog.syslog.call_args.args
        self.assertEqual(priority, 6)
        self.assertEqual(
            json.loads(message),
            {"event": "example_event", "command": "list-items"},
        )

    def test_log_event_does_not_raise_when_syslog_fails(self) -> None:
        fake_syslog = mock.Mock()
        fake_syslog.LOG_DEBUG = 7
        fake_syslog.LOG_INFO = 6
        fake_syslog.LOG_WARNING = 4
        fake_syslog.LOG_ERR = 3
        fake_syslog.LOG_PID = 1
        fake_syslog.LOG_USER = 8
        fake_syslog.syslog.side_effect = OSError("syslog unavailable")

        with mock.patch.object(crud, "syslog", fake_syslog):
            crud.log_event("error", "failure")

    def test_main_logs_command_lifecycle(self) -> None:
        output = io.StringIO()
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            with mock.patch.object(crud, "get_project_items", return_value=[]):
                with mock.patch.object(crud, "log_event") as log_event:
                    with contextlib.redirect_stdout(output):
                        status = crud.main(["list-items"])

        self.assertEqual(status, 0)
        self.assertEqual(log_event.call_args_list[0].args[:2], ("info", "command_started"))
        self.assertEqual(log_event.call_args_list[1].args[:2], ("info", "command_succeeded"))

    def test_main_logs_command_failure_without_secret_values(self) -> None:
        output = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(crud, "log_event") as log_event:
                with contextlib.redirect_stdout(output):
                    status = crud.main(["list-items"])

        self.assertEqual(status, 1)
        _, failure_event = log_event.call_args_list
        self.assertEqual(failure_event.args[:2], ("error", "command_failed"))
        self.assertEqual(failure_event.kwargs["command"], "list-items")
        self.assertEqual(failure_event.kwargs["error_type"], "ProjectCrudError")
        self.assertNotIn("error", failure_event.kwargs)


class GraphqlRequestErrorTests(unittest.TestCase):
    def test_http_error_message_excludes_response_body(self) -> None:
        http_error = urllib.error.HTTPError(
            url="https://api.github.com/graphql",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"SECRET_RESPONSE_CONTENT"}'),
        )
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            with mock.patch("urllib.request.urlopen", side_effect=http_error):
                with self.assertRaises(crud.ProjectCrudError) as ctx:
                    crud.graphql_request("{ viewer { login } }")
        self.assertNotIn("SECRET_RESPONSE_CONTENT", str(ctx.exception))
        self.assertIn("401", str(ctx.exception))

    def test_invalid_json_error_message_excludes_body(self) -> None:
        response = mock.Mock()
        response.read.return_value = b"SECRET_GARBAGE_BODY"
        response.__enter__ = lambda s: s
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            with mock.patch("urllib.request.urlopen", return_value=response):
                with self.assertRaises(crud.ProjectCrudError) as ctx:
                    crud.graphql_request("{ viewer { login } }")
        self.assertNotIn("SECRET_GARBAGE_BODY", str(ctx.exception))
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_missing_data_error_message_excludes_body(self) -> None:
        response = mock.Mock()
        response.read.return_value = json.dumps({"SECRET_KEY": "SECRET_VALUE"}).encode()
        response.__enter__ = lambda s: s
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            with mock.patch("urllib.request.urlopen", return_value=response):
                with self.assertRaises(crud.ProjectCrudError) as ctx:
                    crud.graphql_request("{ viewer { login } }")
        self.assertNotIn("SECRET_VALUE", str(ctx.exception))
        self.assertIn("did not include data", str(ctx.exception))


class ProjectIdTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._cache.clear()

    def tearDown(self) -> None:
        crud._cache.clear()

    def test_get_project_id_returns_cached_value(self) -> None:
        crud._cache["project_id"] = "PVT_cached"
        result = crud.get_project_id()
        self.assertEqual(result, "PVT_cached")

    def test_get_project_id_resolves_from_api_for_org(self) -> None:
        api_response = {
            "organization": {
                "projectV2": {"id": "PVT_abc", "number": 1, "title": "My Project"}
            }
        }
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            with mock.patch.object(crud, "graphql_request", return_value=api_response):
                result = crud.get_project_id()
        self.assertEqual(result, "PVT_abc")
        self.assertEqual(crud._cache["project_id"], "PVT_abc")

    def test_get_project_id_raises_when_project_not_found(self) -> None:
        api_response = {"organization": {"projectV2": None}}
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            with mock.patch.object(crud, "graphql_request", return_value=api_response):
                with self.assertRaisesRegex(crud.ProjectCrudError, "Could not resolve"):
                    crud.get_project_id()


class ProjectFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._cache.clear()

    def tearDown(self) -> None:
        crud._cache.clear()

    def _make_api_response(self, nodes: list, has_next: bool = False) -> dict:
        return {
            "node": {
                "fields": {
                    "pageInfo": {"hasNextPage": has_next, "endCursor": "cursor1" if has_next else None},
                    "nodes": nodes,
                }
            }
        }

    def test_get_project_fields_returns_fields_keyed_by_name(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        nodes = [
            {"__typename": "ProjectV2Field", "id": "f1", "name": "Title", "dataType": "TEXT"},
            {
                "__typename": "ProjectV2SingleSelectField",
                "id": "f2",
                "name": "Status",
                "dataType": "SINGLE_SELECT",
                "options": [{"id": "opt1", "name": "Todo"}, {"id": "opt2", "name": "Done"}],
            },
        ]
        with mock.patch.object(crud, "graphql_request", return_value=self._make_api_response(nodes)):
            fields = crud.get_project_fields()
        self.assertIn("Title", fields)
        self.assertIn("Status", fields)
        self.assertEqual(fields["Status"]["options"], {"Todo": "opt1", "Done": "opt2"})

    def test_get_project_fields_caches_result_after_first_call(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        with mock.patch.object(
            crud, "graphql_request", return_value=self._make_api_response([])
        ) as mock_request:
            crud.get_project_fields()
            crud.get_project_fields()
        mock_request.assert_called_once()

    def test_get_project_fields_raises_when_fields_missing(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        with mock.patch.object(crud, "graphql_request", return_value={"node": {}}):
            with self.assertRaisesRegex(crud.ProjectCrudError, "Could not read project fields"):
                crud.get_project_fields()


class FieldFromNodeTests(unittest.TestCase):
    def test_field_from_node_with_valid_options(self) -> None:
        node = {
            "__typename": "ProjectV2SingleSelectField",
            "id": "f1",
            "name": "Status",
            "dataType": "SINGLE_SELECT",
            "options": [{"id": "opt1", "name": "Todo"}, {"id": "opt2", "name": "Done"}],
        }
        field = crud._field_from_node(node)
        self.assertEqual(field["options"], {"Todo": "opt1", "Done": "opt2"})

    def test_field_from_node_skips_malformed_option_entries(self) -> None:
        node = {
            "__typename": "ProjectV2SingleSelectField",
            "id": "f1",
            "name": "Status",
            "dataType": "SINGLE_SELECT",
            "options": [
                {"id": "opt1", "name": "Todo"},
                {"id": "opt2"},
                "not_a_dict",
            ],
        }
        field = crud._field_from_node(node)
        self.assertEqual(field["options"], {"Todo": "opt1"})

    def test_field_from_node_without_options(self) -> None:
        node = {"__typename": "ProjectV2Field", "id": "f1", "name": "Title", "dataType": "TEXT"}
        field = crud._field_from_node(node)
        self.assertNotIn("options", field)


class CreateDraftItemTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._cache.clear()

    def tearDown(self) -> None:
        crud._cache.clear()

    def test_create_draft_item_returns_project_item(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        item = {"id": "PVTI_1", "type": "DRAFT_ISSUE", "isArchived": False, "content": {"id": "DI_1", "title": "My draft", "body": ""}}
        with mock.patch.object(
            crud, "graphql_request", return_value={"addProjectV2DraftIssue": {"projectItem": item}}
        ):
            result = crud.create_draft_item("My draft")
        self.assertEqual(result["id"], "PVTI_1")

    def test_create_draft_item_raises_on_malformed_response(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        with mock.patch.object(crud, "graphql_request", return_value={}):
            with self.assertRaisesRegex(crud.ProjectCrudError, "unexpected response"):
                crud.create_draft_item("My draft")


class ArchiveItemTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._cache.clear()

    def tearDown(self) -> None:
        crud._cache.clear()

    def test_archive_item_returns_archived_item(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        item = {"id": "PVTI_1", "isArchived": True}
        with mock.patch.object(
            crud, "graphql_request", return_value={"archiveProjectV2Item": {"item": item}}
        ):
            result = crud.archive_item("PVTI_1")
        self.assertEqual(result["id"], "PVTI_1")
        self.assertTrue(result["isArchived"])

    def test_archive_item_raises_on_malformed_response(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        with mock.patch.object(crud, "graphql_request", return_value={}):
            with self.assertRaisesRegex(crud.ProjectCrudError, "unexpected response"):
                crud.archive_item("PVTI_1")


class UpdateFieldValueTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._cache.clear()

    def tearDown(self) -> None:
        crud._cache.clear()

    def test_update_field_value_raises_on_malformed_response(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        crud._cache["fields"] = {"Notes": {"id": "field_notes", "name": "Notes"}}
        with mock.patch.object(crud, "graphql_request", return_value={}):
            with self.assertRaisesRegex(crud.ProjectCrudError, "unexpected response"):
                crud.update_text_field("item_1", "Notes", "hello")


class AddContentItemTests(unittest.TestCase):
    def setUp(self) -> None:
        crud._cache.clear()

    def tearDown(self) -> None:
        crud._cache.clear()

    def test_add_content_item_returns_item(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        item = {"id": "PVTI_2", "type": "ISSUE", "isArchived": False, "content": {"id": "I_1", "title": "Issue 1", "url": "https://github.com/owner/repo/issues/1"}}
        with mock.patch.object(
            crud, "graphql_request", return_value={"addProjectV2ItemById": {"item": item}}
        ):
            result = crud.add_content_item("I_1")
        self.assertEqual(result["id"], "PVTI_2")

    def test_add_content_item_raises_on_malformed_response(self) -> None:
        crud._cache["project_id"] = "PVT_project"
        with mock.patch.object(crud, "graphql_request", return_value={}):
            with self.assertRaisesRegex(crud.ProjectCrudError, "unexpected response"):
                crud.add_content_item("I_1")


class ItemTruncationWarningTests(unittest.TestCase):
    def _make_item(self, typename: str, field_name: str, count: int) -> dict:
        if typename == "ProjectV2ItemFieldUserValue":
            payload = {"users": {"nodes": [{"login": f"u{i}"} for i in range(count)]}}
        else:
            payload = {"labels": {"nodes": [{"name": f"label{i}"} for i in range(count)]}}
        return {
            "id": "item_1",
            "type": "ISSUE",
            "isArchived": False,
            "content": None,
            "fieldValues": {
                "nodes": [{"__typename": typename, "field": {"name": field_name}, **payload}]
            },
        }

    def test_normalize_item_warns_when_users_at_limit(self) -> None:
        item = self._make_item("ProjectV2ItemFieldUserValue", "Assignees", 20)
        with mock.patch.object(crud, "log_event") as mock_log:
            crud._normalize_item(item)
        events = [c.args[1] for c in mock_log.call_args_list]
        self.assertIn("user_field_may_be_truncated", events)

    def test_normalize_item_no_warning_when_users_below_limit(self) -> None:
        item = self._make_item("ProjectV2ItemFieldUserValue", "Assignees", 5)
        with mock.patch.object(crud, "log_event") as mock_log:
            crud._normalize_item(item)
        events = [c.args[1] for c in mock_log.call_args_list]
        self.assertNotIn("user_field_may_be_truncated", events)

    def test_normalize_item_warns_when_labels_at_limit(self) -> None:
        item = self._make_item("ProjectV2ItemFieldLabelValue", "Labels", 20)
        with mock.patch.object(crud, "log_event") as mock_log:
            crud._normalize_item(item)
        events = [c.args[1] for c in mock_log.call_args_list]
        self.assertIn("label_field_may_be_truncated", events)


if __name__ == "__main__":
    unittest.main()

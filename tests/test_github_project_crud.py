from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import unittest
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


if __name__ == "__main__":
    unittest.main()

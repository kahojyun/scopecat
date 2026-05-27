from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from implementation_candidates.uv_sync_intent import build_uv_sync_intent_summary
from implementation_candidates.uv_sync_intent.contracts import (
    EXPECTED_POLICY,
    POLICY_ATTENTION_MATRIX,
    validate_uv_sync_intent_contract,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_intent" / "basic_uv_sync_intent"


def _load_input() -> dict:
    return json.loads((FIXTURE / "uv-sync-intent-input.json").read_text(encoding="utf-8"))


def _set_dependency_groups(source: dict, groups: list[str]) -> None:
    source["sync_request"]["dependency_groups"] = list(groups)
    source["declared_environment"]["modern_python_environment"]["dependency_groups"] = list(groups)


class UvSyncIntentCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_uv_sync_intent_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-uv-sync-intent-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_expected_output_declares_fixture_boundary_metadata(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-uv-sync-intent-summary.json").read_text(encoding="utf-8")
        )

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(expected["source_fixture"], "uv-sync-intent-input.json")
        self.assertEqual(expected["reference_semantics"]["status"], "fixture_only")
        self.assertIn(
            "command-intent projection", expected["reference_semantics"]["contract_guard"]
        )

    def test_intent_constructs_bounded_locked_sync_argv(self) -> None:
        summary = build_uv_sync_intent_summary(_load_input())
        command = summary["command_intent"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(command["working_directory"], "project")
        self.assertEqual(
            command["argv"],
            ["uv", "sync", "--locked", "--no-default-groups", "--group", "analysis"],
        )
        self.assertEqual(command["environment_variables"], [])
        self.assertEqual(command["dependency_group_selection"]["project_dependencies"], "included")
        self.assertEqual(
            command["dependency_group_selection"]["default_dependency_groups"], "excluded"
        )
        self.assertEqual(command["lock_policy"], "uv_locked_mode")
        self.assertEqual(
            attention["process_execution_not_performed"]["does_not_claim"],
            "external_command_completed",
        )
        self.assertEqual(
            attention["dependency_sync_not_executed"]["does_not_claim"],
            "synchronized_environment",
        )

    def test_project_dependencies_without_uv_groups_omits_group_flags(self) -> None:
        source = _load_input()
        _set_dependency_groups(source, [])

        summary = build_uv_sync_intent_summary(source)

        self.assertEqual(
            summary["command_intent"]["argv"], ["uv", "sync", "--locked", "--no-default-groups"]
        )
        self.assertEqual(
            summary["command_intent"]["dependency_group_selection"]["command_dependency_groups"],
            [],
        )

    def test_root_level_pyproject_can_use_workspace_root_working_directory(self) -> None:
        source = _load_input()
        source["sync_request"]["working_directory"] = "."
        source["declared_environment"]["modern_python_environment"]["pyproject_path"] = (
            "pyproject.toml"
        )
        source["declared_environment"]["modern_python_environment"]["lockfile_path"] = "uv.lock"

        summary = build_uv_sync_intent_summary(source)

        self.assertEqual(summary["command_intent"]["working_directory"], ".")

    def test_intent_does_not_read_manifest_lockfile_probe_filesystem_or_execute(self) -> None:
        source = _load_input()
        with (
            mock.patch.object(Path, "open", side_effect=AssertionError("unexpected file read")),
            mock.patch.object(Path, "exists", side_effect=AssertionError("unexpected exists")),
            mock.patch.object(Path, "is_file", side_effect=AssertionError("unexpected is_file")),
            mock.patch.object(Path, "stat", side_effect=AssertionError("unexpected stat")),
            mock.patch.object(os, "stat", side_effect=AssertionError("unexpected os.stat")),
            mock.patch.object(
                subprocess, "run", side_effect=AssertionError("unexpected subprocess.run")
            ),
            mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("unexpected subprocess.Popen")
            ),
            mock.patch.object(os, "system", side_effect=AssertionError("unexpected os.system")),
        ):
            summary = build_uv_sync_intent_summary(source)

        self.assertEqual(summary["intent_status"], "ready_for_external_review")

    def test_policy_attention_matrix_covers_explicit_policy_boundaries(self) -> None:
        expected_policy_keys = {
            "summary_policy",
            "manager_scope",
            "filesystem_inspection",
            "manifest_read",
            "lockfile_read",
            "dependency_resolution",
            "dependency_sync",
            "package_install",
            "process_execution",
            "runtime_probe",
            "code_import_execution",
            "hardware_probe",
            "readiness_claim",
            "shared_environment_schema",
        }
        matrix_policy_keys = {row["policy_key"] for row in POLICY_ATTENTION_MATRIX}
        matrix_codes = [row["code"] for row in POLICY_ATTENTION_MATRIX]

        self.assertEqual(matrix_policy_keys, expected_policy_keys)
        self.assertEqual(len(matrix_codes), len(set(matrix_codes)))
        for row in POLICY_ATTENTION_MATRIX:
            with self.subTest(policy_key=row["policy_key"]):
                self.assertEqual(EXPECTED_POLICY[row["policy_key"]], row["policy_value"])
                self.assertIn(row["severity"], {"info", "review"})
                self.assertTrue(row["basis"])
                self.assertTrue(row["does_not_claim"])

    def test_policy_overrides_are_rejected_for_all_policy_keys(self) -> None:
        for key, expected in EXPECTED_POLICY.items():
            with self.subTest(key=key):
                source = _load_input()
                source["uv_sync_intent_policy"][key] = f"not-{expected}"

                with self.assertRaisesRegex(ValueError, key):
                    build_uv_sync_intent_summary(source)

    def test_extra_or_missing_source_shape_is_rejected(self) -> None:
        source = _load_input()
        source["command_result"] = {}

        with self.assertRaisesRegex(ValueError, "source"):
            build_uv_sync_intent_summary(source)

        source = _load_input()
        del source["sync_request"]

        with self.assertRaisesRegex(ValueError, "source"):
            build_uv_sync_intent_summary(source)

    def test_request_rejects_arbitrary_flags_or_policy_modes(self) -> None:
        source = _load_input()
        source["sync_request"]["extra_flags"] = ["--all-extras"]

        with self.assertRaisesRegex(ValueError, "uv sync request"):
            build_uv_sync_intent_summary(source)

        source = _load_input()
        source["sync_request"]["command_policy"] = "caller_supplied_argv"

        with self.assertRaisesRegex(ValueError, "command_policy"):
            build_uv_sync_intent_summary(source)

    def test_sync_requires_explicit_approved_operation(self) -> None:
        source = _load_input()
        source["sync_request"]["approved_operation"] = "uv_sync"

        with self.assertRaisesRegex(ValueError, "approved_operation"):
            build_uv_sync_intent_summary(source)

    def test_request_must_match_declared_context(self) -> None:
        source = _load_input()
        source["sync_request"]["declared_environment_id"] = "declared-env-other"

        with self.assertRaisesRegex(ValueError, "declared environment"):
            validate_uv_sync_intent_contract(source)

    def test_declared_environment_scope_must_match_prepared_context(self) -> None:
        source = _load_input()
        source["declared_environment"]["scope"]["prepared_run_context_id"] = (
            "prepared-run-context-chevron-qA-other"
        )

        with self.assertRaisesRegex(ValueError, "scope"):
            build_uv_sync_intent_summary(source)

    def test_declared_environment_with_review_findings_is_rejected(self) -> None:
        source = _load_input()
        source["declared_environment"]["record_status"] = "declared_with_review_findings"

        with self.assertRaisesRegex(ValueError, "record_status"):
            build_uv_sync_intent_summary(source)

    def test_working_directory_must_be_relative_and_match_pyproject_parent(self) -> None:
        for path in ["../project", "/private/project", "C:/lab/project", "project\\env"]:
            with self.subTest(path=path):
                source = _load_input()
                source["sync_request"]["working_directory"] = path

                with self.assertRaisesRegex(ValueError, "working_directory must be relative"):
                    build_uv_sync_intent_summary(source)

        source = _load_input()
        source["sync_request"]["working_directory"] = "other-project"

        with self.assertRaisesRegex(
            ValueError, "working_directory must contain declared pyproject"
        ):
            build_uv_sync_intent_summary(source)

    def test_declared_environment_paths_must_stay_relative(self) -> None:
        cases = [
            ("pyproject_path", "../pyproject.toml"),
            ("pyproject_path", "/private/pyproject.toml"),
            ("lockfile_path", "project\\uv.lock"),
            ("lockfile_path", "C:/lab/uv.lock"),
        ]
        for key, path in cases:
            with self.subTest(key=key, path=path):
                source = _load_input()
                source["declared_environment"]["modern_python_environment"][key] = path

                with self.assertRaisesRegex(ValueError, "relative"):
                    build_uv_sync_intent_summary(source)

    def test_lockfile_path_must_be_uv_lock_next_to_pyproject(self) -> None:
        source = _load_input()
        source["declared_environment"]["modern_python_environment"]["lockfile_path"] = (
            "project/custom.lock"
        )

        with self.assertRaisesRegex(ValueError, "uv.lock"):
            build_uv_sync_intent_summary(source)

        source = _load_input()
        source["declared_environment"]["modern_python_environment"]["lockfile_path"] = (
            "other/uv.lock"
        )

        with self.assertRaisesRegex(ValueError, "share a parent"):
            build_uv_sync_intent_summary(source)

    def test_project_dependencies_must_be_explicitly_included(self) -> None:
        source = _load_input()
        source["sync_request"]["include_project_dependencies"] = False

        with self.assertRaisesRegex(ValueError, "include project dependencies"):
            build_uv_sync_intent_summary(source)

    def test_dependency_groups_are_real_uv_groups_not_project_dependency_sentinel(self) -> None:
        source = _load_input()
        _set_dependency_groups(source, ["default"])

        summary = build_uv_sync_intent_summary(source)

        self.assertEqual(
            summary["command_intent"]["argv"],
            ["uv", "sync", "--locked", "--no-default-groups", "--group", "default"],
        )

    def test_request_groups_match_declared_groups_and_emit_declared_spelling_in_request_order(
        self,
    ) -> None:
        source = _load_input()
        source["sync_request"]["dependency_groups"] = ["plot-tools", "analysis-dev"]
        source["declared_environment"]["modern_python_environment"]["dependency_groups"] = [
            "analysis_dev",
            "plot_tools",
        ]

        summary = build_uv_sync_intent_summary(source)

        self.assertEqual(
            summary["command_intent"]["dependency_group_selection"]["normalized_requested_groups"],
            ["plot-tools", "analysis-dev"],
        )
        self.assertEqual(
            summary["command_intent"]["dependency_group_selection"][
                "normalized_declared_environment_groups"
            ],
            ["analysis-dev", "plot-tools"],
        )
        self.assertEqual(
            summary["command_intent"]["dependency_group_selection"]["group_matches"],
            [
                {
                    "requested_group": "plot-tools",
                    "normalized_group": "plot-tools",
                    "declared_environment_group": "plot_tools",
                },
                {
                    "requested_group": "analysis-dev",
                    "normalized_group": "analysis-dev",
                    "declared_environment_group": "analysis_dev",
                },
            ],
        )
        self.assertEqual(
            summary["command_intent"]["argv"],
            [
                "uv",
                "sync",
                "--locked",
                "--no-default-groups",
                "--group",
                "plot_tools",
                "--group",
                "analysis_dev",
            ],
        )

    def test_duplicate_normalized_dependency_groups_are_rejected(self) -> None:
        source = _load_input()
        _set_dependency_groups(source, ["analysis-dev", "analysis_dev"])

        with self.assertRaisesRegex(ValueError, "duplicate normalized dependency group"):
            build_uv_sync_intent_summary(source)

    def test_workspace_root_label_must_not_be_path_like(self) -> None:
        source = _load_input()
        source["sync_request"]["workspace_root_label"] = "/tmp/workspace"

        with self.assertRaisesRegex(ValueError, "workspace_root_label"):
            build_uv_sync_intent_summary(source)

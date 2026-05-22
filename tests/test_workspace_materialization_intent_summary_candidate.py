from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.workspace_materialization_intent import (
    build_workspace_materialization_intent_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "workspace_materialization_intent" / "basic_plan"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "workspace-materialization-intent-input.json").read_text(encoding="utf-8")
    )


class WorkspaceMaterializationIntentSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_workspace_materialization_intent_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-workspace-materialization-intent-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_plan_reports_collision_redaction_and_unavailable_files(self) -> None:
        summary = build_workspace_materialization_intent_summary(_load_input())
        findings_by_path = {item["source_path"]: item for item in summary["file_plans"]}

        self.assertEqual(
            findings_by_path["readout_calibration_entrypoint.ipynb"]["finding"],
            "planned",
        )
        self.assertEqual(
            findings_by_path["experiment_session_setup.ipynb"]["finding"],
            "collision_requires_review",
        )
        self.assertEqual(
            findings_by_path["secrets/device_config.py"]["finding"],
            "skipped_redacted",
        )
        self.assertEqual(
            findings_by_path["helpers/lab_local_driver.py"]["finding"],
            "unavailable",
        )
        self.assertEqual(
            findings_by_path["experiment_session_setup.ipynb"]["does_not_claim"],
            "overwrite_or_merge_performed",
        )

    def test_request_summary_counts_findings_without_workspace_claims(self) -> None:
        summary = build_workspace_materialization_intent_summary(_load_input())
        request = summary["materialization_requests"][0]

        self.assertEqual(request["planned_path_count"], 4)
        self.assertEqual(
            request["finding_counts"],
            {
                "collision_requires_review": 1,
                "planned": 1,
                "skipped_redacted": 1,
                "unavailable": 1,
            },
        )
        self.assertEqual(
            {item["does_not_claim"] for item in summary["attention"]},
            {
                "current_filesystem_state",
                "restored_or_materialized_workspace",
                "overwrite_or_merge_performed",
                "runnable_environment",
                "execution_permission_or_runtime_behavior",
            },
        )

    def test_attention_records_all_boundary_deferrals(self) -> None:
        summary = build_workspace_materialization_intent_summary(_load_input())
        source = _load_input()

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            source["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["materialization_policy"]["workspace_creation"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "workspace_creation"):
            build_workspace_materialization_intent_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["materialization_policy"]["git_checkout"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected workspace materialization intent"):
            build_workspace_materialization_intent_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_workspace_materialization_intent_summary(source)

        source["materialization_policy"]["workspace_creation"] = "mutated"
        source["managed_code_versions"][0]["stable_identity"]["stable_id"] = "mutated"
        source["materialization_requests"][0]["destination"]["root_path"] = "mutated"

        self.assertEqual(
            summary["materialization_policy"]["workspace_creation"],
            "not_performed",
        )
        self.assertEqual(
            summary["selected_versions"][0]["stable_identity"]["stable_id"],
            "sc-codever-readout-0001",
        )
        self.assertEqual(
            summary["materialization_requests"][0]["root_path"],
            "workspaces/readout-rerun-0001",
        )

    def test_unrequested_managed_versions_are_not_reported_as_selected(self) -> None:
        source = _load_input()
        extra_version = copy.deepcopy(source["managed_code_versions"][0])
        extra_version["version_id"] = "managed-code-version-not-selected"
        extra_version["stable_identity"]["stable_id"] = "sc-codever-not-selected"
        source["managed_code_versions"].append(extra_version)

        summary = build_workspace_materialization_intent_summary(source)

        self.assertEqual(
            [item["version_id"] for item in summary["selected_versions"]],
            ["managed-code-version-readout-0001"],
        )

    def test_duplicate_version_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["managed_code_versions"][0])
        source["managed_code_versions"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate version_id"):
            build_workspace_materialization_intent_summary(source)

    def test_request_must_reference_known_version(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["selected_version_id"] = "missing-version"

        with self.assertRaisesRegex(ValueError, "references missing managed version"):
            build_workspace_materialization_intent_summary(source)

    def test_file_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["path"] = "/private/path.py"

        with self.assertRaisesRegex(ValueError, "non-relative file path"):
            build_workspace_materialization_intent_summary(source)

    def test_backslash_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["materialization_path"] = (
            "code\\entrypoint.py"
        )

        with self.assertRaisesRegex(ValueError, "non-relative materialization path"):
            build_workspace_materialization_intent_summary(source)

    def test_destination_root_must_be_relative(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["destination"]["root_path"] = "../outside"

        with self.assertRaisesRegex(ValueError, "destination root path must be relative"):
            build_workspace_materialization_intent_summary(source)

    def test_existing_destination_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["existing_destination_entries"][0]["path"] = (
            "/tmp/existing.py"
        )

        with self.assertRaisesRegex(ValueError, "existing paths must be relative"):
            build_workspace_materialization_intent_summary(source)

    def test_destination_relative_existing_path_reports_collision(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["existing_destination_entries"][0]["path"] = (
            "code/readout_calibration_entrypoint.ipynb"
        )

        summary = build_workspace_materialization_intent_summary(source)
        findings_by_path = {item["source_path"]: item for item in summary["file_plans"]}

        self.assertEqual(
            findings_by_path["readout_calibration_entrypoint.ipynb"]["finding"],
            "collision_requires_review",
        )

    def test_dot_components_in_existing_paths_are_rejected(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["existing_destination_entries"][0]["path"] = (
            "workspaces/readout-rerun-0001/code/./readout_calibration_entrypoint.ipynb"
        )

        with self.assertRaisesRegex(ValueError, "existing paths must be relative"):
            build_workspace_materialization_intent_summary(source)

    def test_empty_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["materialization_path"] = ""

        with self.assertRaisesRegex(ValueError, "non-relative materialization path"):
            build_workspace_materialization_intent_summary(source)

    def test_current_directory_paths_are_rejected(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["destination"]["root_path"] = "."

        with self.assertRaisesRegex(ValueError, "destination root path must be relative"):
            build_workspace_materialization_intent_summary(source)

    def test_duplicate_destination_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][3]["materialization_path"] = (
            "code/secrets/device_config.py"
        )

        with self.assertRaisesRegex(ValueError, "duplicate materialization paths"):
            build_workspace_materialization_intent_summary(source)

    def test_content_available_files_require_integrity_hint(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0].pop("content_state")

        with self.assertRaisesRegex(ValueError, "require content_state"):
            build_workspace_materialization_intent_summary(source)

    def test_non_content_available_files_must_not_carry_integrity_hint(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][2]["content_state"] = {
            "digest_algorithm": "sha256",
            "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "size_bytes": 1,
            "observed_at": "2026-05-21T12:00:00Z",
        }

        with self.assertRaisesRegex(ValueError, "must not carry content_state"):
            build_workspace_materialization_intent_summary(source)

    def test_digest_algorithm_must_be_sha256(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["content_state"][
            "digest_algorithm"
        ] = "md5"

        with self.assertRaisesRegex(ValueError, "must use sha256"):
            build_workspace_materialization_intent_summary(source)

    def test_integrity_hints_must_use_sha256_hex_digest(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["content_state"]["digest"] = (
            "sha256:not-a-real-digest"
        )

        with self.assertRaisesRegex(ValueError, "sha256-prefixed hex digest"):
            build_workspace_materialization_intent_summary(source)

    def test_boundary_policy_claims_are_rejected(self) -> None:
        policy_cases = {
            "filesystem_inspection": "performed_elsewhere",
            "overwrite_behavior": "overwrite_allowed",
            "code_import": "performed_elsewhere",
            "code_execution": "performed_elsewhere",
        }
        for key, value in policy_cases.items():
            with self.subTest(key=key):
                source = _load_input()
                source["materialization_policy"][key] = value

                with self.assertRaisesRegex(ValueError, key):
                    build_workspace_materialization_intent_summary(source)

    def test_destination_path_kind_must_remain_declared_relative_workspace_path(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["destination"]["path_kind"] = (
            "declared_relative_package_path"
        )

        with self.assertRaisesRegex(ValueError, "destination path kind"):
            build_workspace_materialization_intent_summary(source)

    def test_collision_policy_must_require_review(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["destination"]["collision_policy"] = (
            "overwrite_allowed"
        )

        with self.assertRaisesRegex(ValueError, "collision policy"):
            build_workspace_materialization_intent_summary(source)

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.managed_code_version import (
    build_managed_code_version_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "managed_code_version" / "basic_record"


def _load_input() -> dict:
    return json.loads((FIXTURE / "managed-code-version-input.json").read_text(encoding="utf-8"))


class ManagedCodeVersionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_managed_code_version_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-managed-code-version-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_managed_version_summarizes_identity_without_materializing_workspace(self) -> None:
        summary = build_managed_code_version_summary(_load_input())
        version = summary["managed_code_versions"][0]

        self.assertEqual(version["stable_identity"]["stable_id"], "sc-codever-readout-0001")
        self.assertEqual(version["file_count"], 3)
        self.assertEqual(version["integrity_hint_count"], 3)
        self.assertEqual(
            {item["source_capture_state"] for item in summary["file_inventory"]},
            {"content_captured"},
        )
        self.assertEqual(
            version["materialization_intent"]["mode"],
            "editable_workspace_intent",
        )
        self.assertEqual(version["restore_claim"], "not_restored_by_fixture")
        self.assertEqual(version["execution_claim"], "not_imported_loaded_or_executed")

    def test_attention_records_all_boundary_deferrals(self) -> None:
        summary = build_managed_code_version_summary(_load_input())

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            [
                "managed_storage_record_only",
                "integrity_hints_not_storage_contract",
                "materialization_not_performed",
                "environment_not_restored",
                "code_execution_not_granted",
                "internal_git_not_inspected",
            ],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["managed_version_policy"]["environment_restoration"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "environment_restoration"):
            build_managed_code_version_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_managed_code_version_summary(source)

        source["managed_version_policy"]["storage_contract"] = "mutated"
        source["managed_code_versions"][0]["stable_identity"]["stable_id"] = "mutated"
        source["managed_code_versions"][0]["materialization_intent"]["mode"] = "mutated"

        self.assertEqual(
            summary["managed_version_policy"]["storage_contract"],
            "record_only",
        )
        self.assertEqual(
            summary["managed_code_versions"][0]["stable_identity"]["stable_id"],
            "sc-codever-readout-0001",
        )
        self.assertEqual(
            summary["managed_code_versions"][0]["materialization_intent"]["mode"],
            "editable_workspace_intent",
        )

    def test_duplicate_version_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["managed_code_versions"][0])
        source["managed_code_versions"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate version_id"):
            build_managed_code_version_summary(source)

    def test_version_must_reference_known_source_record(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["source_record_id"] = "missing-record"

        with self.assertRaisesRegex(ValueError, "references missing code snapshot record"):
            build_managed_code_version_summary(source)

    def test_file_records_must_match_source_record_inclusion(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["path"] = "different.py"

        with self.assertRaisesRegex(ValueError, "must match source record include list"):
            build_managed_code_version_summary(source)

    def test_reference_only_source_entries_cannot_be_managed_inventory(self) -> None:
        source = _load_input()
        source["code_snapshot_records"][0]["snapshot_scope"]["capture_state_by_file"][
            "helpers/record_measurement_context.py"
        ] = "reference_only"

        with self.assertRaisesRegex(ValueError, "require content-captured source entries"):
            build_managed_code_version_summary(source)

    def test_capture_state_mapping_order_is_not_semantic(self) -> None:
        source = _load_input()
        scope = source["code_snapshot_records"][0]["snapshot_scope"]
        scope["capture_state_by_file"] = {
            path: scope["capture_state_by_file"][path] for path in reversed(scope["included_files"])
        }

        summary = build_managed_code_version_summary(source)

        self.assertEqual(
            {item["source_capture_state"] for item in summary["file_inventory"]},
            {"content_captured"},
        )

    def test_duplicate_file_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][2]["path"] = (
            "readout_calibration_entrypoint.ipynb"
        )

        with self.assertRaisesRegex(ValueError, "duplicate file paths"):
            build_managed_code_version_summary(source)

    def test_file_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["path"] = "/private/path.py"

        with self.assertRaisesRegex(ValueError, "non-relative file path"):
            build_managed_code_version_summary(source)

    def test_backslash_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["materialization_path"] = (
            "redacted\\fixture.py"
        )

        with self.assertRaisesRegex(ValueError, "non-relative materialization path"):
            build_managed_code_version_summary(source)

    def test_materialization_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["materialization_path"] = (
            "../outside.py"
        )

        with self.assertRaisesRegex(ValueError, "non-relative materialization path"):
            build_managed_code_version_summary(source)

    def test_duplicate_materialization_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][2]["materialization_path"] = (
            "code/readout_calibration_entrypoint.ipynb"
        )

        with self.assertRaisesRegex(ValueError, "duplicate materialization paths"):
            build_managed_code_version_summary(source)

    def test_boundary_claims_must_remain_non_execution_claims(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["execution_claim"] = "executed_by_fixture"

        with self.assertRaisesRegex(ValueError, "execution claim"):
            build_managed_code_version_summary(source)

    def test_notebook_files_must_match_source_record_recording_policy(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["recorded_form"] = (
            "source_with_outputs"
        )

        with self.assertRaisesRegex(ValueError, "notebook files"):
            build_managed_code_version_summary(source)

    def test_digest_algorithm_must_be_sha256(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["content_state"][
            "digest_algorithm"
        ] = "md5"

        with self.assertRaisesRegex(ValueError, "must use sha256"):
            build_managed_code_version_summary(source)

    def test_integrity_hints_must_use_sha256_prefix(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["content_state"]["digest"] = "1111"

        with self.assertRaisesRegex(ValueError, "sha256-prefixed hex digest"):
            build_managed_code_version_summary(source)

    def test_integrity_hints_must_use_sha256_hex_digest(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_records"][0]["content_state"]["digest"] = (
            "sha256:not-a-real-digest"
        )

        with self.assertRaisesRegex(ValueError, "sha256-prefixed hex digest"):
            build_managed_code_version_summary(source)

    def test_expected_summary_covers_boundary_output(self) -> None:
        summary = json.loads(
            (FIXTURE / "expected-managed-code-version-summary.json").read_text(encoding="utf-8")
        )
        candidate = summary["candidate_summary"]
        version = candidate["managed_code_versions"][0]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(summary["source_fixture"], "managed-code-version-input.json")
        self.assertEqual(version["version_id"], "managed-code-version-readout-0001")
        self.assertEqual(version["file_count"], 3)
        self.assertEqual(version["notebook_file_count"], 2)
        self.assertEqual(
            {item["source_capture_state"] for item in candidate["file_inventory"]},
            {"content_captured"},
        )
        self.assertIn("storage backend", summary["reference_semantics"]["contract_guard"])
        self.assertIn("integrity hints", summary["reference_semantics"]["integrity"])
        self.assertIn("no workspace is created", summary["boundary_notes"][4])
        self.assertEqual(
            attention["environment_not_restored"]["does_not_claim"],
            "runnable_environment",
        )
        self.assertEqual(
            attention["code_execution_not_granted"]["does_not_claim"],
            "execution_permission",
        )
        self.assertIn("internal Git analysis", summary["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()

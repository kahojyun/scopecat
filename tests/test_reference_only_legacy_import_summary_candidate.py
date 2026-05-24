from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.reference_only_legacy_import import (
    build_reference_only_legacy_import_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reference_only_legacy_import" / "basic_reference"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "reference-only-legacy-import-input.json").read_text(encoding="utf-8")
    )


class ReferenceOnlyLegacyImportSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_reference_only_summary(self) -> None:
        summary = build_reference_only_legacy_import_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-reference-only-legacy-import-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertEqual(summary["storage_mutation"], "not_performed")
        self.assertEqual(summary["copy_result"], "not_copied")

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_reference_only_legacy_import_summary(source)

        source["reference_only_request"]["current_primary_data_reference"]["display_path"] = (
            "mutated"
        )
        source["adapter_manifest"]["linked_context"][0]["label"] = "mutated"

        self.assertEqual(
            summary["current_primary_data_reference"]["display_path"],
            "LEGACY_SOURCE:/redacted-shared-storage/2026/05/01/legacy-record-001",
        )
        self.assertEqual(summary["linked_context"][0]["label"], "Run-local parameter snapshot")

    def test_requires_approved_reference_only_request(self) -> None:
        source = _load_input()
        source["reference_only_request"]["review"]["approval_state"] = "pending_review"

        with self.assertRaisesRegex(ValueError, "must be approved"):
            build_reference_only_legacy_import_summary(source)

    def test_rejects_adapter_manifest_that_is_not_ready(self) -> None:
        source = _load_input()
        source["adapter_manifest"]["primary_data"]["reference_state"] = "unavailable"
        source["adapter_manifest"]["primary_data"]["reason"] = "Adapter could not expose data."
        source["reference_only_request"]["review"]["reviewed_manifest_classification"] = (
            "blocked_pending_source_review"
        )

        with self.assertRaisesRegex(ValueError, "ready adapter manifest"):
            build_reference_only_legacy_import_summary(source)

    def test_rejects_copy_or_storage_mutation_claims(self) -> None:
        source = _load_input()
        source["reference_only_policy"]["storage_mutation"] = "write_manifest"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            build_reference_only_legacy_import_summary(source)

        source = _load_input()
        source["reference_only_request"]["materialization"]["primary_data"] = "copy_into_storage"

        with self.assertRaisesRegex(ValueError, "materialization"):
            build_reference_only_legacy_import_summary(source)

    def test_current_reference_display_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"]["display_path"] = (
            "/Users/example/lab/legacy-record-001"
        )

        with self.assertRaisesRegex(ValueError, "display_path"):
            build_reference_only_legacy_import_summary(source)

        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"]["display_path"] = (
            "LEGACY_SOURCE:/home/alice/redacted/legacy-record-001"
        )

        with self.assertRaisesRegex(ValueError, "display_path"):
            build_reference_only_legacy_import_summary(source)

    def test_current_reference_rejects_extra_observation_or_copy_claims(self) -> None:
        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"]["observed_at"] = (
            "2026-05-03T10:00:00Z"
        )

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_reference_only_legacy_import_summary(source)

        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"]["materialized_path"] = (
            "records/legacy-rabi-001/primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_reference_only_legacy_import_summary(source)

    def test_current_reference_must_be_available_for_ready_summary(self) -> None:
        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"]["reference_state"] = (
            "unavailable"
        )
        source["reference_only_request"]["current_primary_data_reference"]["reason"] = (
            "The shared-storage reference was not available during review."
        )

        with self.assertRaisesRegex(ValueError, "adapter_declared_available"):
            build_reference_only_legacy_import_summary(source)

    def test_current_reference_must_match_adapter_primary_data_path(self) -> None:
        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"][
            "adapter_primary_data_path"
        ] = "source-data/other.csv"

        with self.assertRaisesRegex(ValueError, "adapter primary data path"):
            build_reference_only_legacy_import_summary(source)

    def test_reference_only_request_must_not_claim_observation(self) -> None:
        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"]["digest"] = (
            "sha256:ffbcc9e95e07eb0e638faf7779958065fa2d331a2f8b15442b0bba899b30054d"
        )

        with self.assertRaisesRegex(ValueError, "digest observation"):
            build_reference_only_legacy_import_summary(source)

        source = _load_input()
        source["reference_only_request"]["current_primary_data_reference"]["openability"] = "opened"

        with self.assertRaisesRegex(ValueError, "openability"):
            build_reference_only_legacy_import_summary(source)

    def test_duplicate_link_ids_are_rejected_by_embedded_manifest_validator(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["adapter_manifest"]["linked_context"][0])
        source["adapter_manifest"]["linked_context"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_reference_only_legacy_import_summary(source)


if __name__ == "__main__":
    unittest.main()

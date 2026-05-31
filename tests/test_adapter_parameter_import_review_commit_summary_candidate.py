from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.adapter_parameter_import_review_commit import (
    build_adapter_parameter_import_review_commit_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "adapter_parameter_import_review_commit" / "basic_review_commit"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-commit-input.json").read_text(encoding="utf-8"))


class AdapterParameterImportReviewCommitSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_adapter_parameter_import_review_commit_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-review-commit-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_adapter_parameter_import_review_commit_summary(source)

        source["managed_parameter_state"]["entries"][0]["value"] = {"mutated": ["value"]}
        source["managed_parameter_state"]["lineage"]["target_scope"].append("mutated")
        source["side_effect_claims"]["storage_mutation"] = "performed"

        self.assertEqual(summary["managed_parameter_state"]["entries"][0]["value"], 5012500000)
        self.assertEqual(
            summary["managed_parameter_state"]["lineage"]["target_scope"],
            ["sample-alpha", "qA", "default_bias"],
        )
        self.assertEqual(summary["side_effects"]["storage_mutation"], "not_performed")

    def test_policy_must_match_expected_shape(self) -> None:
        source = _load_input()
        source["adapter_parameter_import_review_policy"]["legacy_parser"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_review_must_match_preview_identity_and_classification(self) -> None:
        source = _load_input()
        source["review"]["preview_candidate_state_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "preview candidate state"):
            build_adapter_parameter_import_review_commit_summary(source)

        source = _load_input()
        source["review"]["reviewed_preview_classification"] = "stale"

        with self.assertRaisesRegex(ValueError, "preview classification"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_review_must_be_accepted_and_explicit(self) -> None:
        source = _load_input()
        source["review"]["review_status"] = "pending"

        with self.assertRaisesRegex(ValueError, "must be accepted"):
            build_adapter_parameter_import_review_commit_summary(source)

        source = _load_input()
        source["review"]["accepted_entry_paths"] = []

        with self.assertRaisesRegex(ValueError, "accepted entry paths"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_review_can_accept_candidate_entries_only(self) -> None:
        source = _load_input()
        source["review"]["accepted_entry_paths"] = ["readout.qA.frequency_hz"]
        source["review"]["rejected_or_deferred_entry_paths"] = [
            "qubits.qA.drive_frequency_hz",
            "qubits.qA.pi_amp",
            "readout.qA.calibration_table",
        ]

        with self.assertRaisesRegex(ValueError, "candidate entries only"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_managed_entries_must_match_accepted_paths(self) -> None:
        source = _load_input()
        source["managed_parameter_state"]["entries"] = source["managed_parameter_state"]["entries"][
            :1
        ]
        source["managed_parameter_state"]["trusted_entry_paths"] = ["qubits.qA.drive_frequency_hz"]

        with self.assertRaisesRegex(ValueError, "entries must match accepted entry paths"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_managed_entry_values_units_and_sources_must_come_from_preview(self) -> None:
        source = _load_input()
        source["managed_parameter_state"]["entries"][0]["value"] = 1

        with self.assertRaisesRegex(ValueError, "value must come from preview"):
            build_adapter_parameter_import_review_commit_summary(source)

        source = _load_input()
        source["managed_parameter_state"]["entries"][0]["source_ids"] = [
            "legacy-xlsx-parameter-table-001"
        ]

        with self.assertRaisesRegex(ValueError, "sources must come from preview"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_managed_lineage_must_come_from_preview_hint(self) -> None:
        source = _load_input()
        source["managed_parameter_state"]["lineage"]["lineage_label"] = "other"

        with self.assertRaisesRegex(ValueError, "lineage label"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_side_effect_claims_must_stay_out_of_scope(self) -> None:
        source = _load_input()
        source["side_effect_claims"]["hardware_write_back"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_write_back"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_adapter_preview_manifest_is_validated_before_commit_review(self) -> None:
        source = _load_input()
        source["adapter_preview_manifest"]["adapter"]["parsing_authority"] = "scopecat_core"

        with self.assertRaisesRegex(ValueError, "parsing authority"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_duplicate_review_paths_are_rejected(self) -> None:
        source = _load_input()
        source["review"]["accepted_entry_paths"].append("qubits.qA.pi_amp")

        with self.assertRaisesRegex(ValueError, "duplicate accepted entry path"):
            build_adapter_parameter_import_review_commit_summary(source)

    def test_excluded_entries_include_all_not_accepted_preview_entries(self) -> None:
        summary = build_adapter_parameter_import_review_commit_summary(_load_input())

        self.assertEqual(
            [entry["path"] for entry in summary["excluded_preview_entries"]],
            ["readout.qA.frequency_hz", "readout.qA.calibration_table"],
        )


if __name__ == "__main__":
    unittest.main()

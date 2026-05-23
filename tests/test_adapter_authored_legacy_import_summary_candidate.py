from __future__ import annotations

import copy
import csv
import json
import unittest
from pathlib import Path

from implementation_candidates.adapter_authored_legacy_import import (
    build_adapter_authored_legacy_import_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "adapter_authored_legacy_import" / "basic_1d_record"


def _load_input() -> dict:
    return json.loads((FIXTURE / "adapter-import-manifest.json").read_text(encoding="utf-8"))


class AdapterAuthoredLegacyImportSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_adapter_authored_legacy_import_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-adapter-manifest-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_fixture_source_data_is_openable_but_not_parsed_by_builder(self) -> None:
        source = _load_input()
        data_path = FIXTURE / source["primary_data"]["path"]

        with data_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), source["declared_preview_metadata"]["declared_row_count"])
        self.assertEqual(rows[0]["drive_frequency"], "5.100")

    def test_boundary_keeps_legacy_reader_and_public_api_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-adapter-manifest-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("not a stable public API", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["adapter_import_policy"]["legacy_source_parsing"],
            "not_performed_by_scopecat",
        )
        self.assertEqual(
            attention["legacy_parser_not_in_core"]["does_not_claim"],
            "labrad_datavault_labber_reader",
        )
        self.assertIn(
            "stable public adapter API",
            expected["decisions_not_earned"],
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_adapter_authored_legacy_import_summary(source)

        source["primary_data"]["path"] = "mutated"
        source["declared_preview_metadata"]["declared_columns"][0]["label"] = "mutated"
        source["linked_context"][0]["label"] = "mutated"

        self.assertEqual(summary["primary_data"]["path"], "source-data/measurement.csv")
        self.assertEqual(summary["preview"]["declared_roles"][0]["label"], "Drive frequency")
        self.assertEqual(summary["linked_context"][0]["label"], "Run-local parameter snapshot")

    def test_core_legacy_parser_claims_are_rejected(self) -> None:
        source = _load_input()
        source["adapter_import_policy"]["legacy_source_parsing"] = "performed_by_scopecat"

        with self.assertRaisesRegex(ValueError, "legacy_source_parsing"):
            build_adapter_authored_legacy_import_summary(source)

        source = _load_input()
        source["adapter"]["parsing_authority"] = "scopecat_core"

        with self.assertRaisesRegex(ValueError, "parsing authority"):
            build_adapter_authored_legacy_import_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["adapter_import_policy"]["labrad_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_adapter_authored_legacy_import_summary(source)

    def test_manifest_schema_is_intentionally_versioned_as_fixture_contract(self) -> None:
        source = _load_input()
        source["manifest_schema"] = "scopecat.adapter_import_manifest.v1"

        with self.assertRaisesRegex(ValueError, "manifest_schema"):
            build_adapter_authored_legacy_import_summary(source)

    def test_primary_data_path_must_be_relative(self) -> None:
        source = _load_input()
        source["primary_data"]["path"] = "/private/legacy/measurement.csv"

        with self.assertRaisesRegex(ValueError, "primary data path"):
            build_adapter_authored_legacy_import_summary(source)

    def test_source_display_path_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["source_identity"]["original_path_display"] = "/Users/example/legacy/record"

        with self.assertRaisesRegex(ValueError, "original_path_display"):
            build_adapter_authored_legacy_import_summary(source)

    def test_source_identity_labels_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["source_identity"]["external_root_label"] = "/Users/example/lab-share"

        with self.assertRaisesRegex(ValueError, "external_root_label"):
            build_adapter_authored_legacy_import_summary(source)

    def test_preview_axes_must_reference_declared_columns(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["plot_candidates"][0]["y"] = "undeclared_signal"

        with self.assertRaisesRegex(ValueError, "declared columns"):
            build_adapter_authored_legacy_import_summary(source)

    def test_preview_declared_column_names_must_be_unique(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["declared_columns"][1]["name"] = "drive_frequency"

        with self.assertRaisesRegex(ValueError, "unique names"):
            build_adapter_authored_legacy_import_summary(source)

    def test_declared_row_count_must_be_positive(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["declared_row_count"] = 0

        with self.assertRaisesRegex(ValueError, "declared_row_count"):
            build_adapter_authored_legacy_import_summary(source)

    def test_blocking_adapter_findings_dominate_review_only_states(self) -> None:
        source = _load_input()
        source["linked_context"][0]["reference_state"] = "unavailable"
        source["linked_context"][0]["reason"] = "The adapter could not include the context file."
        source["adapter_findings"][0]["severity"] = "block_import"

        summary = build_adapter_authored_legacy_import_summary(source)

        self.assertEqual(summary["classification"], "blocked_by_adapter_finding")

    def test_duplicate_link_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["linked_context"][0])
        source["linked_context"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_adapter_authored_legacy_import_summary(source)

    def test_unavailable_linked_context_requires_reason(self) -> None:
        source = _load_input()
        source["linked_context"][0]["reference_state"] = "unavailable"
        source["linked_context"][0]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_adapter_authored_legacy_import_summary(source)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_contents_preview import (
    build_handoff_package_contents_preview_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "handoff_package_contents_preview" / "basic_package"


def _load_input() -> dict:
    return json.loads((FIXTURE / "package-preview-input.json").read_text(encoding="utf-8"))


class HandoffPackageContentsPreviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_handoff_package_contents_preview_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-package-preview-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_classifies_package_without_accepting_import_or_storage(self) -> None:
        summary = build_handoff_package_contents_preview_summary(_load_input())
        measurements = {
            item["measurement_record_id"]: item for item in summary["selected_measurements"]
        }

        self.assertEqual(summary["package"]["classification"], "needs_review_before_acceptance")
        self.assertEqual(
            measurements["measurement-1001"]["classification"],
            "preview_ready_for_opening",
        )
        self.assertEqual(
            measurements["measurement-1002"]["classification"],
            "needs_preview_metadata_review",
        )
        self.assertEqual(measurements["measurement-1001"]["import_acceptance"], "not_accepted")
        self.assertEqual(measurements["measurement-1002"]["storage_mutation"], "not_performed")

    def test_preview_findings_do_not_claim_package_integrity_or_import_failure(self) -> None:
        summary = build_handoff_package_contents_preview_summary(_load_input())
        findings = {item["finding"]: item for item in summary["preview_findings"]}

        self.assertEqual(
            findings["preview_metadata_missing"]["does_not_claim"],
            "packaged_data_unreadable_or_invalid",
        )
        self.assertEqual(
            findings["linked_context_not_packaged_visible_reference"]["does_not_claim"],
            "package_integrity_or_import_acceptance_failure",
        )
        self.assertEqual(
            findings["linked_context_missing_from_package"]["does_not_claim"],
            "package_integrity_or_import_acceptance_failure",
        )

    def test_boundary_output_keeps_archive_and_schema_inference_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-package-preview-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("not an importer", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["package_preview_policy"]["archive_extraction"],
            "not_performed",
        )
        self.assertEqual(
            attention["schema_inference_not_performed"]["does_not_claim"],
            "automatic_schema_detection",
        )
        self.assertIn("Handoff package contents preview classifies", expected["boundary_notes"][0])
        self.assertIn("handoff package review GUI", expected["decisions_not_earned"])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["package_preview_policy"]["package_integrity"] = "verified"

        with self.assertRaisesRegex(ValueError, "package_integrity"):
            build_handoff_package_contents_preview_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["package_preview_policy"]["package_acceptance"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_handoff_package_contents_preview_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_handoff_package_contents_preview_summary(source)

        source["selected_measurements"][0]["primary_data"]["label"] = "mutated"
        source["selected_measurements"][0]["declared_preview_metadata"]["declared_columns"][0][
            "label"
        ] = "mutated"
        source["linked_context"][0]["label"] = "mutated"

        measurement = summary["selected_measurements"][0]
        linked = summary["package_contents"][4]
        self.assertEqual(measurement["primary_data"]["label"], "Run 1001 Rabi source data")
        self.assertEqual(measurement["preview"]["declared_roles"][0]["label"], "Drive amplitude")
        self.assertEqual(linked["label"], "Session wiring note")

    def test_duplicate_measurement_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["selected_measurements"][0])
        source["selected_measurements"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate measurement_record_id"):
            build_handoff_package_contents_preview_summary(source)

    def test_duplicate_link_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["linked_context"][0])
        source["linked_context"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_handoff_package_contents_preview_summary(source)

    def test_duplicate_packaged_paths_are_rejected(self) -> None:
        source = _load_input()
        source["selected_measurements"][1]["default_bundle"][1]["package_path"] = (
            "measurements/measurement-1001/parameter-snapshot.json"
        )

        with self.assertRaisesRegex(ValueError, "duplicate package_path"):
            build_handoff_package_contents_preview_summary(source)

    def test_linked_context_duplicate_packaged_paths_are_rejected(self) -> None:
        source = _load_input()
        source["linked_context"][0]["package_path"] = "measurements/measurement-1001/primary.csv"

        with self.assertRaisesRegex(ValueError, "duplicate package_path"):
            build_handoff_package_contents_preview_summary(source)

    def test_missing_primary_bundle_item_is_rejected(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["default_bundle"] = [
            item
            for item in source["selected_measurements"][0]["default_bundle"]
            if item["kind"] != "primary_data"
        ]

        with self.assertRaisesRegex(ValueError, "one primary data item"):
            build_handoff_package_contents_preview_summary(source)

    def test_duplicate_preview_column_names_are_rejected(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["declared_preview_metadata"]["declared_columns"].append(
            {
                "name": "drive_amp",
                "label": "Drive amplitude duplicate",
                "role": "sweep_axis",
                "unit": "arb",
            }
        )

        with self.assertRaisesRegex(ValueError, "unique names"):
            build_handoff_package_contents_preview_summary(source)

    def test_primary_bundle_path_must_match_primary_data(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][0]["package_path"] = (
            "measurements/measurement-1001/wrong.csv"
        )

        with self.assertRaisesRegex(ValueError, "primary bundle item path"):
            build_handoff_package_contents_preview_summary(source)

    def test_plot_candidate_source_must_match_primary_data(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][0][
            "source"
        ] = "measurements/measurement-1001/wrong.csv"

        with self.assertRaisesRegex(ValueError, "plot candidate source"):
            build_handoff_package_contents_preview_summary(source)

    def test_package_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][0]["package_path"] = (
            "/private/package/primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "path must be relative"):
            build_handoff_package_contents_preview_summary(source)

    def test_display_path_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["package_identity"]["display_path"] = (
            "/" + "Users" + "/example/lab/private/package.zip"
        )

        with self.assertRaisesRegex(ValueError, "display path"):
            build_handoff_package_contents_preview_summary(source)

    def test_non_packaged_context_requires_reason(self) -> None:
        source = _load_input()
        source["linked_context"][1]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_handoff_package_contents_preview_summary(source)

    def test_non_packaged_context_must_not_carry_package_path(self) -> None:
        source = _load_input()
        source["linked_context"][1]["package_path"] = "context/summary.csv"

        with self.assertRaisesRegex(ValueError, "must not carry package_path"):
            build_handoff_package_contents_preview_summary(source)

    def test_degraded_preview_does_not_carry_inferred_columns(self) -> None:
        source = _load_input()
        source["selected_measurements"][1]["declared_preview_metadata"]["declared_columns"].append(
            {
                "name": "delay",
                "role": "sweep_axis",
                "label": "Delay",
                "unit": "us",
            }
        )

        with self.assertRaisesRegex(ValueError, "degraded preview"):
            build_handoff_package_contents_preview_summary(source)

    def test_preview_axes_must_reference_declared_columns(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][0][
            "y"
        ] = "undeclared_signal"

        with self.assertRaisesRegex(ValueError, "declared columns"):
            build_handoff_package_contents_preview_summary(source)

    def test_preview_metadata_authority_must_stay_manifest_only(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["declared_preview_metadata"]["metadata_authority"] = (
            "source_parser"
        )

        with self.assertRaisesRegex(ValueError, "metadata authority"):
            build_handoff_package_contents_preview_summary(source)

    def test_linked_context_must_reference_selected_measurement(self) -> None:
        source = _load_input()
        source["linked_context"][0]["linked_measurement_record_ids"] = ["measurement-9999"]

        with self.assertRaisesRegex(ValueError, "must reference selected measurements"):
            build_handoff_package_contents_preview_summary(source)

    def test_linked_context_must_not_mix_unselected_measurements(self) -> None:
        source = _load_input()
        source["linked_context"][0]["linked_measurement_record_ids"] = [
            "measurement-9999",
            "measurement-1001",
        ]

        with self.assertRaisesRegex(ValueError, "must reference selected measurements"):
            build_handoff_package_contents_preview_summary(source)


if __name__ == "__main__":
    unittest.main()

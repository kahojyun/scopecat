from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.measurement_record_import_preview import (
    build_measurement_record_import_preview_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurement_record_import_preview" / "basic_preview"


def _load_input() -> dict:
    return json.loads((FIXTURE / "import-preview-input.json").read_text(encoding="utf-8"))


class MeasurementRecordImportPreviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_measurement_record_import_preview_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-import-preview-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_classifies_records_without_accepting_import(self) -> None:
        summary = build_measurement_record_import_preview_summary(_load_input())
        records = {item["incoming_record_id"]: item for item in summary["incoming_records"]}

        self.assertEqual(
            records["incoming-run-2001-rabi"]["classification"],
            "preview_ready_for_review",
        )
        self.assertEqual(
            records["incoming-run-2002-t1"]["classification"],
            "blocked_pending_source_review",
        )
        self.assertEqual(records["incoming-run-2001-rabi"]["import_acceptance"], "not_accepted")
        self.assertEqual(records["incoming-run-2002-t1"]["storage_mutation"], "not_performed")

    def test_preview_findings_do_not_claim_import_or_storage_failure(self) -> None:
        summary = build_measurement_record_import_preview_summary(_load_input())
        findings = {item["finding"]: item for item in summary["preview_findings"]}

        self.assertEqual(
            findings["source_unavailable"]["does_not_claim"],
            "source_permanently_missing_or_invalid",
        )
        self.assertEqual(
            findings["preview_metadata_missing"]["does_not_claim"],
            "record_cannot_be_imported_or_plotted_later",
        )
        self.assertEqual(
            findings["linked_context_unavailable"]["does_not_claim"],
            "relation_graph_or_package_integrity_invalid",
        )

    def test_boundary_output_keeps_import_and_schema_inference_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-import-preview-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("not an importer", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["import_preview_policy"]["storage_mutation"],
            "not_performed",
        )
        self.assertEqual(
            attention["schema_inference_not_performed"]["does_not_claim"],
            "automatic_schema_detection",
        )
        self.assertIn("Incoming-record import preview classifies", expected["boundary_notes"][0])
        self.assertIn("import review GUI", expected["decisions_not_earned"])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["import_preview_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            build_measurement_record_import_preview_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["import_preview_policy"]["import_writer"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_measurement_record_import_preview_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_measurement_record_import_preview_summary(source)

        source["import_preview_policy"]["schema_inference"] = "mutated"
        source["incoming_records"][0]["primary_data"]["path"] = "mutated"
        source["incoming_records"][0]["declared_preview_metadata"]["declared_columns"][0][
            "label"
        ] = "mutated"

        self.assertEqual(
            summary["import_preview_policy"]["schema_inference"],
            "not_performed",
        )
        self.assertEqual(
            summary["incoming_records"][0]["primary_data"]["path"],
            "source/import-drop/run-2001-rabi-source.csv",
        )
        self.assertEqual(
            summary["incoming_records"][0]["preview"]["declared_roles"][0]["label"],
            "Drive amplitude",
        )

    def test_duplicate_incoming_record_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["incoming_records"][0])
        source["incoming_records"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate incoming_record_id"):
            build_measurement_record_import_preview_summary(source)

    def test_duplicate_link_ids_are_rejected_per_record(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["incoming_records"][0]["linked_context"][0])
        source["incoming_records"][0]["linked_context"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_measurement_record_import_preview_summary(source)

    def test_primary_data_path_must_match_current_reference(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["primary_data"]["path"] = "source/import-drop/wrong.csv"

        with self.assertRaisesRegex(ValueError, "primary data path"):
            build_measurement_record_import_preview_summary(source)

    def test_plot_candidate_source_must_match_primary_data(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["declared_preview_metadata"]["plot_candidates"][0][
            "source"
        ] = "source/import-drop/wrong.csv"

        with self.assertRaisesRegex(ValueError, "plot candidate source"):
            build_measurement_record_import_preview_summary(source)

    def test_current_reference_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["current_reference"]["path"] = "/private/run.csv"

        with self.assertRaisesRegex(ValueError, "current reference path"):
            build_measurement_record_import_preview_summary(source)

    def test_local_source_paths_must_stay_redacted(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["source_identity"]["local_path_redacted"] = False

        with self.assertRaisesRegex(ValueError, "local path"):
            build_measurement_record_import_preview_summary(source)

    def test_display_paths_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["source_identity"]["display_path"] = (
            "/" + "Users" + "/example/lab/run-2001-rabi-source.csv"
        )

        with self.assertRaisesRegex(ValueError, "display path"):
            build_measurement_record_import_preview_summary(source)

    def test_unavailable_current_reference_requires_reason(self) -> None:
        source = _load_input()
        source["incoming_records"][1]["current_reference"]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_measurement_record_import_preview_summary(source)

    def test_unavailable_linked_context_requires_reason(self) -> None:
        source = _load_input()
        source["incoming_records"][1]["linked_context"][0]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_measurement_record_import_preview_summary(source)

    def test_degraded_preview_does_not_carry_inferred_columns(self) -> None:
        source = _load_input()
        source["incoming_records"][1]["declared_preview_metadata"]["declared_columns"].append(
            {
                "name": "delay",
                "role": "sweep_axis",
                "label": "Delay",
                "unit": "us",
            }
        )

        with self.assertRaisesRegex(ValueError, "degraded preview"):
            build_measurement_record_import_preview_summary(source)

    def test_degraded_preview_does_not_silently_drop_shape_metadata(self) -> None:
        source = _load_input()
        source["incoming_records"][1]["declared_preview_metadata"]["data_shape"] = {
            "kind": "declared_1d_table",
            "axis_order": ["delay", "signal"],
        }

        with self.assertRaisesRegex(ValueError, "degraded preview"):
            build_measurement_record_import_preview_summary(source)

    def test_preview_axes_must_reference_declared_columns(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["declared_preview_metadata"]["plot_candidates"][0]["y"] = (
            "undeclared_signal"
        )

        with self.assertRaisesRegex(ValueError, "declared columns"):
            build_measurement_record_import_preview_summary(source)

    def test_preview_axis_order_must_reference_declared_columns(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["declared_preview_metadata"]["data_shape"]["axis_order"][
            0
        ] = "undeclared_drive"

        with self.assertRaisesRegex(ValueError, "axis order"):
            build_measurement_record_import_preview_summary(source)

    def test_preview_metadata_authority_must_stay_manifest_only(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["declared_preview_metadata"]["metadata_authority"] = (
            "source_parser"
        )

        with self.assertRaisesRegex(ValueError, "metadata authority"):
            build_measurement_record_import_preview_summary(source)

    def test_linked_context_authority_must_stay_manifest_only(self) -> None:
        source = _load_input()
        source["incoming_records"][0]["linked_context"][0]["authority"] = "observed_filesystem"

        with self.assertRaisesRegex(ValueError, "authority"):
            build_measurement_record_import_preview_summary(source)


if __name__ == "__main__":
    unittest.main()

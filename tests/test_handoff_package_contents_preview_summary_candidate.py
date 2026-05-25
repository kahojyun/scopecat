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
        linked = next(
            item
            for item in summary["package_contents"]
            if item["owner_type"] == "linked_context"
            and item["item_id"] == "package-session-wiring-note"
        )
        self.assertEqual(measurement["primary_data"]["label"], "Run 1001 Rabi source data")
        self.assertEqual(measurement["preview"]["declared_roles"][0]["label"], "Drive amplitude")
        self.assertEqual(linked["label"], "Session wiring note")

    def test_duplicate_measurement_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["selected_measurements"][0])
        source["selected_measurements"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate measurement_record_id"):
            build_handoff_package_contents_preview_summary(source)

    def test_managed_measurement_fields_are_validated(self) -> None:
        invalid_cases = (
            (("measurement_record_id",), "/Users/lab/private/measurement", "measurement_record_id"),
            (("experiment_type",), "/Users/lab/private/type", "experiment_type"),
            (("target",), "/Users/lab/private/qA", "target"),
            (("default_bundle", 0, "item_id"), "measurement-1001-private\nsecret", "item_id"),
            (("default_bundle", 0, "kind"), "/Users/lab/private/kind", "kind"),
            (("default_bundle", 0, "include_status"), "surprise_status", "include_status"),
            (("default_bundle", 0, "relation"), "/Users/lab/private/relation", "relation"),
        )
        for path, value, message in invalid_cases:
            with self.subTest(path=path):
                source = _load_input()
                target = source["selected_measurements"][0]
                for segment in path[:-1]:
                    target = target[segment]
                target[path[-1]] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_handoff_package_contents_preview_summary(source)

    def test_selected_measurements_must_not_be_empty(self) -> None:
        source = _load_input()
        source["selected_measurements"] = []

        with self.assertRaisesRegex(ValueError, "requires selected_measurements"):
            build_handoff_package_contents_preview_summary(source)

    def test_duplicate_link_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["linked_context"][0])
        source["linked_context"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_handoff_package_contents_preview_summary(source)

    def test_managed_linked_context_fields_are_validated(self) -> None:
        invalid_cases = (
            ("link_id", "/Users/lab/private/link", "link_id"),
            ("kind", "/Users/lab/private/kind", "kind"),
            ("include_status", "/Users/lab/private/include", "include_status"),
            ("include_status", "surprise_status", "include_status"),
            ("relation", "/Users/lab/private/relation", "relation"),
        )
        for field, value, message in invalid_cases:
            with self.subTest(field=field):
                source = _load_input()
                source["linked_context"][0][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_handoff_package_contents_preview_summary(source)

    def test_duplicate_packaged_paths_are_rejected(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][1]["package_path"] = (
            "measurements/measurement-1001/primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "duplicate package_path"):
            build_handoff_package_contents_preview_summary(source)

    def test_linked_context_duplicate_packaged_paths_are_rejected(self) -> None:
        source = _load_input()
        source["linked_context"][1]["package_path"] = "context/session-wiring-note.md"
        source["linked_context"][1]["include_status"] = "included_by_user"
        source["linked_context"][1]["package_state"] = "packaged"
        source["linked_context"][1]["reason"] = None

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

    def test_primary_data_package_path_must_use_current_topology(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["package_path"] = (
            "measurements/measurement-1001/nested/primary.csv"
        )
        source["selected_measurements"][0]["default_bundle"][0]["package_path"] = (
            "measurements/measurement-1001/nested/primary.csv"
        )
        source["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][0][
            "source"
        ] = "measurements/measurement-1001/nested/primary.csv"
        source["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][1][
            "source"
        ] = "measurements/measurement-1001/nested/primary.csv"

        with self.assertRaisesRegex(ValueError, "primary data package_path"):
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

        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][1]["package_path"] = (
            "measurements/measurement-1001/./parameter-snapshot.json"
        )

        with self.assertRaisesRegex(ValueError, "path must be relative"):
            build_handoff_package_contents_preview_summary(source)

    def test_non_primary_packaged_paths_use_declared_topology(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][1]["package_path"] = (
            "misc/free-layout.json"
        )

        with self.assertRaisesRegex(ValueError, "must stay under measurements/measurement-1001"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["linked_context"][0]["package_path"] = "misc/free-context.md"

        with self.assertRaisesRegex(ValueError, "must stay under context"):
            build_handoff_package_contents_preview_summary(source)

    def test_packaged_managed_paths_must_use_public_safe_segments(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][1]["package_path"] = (
            "measurements/measurement-1001/Users/lab/private-metadata.json"
        )

        with self.assertRaisesRegex(ValueError, "path segments"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["linked_context"][1]["package_path"] = "context/private/customer-params.md"
        source["linked_context"][1]["include_status"] = "included_by_user"
        source["linked_context"][1]["package_state"] = "packaged"
        source["linked_context"][1]["reason"] = None

        with self.assertRaisesRegex(ValueError, "path segments"):
            build_handoff_package_contents_preview_summary(source)

    def test_packaged_items_must_not_carry_reason(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][0]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        del source["selected_measurements"][0]["primary_data"]["reason"]

        with self.assertRaisesRegex(ValueError, "must not carry reason"):
            build_handoff_package_contents_preview_summary(source)

    def test_primary_data_literals_must_match_route_contract(self) -> None:
        invalid_cases = (
            ("kind", "metadata_blob", "primary_data kind"),
            ("include_status", "included_by_user", "primary_data include_status"),
            ("relation", "alternate_source", "primary_data relation"),
            ("authority", "user_declared", "authority"),
            ("format", "/Users/lab/private/format", "primary_data format"),
            ("package_state", "missing_from_package", "package_state"),
        )
        for field, value, message in invalid_cases:
            with self.subTest(field=field):
                source = _load_input()
                source["selected_measurements"][0]["primary_data"][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_handoff_package_contents_preview_summary(source)

    def test_default_primary_bundle_literals_must_match_primary_data(self) -> None:
        invalid_cases = (
            ("label", "Other primary data", "default bundle primary_data label"),
            ("include_status", "included_by_user", "default bundle primary_data include_status"),
            ("relation", "alternate_source", "default bundle primary_data relation"),
            ("authority", "user_declared", "authority"),
            ("package_state", "redacted", "package_state"),
        )
        for field, value, message in invalid_cases:
            with self.subTest(field=field):
                source = _load_input()
                source["selected_measurements"][0]["default_bundle"][0][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_handoff_package_contents_preview_summary(source)

    def test_primary_data_format_must_be_csv_table_for_message_stability(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["format"] = "/Users/lab/private/format"

        with self.assertRaisesRegex(ValueError, "primary_data format"):
            build_handoff_package_contents_preview_summary(source)

    def test_declared_digest_and_size_are_validated_when_present(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["digest"] = "sha256:" + "0" * 64
        source["selected_measurements"][0]["primary_data"]["size_bytes"] = 123

        summary = build_handoff_package_contents_preview_summary(source)

        self.assertEqual(
            summary["selected_measurements"][0]["primary_data"]["digest"],
            "sha256:" + "0" * 64,
        )
        self.assertEqual(summary["selected_measurements"][0]["primary_data"]["size_bytes"], 123)

        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["digest"] = "/Users/lab/private/digest"
        source["selected_measurements"][0]["primary_data"]["size_bytes"] = 123
        with self.assertRaisesRegex(ValueError, "primary data digest"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["digest"] = "sha256:" + "0" * 64
        source["selected_measurements"][0]["primary_data"]["size_bytes"] = 0
        with self.assertRaisesRegex(ValueError, "primary data size_bytes"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "declared together"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["size_bytes"] = 123
        with self.assertRaisesRegex(ValueError, "declared together"):
            build_handoff_package_contents_preview_summary(source)

    def test_display_path_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["package_identity"]["display_path"] = (
            "/" + "Users" + "/example/lab/private/package.zip"
        )

        with self.assertRaisesRegex(ValueError, "display_path"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["package_identity"]["display_path"] = "HANDOFF_PACKAGE:/redacted/C:/lab-package"

        with self.assertRaisesRegex(ValueError, "display_path"):
            build_handoff_package_contents_preview_summary(source)

    def test_managed_package_identity_fields_are_validated(self) -> None:
        invalid_cases = (
            ("package_id", "/Users/lab/private/package", "package_id"),
            (
                "source_export_summary_id",
                "/Users/lab/private/export",
                "source_export_summary_id",
            ),
            ("display_name", {"text": "qA selected measurement handoff"}, "display_name"),
        )
        for field, value, message in invalid_cases:
            with self.subTest(field=field):
                source = _load_input()
                source["package_identity"][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_handoff_package_contents_preview_summary(source)

    def test_display_path_is_optional_for_portable_writer_manifest(self) -> None:
        source = _load_input()
        del source["package_identity"]["display_path"]

        summary = build_handoff_package_contents_preview_summary(source)

        self.assertNotIn("display_path", summary["package"])
        self.assertEqual(summary["package"]["package_id"], "handoff-package-qA-2026-05")
        self.assertEqual(summary["package"]["classification"], "needs_review_before_acceptance")
        findings = {item["finding"] for item in summary["preview_findings"]}
        self.assertIn("preview_metadata_missing", findings)
        self.assertIn("linked_context_not_packaged_visible_reference", findings)

    def test_non_packaged_context_requires_reason(self) -> None:
        source = _load_input()
        source["linked_context"][1]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_handoff_package_contents_preview_summary(source)

        source = _load_input()
        source["linked_context"][1]["reason"] = {"text": "Visible but not packaged"}

        with self.assertRaisesRegex(ValueError, "reason"):
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

    def test_preview_schema_binding_names_are_public_identifiers(self) -> None:
        invalid_cases = (
            (
                ("declared_columns", 0, "name"),
                "/Users/lab/private/drive",
                "preview column name",
            ),
            (
                ("declared_columns", 0, "role"),
                "/Users/lab/private/role",
                "preview column role",
            ),
            (
                ("declared_columns", 0, "unit"),
                "/Users/lab/private/unit",
                "preview column unit",
            ),
            (("data_shape", "kind"), "/Users/lab/private/shape", "preview shape kind"),
            (("data_shape", "axis_order", 0), "/Users/lab/private/axis", "preview axis"),
            (("plot_candidates", 0, "x"), "/Users/lab/private/x", "plot x"),
        )
        for path, value, message in invalid_cases:
            with self.subTest(path=path):
                source = _load_input()
                target = source["selected_measurements"][0]["declared_preview_metadata"]
                for segment in path[:-1]:
                    target = target[segment]
                target[path[-1]] = value

                with self.assertRaisesRegex(ValueError, message):
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

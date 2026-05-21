import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "selected_run_handoff" / "preview_ready_measurement_export"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_bundle_paths(summary: dict) -> list[str]:
    return [
        item["path"]
        for measurement in summary["measurements"]
        for item in measurement["default_bundle"]
    ]


def _linked_paths_by_status(summary: dict, include_status: str) -> list[str]:
    return [
        item["path"]
        for item in summary["linked_context"]
        if item["include_status"] == include_status
    ]


class PreviewReadyMeasurementExportFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "export-input.json",
            FIXTURE / "expected-export-summary.json",
            FIXTURE / "snapshots" / "measurement-1001-parameter-snapshot.json",
            FIXTURE / "snapshots" / "measurement-1002-parameter-snapshot.json",
        ]:
            with self.subTest(path=path):
                _load_json(path)

    def test_expected_summary_integrates_export_and_preview_readiness(self) -> None:
        wrapped_summary = _load_json(FIXTURE / "expected-export-summary.json")
        summary = wrapped_summary["candidate_summary"]
        measurements = {
            measurement["legacy_data_id"]: measurement for measurement in summary["measurements"]
        }

        self.assertEqual(
            summary["selected_export_set"]["selected_legacy_data_ids"],
            [1001, 1002],
        )
        self.assertEqual(
            wrapped_summary["reference_semantics"]["status"],
            "fixture_paths_are_package_relative",
        )
        self.assertIn(
            "not a final package format",
            wrapped_summary["reference_semantics"]["contract_guard"],
        )
        self.assertEqual(
            measurements[1001]["preview"]["status"],
            "preview_ready",
        )
        self.assertEqual(
            measurements[1001]["export_source"],
            "LAB_LOCAL:/redacted/datavault/export-demo-session/measurement-1001-rabi-source.csv",
        )
        self.assertEqual(measurements[1001]["primary_data_authority"], "source_metadata")
        self.assertEqual(
            measurements[1001]["preview"]["shape_kind"],
            "1d_multi_response_table",
        )
        self.assertEqual(
            [candidate["y"] for candidate in measurements[1001]["preview"]["plot_candidates"]],
            ["iq_i", "iq_q"],
        )
        self.assertEqual(
            measurements[1002]["preview"]["status"],
            "degraded_preview",
        )
        self.assertEqual(
            measurements[1002]["export_source"],
            "LAB_LOCAL:/redacted/datavault/export-demo-session/measurement-1002-t1-source.csv",
        )
        self.assertEqual(measurements[1002]["primary_data_authority"], "source_metadata")
        self.assertEqual(measurements[1002]["preview"]["plot_candidates"], [])
        self.assertEqual(
            measurements[1002]["preview"]["warnings"][0]["code"],
            "preview_metadata_missing",
        )

    def test_declared_warning_codes_match_emitted_warning_codes(self) -> None:
        source = _load_json(FIXTURE / "export-input.json")
        summary = _load_json(FIXTURE / "expected-export-summary.json")
        summary = summary["candidate_summary"]

        self.assertEqual(
            source["warnings_expected"],
            list(dict.fromkeys(warning["code"] for warning in summary["warnings"])),
        )

    def test_preview_metadata_missing_does_not_block_export(self) -> None:
        summary = _load_json(FIXTURE / "expected-export-summary.json")
        summary = summary["candidate_summary"]
        default_bundle_paths = _default_bundle_paths(summary)

        self.assertIn(
            "source/export-demo-session/measurement-1002-t1-source.csv",
            default_bundle_paths,
        )
        self.assertIn(
            "snapshots/measurement-1002-parameter-snapshot.json",
            default_bundle_paths,
        )
        self.assertIn(
            "preview_metadata_missing",
            [warning["code"] for warning in summary["warnings"]],
        )

    def test_degraded_preview_does_not_infer_roles_from_csv_headers(self) -> None:
        summary = _load_json(FIXTURE / "expected-export-summary.json")
        summary = summary["candidate_summary"]
        measurements = {
            measurement["legacy_data_id"]: measurement for measurement in summary["measurements"]
        }
        source_path = FIXTURE / "source" / "export-demo-session" / "measurement-1002-t1-source.csv"
        with source_path.open(newline="", encoding="utf-8") as handle:
            fieldnames = list(csv.DictReader(handle).fieldnames or [])

        self.assertEqual(fieldnames, ["delay_us", "p_excited", "bias_v"])
        self.assertEqual(measurements[1002]["preview"]["declared_roles"], [])
        self.assertEqual(measurements[1002]["preview"]["plot_candidates"], [])
        self.assertEqual(
            measurements[1002]["preview"]["warnings"][0]["code"],
            "preview_metadata_missing",
        )

    def test_optional_linked_files_have_distinct_inclusion_states(self) -> None:
        summary = _load_json(FIXTURE / "expected-export-summary.json")
        summary = summary["candidate_summary"]
        linked_context = {item["path"]: item for item in summary["linked_context"]}

        included_path = "attachments/export-session-wiring-note.md"
        excluded_path = "artifacts/optional-two-measurement-summary.csv"
        missing_path = "attachments/measurement-1002-fit-note.md"

        self.assertIn(included_path, _linked_paths_by_status(summary, "included_by_user"))
        self.assertIn(
            excluded_path,
            _linked_paths_by_status(summary, "visible_excluded"),
        )
        self.assertIn(missing_path, _linked_paths_by_status(summary, "missing"))
        self.assertEqual(linked_context[included_path]["include_status"], "included_by_user")
        self.assertEqual(linked_context[excluded_path]["include_status"], "visible_excluded")
        self.assertEqual(linked_context[missing_path]["include_status"], "missing")
        self.assertNotIn(
            "visible_optional_link_excluded",
            [warning["code"] for warning in summary["warnings"]],
        )

    def test_source_transform_posture_is_per_selected_measurement(self) -> None:
        source = _load_json(FIXTURE / "export-input.json")
        summary = _load_json(FIXTURE / "expected-export-summary.json")
        summary = summary["candidate_summary"]

        self.assertEqual(
            [
                measurement["source_transform_expectation"]["policy"]
                for measurement in source["measurements"]
            ],
            ["no_silent_transform", "no_silent_transform"],
        )
        self.assertEqual(
            {
                measurement["legacy_data_id"]: measurement["source_transform_policy"]
                for measurement in summary["measurements"]
            },
            {
                1001: "no_silent_transform",
                1002: "no_silent_transform",
            },
        )

    def test_expected_openability_matches_fixture_files(self) -> None:
        summary = _load_json(FIXTURE / "expected-export-summary.json")
        summary = summary["candidate_summary"]

        present_paths = (
            _default_bundle_paths(summary)
            + _linked_paths_by_status(summary, "included_by_user")
            + _linked_paths_by_status(summary, "visible_excluded")
        )
        for rel_path in present_paths:
            with self.subTest(rel_path=rel_path):
                self.assertTrue((FIXTURE / rel_path).exists())

        for rel_path in _linked_paths_by_status(summary, "missing"):
            with self.subTest(rel_path=rel_path):
                self.assertFalse((FIXTURE / rel_path).exists())

    def test_review_states_preview_ready_boundary(self) -> None:
        review = (FIXTURE / "expected-export-review.md").read_text(encoding="utf-8")

        self.assertIn("selected measurements: `1001`, `1002`", review)
        self.assertIn("User-Included Optional Context", review)
        self.assertIn("Visible But Excluded Optional Context", review)
        self.assertIn("`1001` | `preview_ready`", review)
        self.assertIn("`1002` | `degraded_preview`", review)
        self.assertIn("does not block export", review)
        self.assertIn("non-recursive traversal is represented", review)
        self.assertIn("not claiming a downstream analysis DAG", review)
        self.assertIn("normal source data handling is represented", review)
        warnings_section = review.split("## Warnings", 1)[1].split("## Boundary Notes", 1)[0]
        self.assertNotIn("no_silent_transform", warnings_section)
        self.assertNotIn("not_scientific_validation", warnings_section)


if __name__ == "__main__":
    unittest.main()

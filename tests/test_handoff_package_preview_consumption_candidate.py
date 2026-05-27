from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_preview_consumption import (
    build_handoff_package_preview_consumption_summary,
)
from implementation_candidates.handoff_package_preview_consumption import (
    summary as consumption_summary,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict) -> None:
    (package_dir / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _assert_no_path_leak(test_case: unittest.TestCase, summary: dict, path: Path) -> None:
    serialized = json.dumps(summary, sort_keys=True)
    test_case.assertNotIn(str(path), serialized)
    test_case.assertNotIn(str(path.resolve()), serialized)


def _assert_summary_shape(test_case: unittest.TestCase, summary: dict) -> None:
    test_case.assertEqual(
        set(summary),
        {
            "artifact_posture",
            "attention",
            "measurements",
            "package",
            "preview_consumption_policy",
            "preview_shape_view",
            "read_view",
            "visual_review",
        },
    )
    test_case.assertEqual(
        set(summary["package"]),
        {
            "display_name",
            "first_surface_counts",
            "measurement_count",
            "package_id",
            "preview_classification",
        },
    )
    for measurement in summary["measurements"]:
        test_case.assertEqual(
            set(measurement),
            {
                "declared_preview",
                "finding_codes",
                "first_surface",
                "label",
                "linked_context_count",
                "measurement_record_id",
                "table_access",
                "visual_review",
            },
        )
        test_case.assertEqual(
            set(measurement["table_access"]),
            {
                "dataframe_adapter",
                "preview_columns",
                "preview_row_count",
                "primary_columns",
                "primary_row_count",
            },
        )


def _add_second_measurement_without_plot(package_dir: Path) -> None:
    manifest = _manifest(package_dir)
    source = manifest["selected_measurements"][0]
    measurement = copy.deepcopy(source)
    measurement["measurement_record_id"] = "legacy-rabi-002"
    measurement["legacy_data_id"] = 1002
    measurement["label"] = "Rabi calibration follow-up without plot"
    measurement["primary_data"]["package_path"] = "measurements/legacy-rabi-002/primary.csv"
    measurement["declared_preview_metadata"]["plot_candidates"] = []
    measurement["default_bundle"][0]["item_id"] = "legacy-rabi-002-primary"
    measurement["default_bundle"][0]["package_path"] = "measurements/legacy-rabi-002/primary.csv"
    manifest["selected_measurements"].append(measurement)
    manifest["linked_context"][0]["linked_measurement_record_ids"].append("legacy-rabi-002")
    target_dir = package_dir / "measurements" / "legacy-rabi-002"
    target_dir.mkdir()
    shutil.copyfile(
        package_dir / "measurements" / "legacy-rabi-001" / "primary.csv",
        target_dir / "primary.csv",
    )
    _write_manifest(package_dir, manifest)


class HandoffPackagePreviewConsumptionCandidateTest(unittest.TestCase):
    def test_composes_preview_shape_and_visual_review_for_first_use(self) -> None:
        summary = build_handoff_package_preview_consumption_summary(PACKAGE)
        measurement = summary["measurements"][0]
        expected_policy = {
            "archive_handling": "not_performed",
            "composition_authority": "read_only_handoff_package_read_view",
            "dataframe_adapter": "not_invoked",
            "first_surface_selection": "composed_projection_facts",
            "interactive_gui": "not_defined",
            "package_acceptance": "not_performed",
            "package_integrity": "not_claimed",
            "package_open": "performed_via_handoff_package_read_view",
            "plot_rendering": "not_performed",
            "preview_shape_projection": "performed",
            "scan_shape_inference": "not_performed",
            "schema_inference": "not_performed",
            "sdk_adapter": "not_invoked",
            "shared_measurement_schema": "not_defined",
            "storage_import": "not_performed",
            "table_drilldown": "projected_as_summary_facts",
            "visual_review_projection": "performed",
        }

        self.assertEqual(summary["artifact_posture"], "review_summary")
        self.assertEqual(summary, build_handoff_package_preview_consumption_summary(PACKAGE))
        _assert_summary_shape(self, summary)
        self.assertEqual(summary["preview_consumption_policy"], expected_policy)
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["package"]["measurement_count"], 1)
        self.assertEqual(
            summary["package"]["first_surface_counts"],
            {
                "plot_first_visual_review": 1,
                "review_findings": 0,
                "table_drilldown": 0,
            },
        )

        self.assertEqual(summary["read_view"]["measurement_ids"], ["legacy-rabi-001"])
        self.assertEqual(summary["read_view"]["linked_context_count"], 1)
        self.assertEqual(summary["preview_shape_view"]["measurement_ids"], ["legacy-rabi-001"])
        self.assertEqual(summary["visual_review"]["visual_summary_count"], 1)
        self.assertEqual(summary["visual_review"]["measurement_index_count"], 1)
        self.assertEqual(
            summary["attention"][1]["code"],
            "first_surface_selection_uses_composed_projection_facts",
        )

        self.assertEqual(measurement["measurement_record_id"], "legacy-rabi-001")
        self.assertEqual(measurement["first_surface"]["surface"], "plot_first_visual_review")
        self.assertEqual(
            measurement["first_surface"]["basis"],
            "declared_plot_candidate_projected_to_visual_summary",
        )
        self.assertEqual(measurement["declared_preview"]["kind"], "declared_1d_table")
        self.assertEqual(measurement["declared_preview"]["preview_affordance"], "xy_series")
        self.assertEqual(
            measurement["declared_preview"]["status"],
            "declared_preview_affordance_ready",
        )
        self.assertEqual(measurement["declared_preview"]["plot_candidate_count"], 1)
        self.assertEqual(measurement["declared_preview"]["schema_inference"], "not_performed")
        self.assertEqual(measurement["declared_preview"]["file_observation"], "not_performed")
        self.assertEqual(
            measurement["visual_review"]["visual_summary_ids"],
            ["legacy-rabi-001-visual-1"],
        )
        self.assertEqual(measurement["visual_review"]["plot_kinds"], ["declared_xy_series"])
        self.assertEqual(measurement["visual_review"]["plot_rendering"], "not_performed")
        self.assertEqual(
            measurement["table_access"]["primary_columns"],
            ["drive_frequency", "signal"],
        )
        self.assertEqual(measurement["table_access"]["primary_row_count"], 5)
        self.assertEqual(
            measurement["table_access"]["preview_columns"],
            ["drive_frequency", "signal"],
        )
        self.assertEqual(measurement["table_access"]["preview_row_count"], 5)
        self.assertEqual(measurement["table_access"]["dataframe_adapter"], "not_defined")

    def test_no_declared_plot_candidate_routes_to_table_drilldown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"][
                "plot_candidates"
            ] = []
            _write_manifest(package_dir, manifest)

            summary = build_handoff_package_preview_consumption_summary(package_dir)
            measurement = summary["measurements"][0]
            _assert_no_path_leak(self, summary, Path(temp_dir))
            _assert_no_path_leak(self, summary, package_dir)

        self.assertEqual(measurement["first_surface"]["surface"], "table_drilldown")
        self.assertEqual(measurement["declared_preview"]["plot_candidate_count"], 0)
        self.assertEqual(measurement["visual_review"]["visual_summary_ids"], [])
        self.assertEqual(
            summary["package"]["first_surface_counts"],
            {
                "plot_first_visual_review": 0,
                "review_findings": 0,
                "table_drilldown": 1,
            },
        )

    def test_preview_shape_review_finding_routes_to_review_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"]["data_shape"][
                "kind"
            ] = "unsupported_preview_shape"
            _write_manifest(package_dir, manifest)

            summary = build_handoff_package_preview_consumption_summary(package_dir)
            measurement = summary["measurements"][0]
            _assert_no_path_leak(self, summary, Path(temp_dir))
            _assert_no_path_leak(self, summary, package_dir)

        self.assertEqual(measurement["first_surface"]["surface"], "review_findings")
        self.assertEqual(
            measurement["declared_preview"]["status"],
            "unsupported_preview_affordance",
        )
        self.assertEqual(
            measurement["declared_preview"]["finding_codes"],
            ["declared_preview_affordance_unsupported"],
        )
        self.assertEqual(
            summary["package"]["first_surface_counts"],
            {
                "plot_first_visual_review": 0,
                "review_findings": 1,
                "table_drilldown": 0,
            },
        )

    def test_mismatched_declared_plot_kind_routes_to_review_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][0][
                "plot_kind"
            ] = "heatmap_grid"
            _write_manifest(package_dir, manifest)

            summary = build_handoff_package_preview_consumption_summary(package_dir)
            measurement = summary["measurements"][0]

        self.assertEqual(measurement["first_surface"]["surface"], "review_findings")
        self.assertEqual(
            measurement["declared_preview"]["finding_codes"],
            ["declared_preview_plot_kind_mismatch"],
        )

    def test_multiple_plot_candidates_keep_visual_summary_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"][
                "plot_candidates"
            ].append(
                {
                    "source": "measurements/legacy-rabi-001/primary.csv",
                    "x": "drive_frequency",
                    "y": "signal",
                }
            )
            _write_manifest(package_dir, manifest)

            summary = build_handoff_package_preview_consumption_summary(package_dir)
            measurement = summary["measurements"][0]

        self.assertEqual(
            measurement["visual_review"]["visual_summary_ids"],
            ["legacy-rabi-001-visual-1", "legacy-rabi-001-visual-2"],
        )
        self.assertEqual(
            measurement["visual_review"]["plot_kinds"],
            ["declared_xy_series", "declared_xy_series"],
        )
        self.assertEqual(
            summary["package"]["first_surface_counts"],
            {
                "plot_first_visual_review": 1,
                "review_findings": 0,
                "table_drilldown": 0,
            },
        )

    def test_multi_measurement_summary_counts_first_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            _add_second_measurement_without_plot(package_dir)

            summary = build_handoff_package_preview_consumption_summary(package_dir)
            _assert_no_path_leak(self, summary, Path(temp_dir))
            _assert_no_path_leak(self, summary, package_dir)

        self.assertEqual(summary["package"]["measurement_count"], 2)
        self.assertEqual(
            summary["read_view"]["measurement_ids"], ["legacy-rabi-001", "legacy-rabi-002"]
        )
        self.assertEqual(
            [measurement["first_surface"]["surface"] for measurement in summary["measurements"]],
            ["plot_first_visual_review", "table_drilldown"],
        )
        self.assertEqual(
            summary["package"]["first_surface_counts"],
            {
                "plot_first_visual_review": 1,
                "review_findings": 0,
                "table_drilldown": 1,
            },
        )

    def test_invalid_package_stops_before_composition(self) -> None:
        with self.assertRaisesRegex(ValueError, "existing package directory"):
            build_handoff_package_preview_consumption_summary(PACKAGE.parent / "missing")

    def test_package_like_missing_manifest_stops_before_composition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "handoff-package-missing-manifest"
            package_dir.mkdir()

            with self.assertRaisesRegex(ValueError, "manifest.*unavailable"):
                build_handoff_package_preview_consumption_summary(package_dir)

    def test_degraded_preview_metadata_stops_before_composition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"]["status"] = (
                "preview_degraded"
            )
            _write_manifest(package_dir, manifest)

            with self.assertRaisesRegex(ValueError, "unsupported preview status"):
                build_handoff_package_preview_consumption_summary(package_dir)

    def test_composition_alignment_validation_reports_missing_measurement_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "aligned visual-review measurement ids"):
            consumption_summary._validate_visual_alignment(
                preview_measurement_ids=("legacy-rabi-001",),
                visual_index={},
                visual_summaries={},
            )

    def test_composition_alignment_validation_reports_missing_visual_summary_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "visual summary ids to resolve"):
            consumption_summary._validate_visual_alignment(
                preview_measurement_ids=("legacy-rabi-001",),
                visual_index={
                    "legacy-rabi-001": {
                        "measurement_record_id": "legacy-rabi-001",
                        "visual_summary_ids": ["missing-visual"],
                        "table_drilldown": {
                            "primary_table": {"columns": [], "row_count": 0},
                            "preview_table": {"columns": [], "row_count": 0},
                            "dataframe_adapter": "not_defined",
                        },
                        "attention_items": [],
                        "finding_codes": [],
                        "linked_context_count": 0,
                    },
                },
                visual_summaries={},
            )

    def test_composition_alignment_validation_reports_cross_linked_visual_summaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "visual summaries to match"):
            consumption_summary._validate_visual_alignment(
                preview_measurement_ids=("legacy-rabi-001", "legacy-rabi-002"),
                visual_index={
                    "legacy-rabi-001": {
                        "measurement_record_id": "legacy-rabi-001",
                        "visual_summary_ids": ["legacy-rabi-002-visual-1"],
                        "table_drilldown": {
                            "primary_table": {"columns": [], "row_count": 0},
                            "preview_table": {"columns": [], "row_count": 0},
                            "dataframe_adapter": "not_defined",
                        },
                        "attention_items": [],
                        "finding_codes": [],
                        "linked_context_count": 0,
                    },
                    "legacy-rabi-002": {
                        "measurement_record_id": "legacy-rabi-002",
                        "visual_summary_ids": [],
                        "table_drilldown": {
                            "primary_table": {"columns": [], "row_count": 0},
                            "preview_table": {"columns": [], "row_count": 0},
                            "dataframe_adapter": "not_defined",
                        },
                        "attention_items": [],
                        "finding_codes": [],
                        "linked_context_count": 0,
                    },
                },
                visual_summaries={
                    "legacy-rabi-002-visual-1": {
                        "visual_summary_id": "legacy-rabi-002-visual-1",
                        "measurement_record_id": "legacy-rabi-002",
                        "plot": {"kind": "declared_xy_series"},
                    }
                },
            )

    def test_visual_model_shape_validation_reports_missing_required_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "visual_summary_ids"):
            consumption_summary._validate_visual_alignment(
                preview_measurement_ids=("legacy-rabi-001",),
                visual_index={
                    "legacy-rabi-001": {
                        "measurement_record_id": "legacy-rabi-001",
                    },
                },
                visual_summaries={},
            )
        with self.assertRaisesRegex(ValueError, "table_drilldown"):
            consumption_summary._validate_visual_alignment(
                preview_measurement_ids=("legacy-rabi-001",),
                visual_index={
                    "legacy-rabi-001": {
                        "measurement_record_id": "legacy-rabi-001",
                        "visual_summary_ids": [],
                    },
                },
                visual_summaries={},
            )
        with self.assertRaisesRegex(ValueError, "plot.kind"):
            consumption_summary._visual_summaries_by_id(
                {
                    "visual_summaries": [
                        {
                            "visual_summary_id": "legacy-rabi-001-visual-1",
                            "measurement_record_id": "legacy-rabi-001",
                            "plot": {},
                        }
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_read_view import (
    HandoffPackageReadView,
    HandoffPlotSeries,
    HandoffTable,
    open_handoff_package_view,
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


def _copy_package(temp_dir: str) -> Path:
    destination = Path(temp_dir) / PACKAGE.name
    shutil.copytree(PACKAGE, destination)
    return destination


def _load_manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict) -> None:
    (package_dir / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class HandoffPackageReadViewCandidateTest(unittest.TestCase):
    def test_reader_can_find_measurements_without_knowing_summary_shape(self) -> None:
        package = open_handoff_package_view(PACKAGE)

        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))

        measurement = package.measurement("legacy-rabi-001")
        self.assertEqual(measurement.label, "Rabi calibration follow-up")
        self.assertEqual(measurement.experiment_type, "rabi")
        self.assertEqual(measurement.target, "qA")

    def test_reader_gets_table_like_primary_data_without_dataframe_dependency(self) -> None:
        measurement = open_handoff_package_view(PACKAGE).measurement("legacy-rabi-001")

        table = measurement.primary_table()

        self.assertEqual(table.columns, ("drive_frequency", "signal"))
        self.assertEqual(table.row_count, 5)
        self.assertEqual(table.row(2), {"drive_frequency": "5.02", "signal": "0.81"})
        self.assertEqual(table.column("signal"), ("0.12", "0.44", "0.81", "0.45", "0.13"))
        self.assertEqual(
            table.to_records()[-1],
            {"drive_frequency": "5.06", "signal": "0.13"},
        )

    def test_reader_gets_declared_preview_table_separately_from_primary_table(self) -> None:
        measurement = open_handoff_package_view(PACKAGE).measurement("legacy-rabi-001")

        preview_table = measurement.preview_table()

        self.assertEqual(preview_table.columns, ("drive_frequency", "signal"))
        self.assertEqual(preview_table.row_count, 5)
        self.assertEqual(
            list(preview_table)[0],
            {"drive_frequency": "4.98", "signal": "0.12"},
        )

    def test_primary_table_can_include_columns_outside_declared_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal,temperature_mk\n4.98,0.12,10\n5.00,0.44,10\n",
                encoding="utf-8",
            )

            measurement = open_handoff_package_view(package_dir).measurement("legacy-rabi-001")

        self.assertEqual(
            measurement.primary_table().columns,
            ("drive_frequency", "signal", "temperature_mk"),
        )
        self.assertEqual(measurement.preview_table().columns, ("drive_frequency", "signal"))
        self.assertEqual(measurement.preview_table().row_count, 2)

    def test_reader_gets_declared_plot_series_by_columns(self) -> None:
        measurement = open_handoff_package_view(PACKAGE).measurement("legacy-rabi-001")

        series = measurement.plot_series_by_columns(x="drive_frequency", y="signal")

        self.assertEqual(series.source, "measurements/legacy-rabi-001/primary.csv")
        self.assertEqual(series.x_name, "drive_frequency")
        self.assertEqual(series.y_name, "signal")
        self.assertEqual(series.x, ("4.98", "5.00", "5.02", "5.04", "5.06"))
        self.assertEqual(series.y, ("0.12", "0.44", "0.81", "0.45", "0.13"))

    def test_plot_series_points_are_copy_safe(self) -> None:
        measurement = open_handoff_package_view(PACKAGE).measurement("legacy-rabi-001")
        series = measurement.plot_series_by_columns(x="drive_frequency", y="signal")

        points = series.points
        points[0]["x"] = "mutated"

        self.assertEqual(series.x[0], "4.98")
        self.assertEqual(series.points[0]["x"], "4.98")
        self.assertEqual(series.to_records()[0]["x"], "4.98")

    def test_plot_series_rejects_inconsistent_points(self) -> None:
        with self.assertRaisesRegex(ValueError, "points must have x and y"):
            HandoffPlotSeries.from_points(
                source="measurements/legacy-rabi-001/primary.csv",
                x_name="drive_frequency",
                y_name="signal",
                points=[{"x": "5.00"}],
            )

        with self.assertRaisesRegex(ValueError, "point values must be strings"):
            HandoffPlotSeries.from_points(
                source="measurements/legacy-rabi-001/primary.csv",
                x_name="drive_frequency",
                y_name="signal",
                points=[{"x": "5.00", "y": 0.44}],
            )

        with self.assertRaisesRegex(ValueError, "point values must be strings"):
            HandoffPlotSeries(
                source="measurements/legacy-rabi-001/primary.csv",
                x_name="drive_frequency",
                y_name="signal",
                _points=(("5.00", 0.44),),
            )

    def test_reader_keeps_findings_and_linked_context_visible(self) -> None:
        package = open_handoff_package_view(PACKAGE)
        measurement = package.measurement("legacy-rabi-001")

        self.assertEqual(
            package.preview_classification,
            "needs_review_before_acceptance",
        )
        self.assertEqual(
            package.findings[0]["finding"], "linked_context_not_packaged_visible_reference"
        )
        self.assertEqual(
            measurement.findings[0]["subject_id"],
            "package-legacy-001-parameter-snapshot",
        )
        self.assertEqual(measurement.linked_context[0]["materialization"], "reference_only")
        self.assertEqual(measurement.integrity_check, "not_performed")

    def test_reader_returns_copies_for_local_summary_facts(self) -> None:
        package = open_handoff_package_view(PACKAGE)

        findings = package.findings
        linked_context = package.linked_context
        summary = package.as_open_summary()
        findings[0]["finding"] = "mutated"
        linked_context[0]["materialization"] = "mutated"
        summary["package"]["package_id"] = "mutated"

        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(
            package.findings[0]["finding"], "linked_context_not_packaged_visible_reference"
        )
        self.assertEqual(package.linked_context[0]["materialization"], "reference_only")

    def test_reader_associates_shared_linked_context_findings_with_each_measurement(self) -> None:
        package = HandoffPackageReadView(
            {
                "package": {
                    "package_id": "handoff-package-shared-context",
                    "display_name": "Shared context package",
                    "preview_classification": "needs_review_before_acceptance",
                },
                "selected_measurements": [
                    {"measurement_record_id": "measurement-001"},
                    {"measurement_record_id": "measurement-002"},
                ],
                "linked_context": [
                    {
                        "link_id": "shared-context-001",
                        "linked_measurement_record_ids": [
                            "measurement-001",
                            "measurement-002",
                        ],
                    }
                ],
                "manifest_preview_findings": [
                    {
                        "finding": "linked_context_not_packaged_visible_reference",
                        "measurement_record_id": "measurement-001",
                        "subject_type": "linked_context",
                        "subject_id": "shared-context-001",
                    }
                ],
                "attention": [],
            }
        )

        self.assertEqual(
            package.measurement("measurement-002").findings[0]["subject_id"],
            "shared-context-001",
        )

    def test_reader_does_not_associate_non_context_finding_by_id_collision(self) -> None:
        package = HandoffPackageReadView(
            {
                "package": {
                    "package_id": "handoff-package-shared-context",
                    "display_name": "Shared context package",
                    "preview_classification": "needs_review_before_acceptance",
                },
                "selected_measurements": [
                    {"measurement_record_id": "measurement-001"},
                    {"measurement_record_id": "measurement-002"},
                ],
                "linked_context": [
                    {
                        "link_id": "shared-id",
                        "linked_measurement_record_ids": [
                            "measurement-002",
                        ],
                    }
                ],
                "manifest_preview_findings": [
                    {
                        "finding": "artifact_review",
                        "measurement_record_id": "measurement-001",
                        "subject_type": "artifact",
                        "subject_id": "shared-id",
                    }
                ],
                "attention": [],
            }
        )

        self.assertEqual(package.measurement("measurement-002").findings, ())

    def test_missing_measurement_or_column_is_reported_as_lookup_error(self) -> None:
        package = open_handoff_package_view(PACKAGE)

        with self.assertRaises(KeyError):
            package.measurement("missing-record")

        with self.assertRaises(KeyError):
            package.measurement("legacy-rabi-001").primary_table().column("missing_column")

        with self.assertRaises(KeyError):
            package.measurement("legacy-rabi-001").plot_series_by_columns(
                x="drive_frequency",
                y="missing_signal",
            )

    def test_table_like_object_rejects_inconsistent_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires unique columns"):
            HandoffTable.from_records(
                ["drive_frequency", "drive_frequency"],
                [{"drive_frequency": "5.00"}],
            )

        with self.assertRaisesRegex(ValueError, "rows must match columns"):
            HandoffTable.from_records(
                ["drive_frequency", "signal"],
                [{"drive_frequency": "5.00"}],
            )

        with self.assertRaisesRegex(ValueError, "row values must be strings"):
            HandoffTable.from_records(
                ["drive_frequency", "signal"],
                [{"drive_frequency": "5.00", "signal": 0.44}],
            )

        with self.assertRaisesRegex(ValueError, "rows must match columns"):
            HandoffTable(
                columns=("drive_frequency", "signal"),
                _rows=(("5.00",),),
            )

    def test_optional_digest_and_size_absence_still_opens_through_read_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            primary = manifest["selected_measurements"][0]["primary_data"]
            del primary["digest"]
            del primary["size_bytes"]
            _write_manifest(package_dir, manifest)

            measurement = open_handoff_package_view(package_dir).measurement("legacy-rabi-001")

        self.assertEqual(measurement.primary_table().row_count, 5)
        self.assertEqual(measurement.integrity_check, "not_performed")

    def test_degraded_preview_rejection_propagates_through_read_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            preview = manifest["selected_measurements"][0]["declared_preview_metadata"]
            preview["status"] = "degraded_preview"
            preview["data_shape"] = None
            preview["declared_columns"] = []
            preview["plot_candidates"] = []
            preview["warning_code"] = "preview_metadata_missing"
            preview["message"] = "Declared preview metadata is not available."
            _write_manifest(package_dir, manifest)

            with self.assertRaisesRegex(ValueError, "requires preview_ready metadata"):
                open_handoff_package_view(package_dir)


if __name__ == "__main__":
    unittest.main()

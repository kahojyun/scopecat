from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import (
    HANDOFF_INSPECTION_ARTIFACT_NAME,
    HandoffPackage,
    HandoffPlotSeries,
    HandoffTable,
    open_package,
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
ROUTE_PRESSURE_ROOT = ROOT / "tests" / "fixtures" / "handoff_package_route_pressure"
RICHER_PACKAGE = (
    ROUTE_PRESSURE_ROOT
    / "richer_reader_package"
    / "package"
    / "handoff-package-reader-pressure-001"
)
DEGRADED_PACKAGE = (
    ROUTE_PRESSURE_ROOT
    / "degraded_preview_package"
    / "package"
    / "handoff-package-degraded-preview-001"
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


class HandoffEngineeringPrototypeReadOnlyTest(unittest.TestCase):
    def test_open_package_exposes_read_only_handoff_projection(self) -> None:
        package = open_package(PACKAGE)

        self.assertIsInstance(package, HandoffPackage)
        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(package.display_name, "Legacy Rabi selected measurement handoff")
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        self.assertEqual(package.preview_classification, "needs_review_before_acceptance")

        measurement = package.measurement("legacy-rabi-001")
        self.assertEqual(measurement.label, "Rabi calibration follow-up")
        self.assertEqual(measurement.experiment_type, "rabi")
        self.assertEqual(measurement.target, "qA")
        self.assertEqual(
            measurement.primary_package_path,
            "measurements/legacy-rabi-001/primary.csv",
        )
        self.assertEqual(measurement.integrity_check, "not_performed")

    def test_primary_table_and_declared_plot_series_are_available_without_dataframe(self) -> None:
        measurement = open_package(PACKAGE).measurement("legacy-rabi-001")

        table = measurement.primary_table
        series = measurement.plot_series_by_columns(x="drive_frequency", y="signal")

        self.assertIsInstance(table, HandoffTable)
        self.assertIsInstance(series, HandoffPlotSeries)
        self.assertEqual(table.columns, ("drive_frequency", "signal"))
        self.assertEqual(table.row_count, 5)
        self.assertEqual(table.row(2), {"drive_frequency": "5.02", "signal": "0.81"})
        self.assertEqual(table.column("signal"), ("0.12", "0.44", "0.81", "0.45", "0.13"))
        self.assertEqual(series.source, "measurements/legacy-rabi-001/primary.csv")
        self.assertEqual(series.x, ("4.98", "5.00", "5.02", "5.04", "5.06"))
        self.assertEqual(series.y, ("0.12", "0.44", "0.81", "0.45", "0.13"))

    def test_preview_table_is_declared_column_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal,temperature_mk\n4.98,0.12,10\n5.00,0.44,10\n",
                encoding="utf-8",
            )

            measurement = open_package(package_dir).measurement("legacy-rabi-001")

        self.assertEqual(
            measurement.primary_table.columns,
            ("drive_frequency", "signal", "temperature_mk"),
        )
        self.assertEqual(measurement.preview_table.columns, ("drive_frequency", "signal"))
        self.assertEqual(measurement.preview_table.row_count, 2)

    def test_linked_context_and_findings_remain_visible_but_reference_only(self) -> None:
        package = open_package(PACKAGE)
        measurement = package.measurement("legacy-rabi-001")

        self.assertEqual(package.linked_context[0]["materialization"], "reference_only")
        self.assertEqual(
            package.findings[0]["finding"],
            "linked_context_not_packaged_visible_reference",
        )
        self.assertEqual(measurement.linked_context[0]["materialization"], "reference_only")
        self.assertEqual(
            measurement.findings[0]["subject_id"],
            "package-legacy-001-parameter-snapshot",
        )
        self.assertEqual(
            package.attention[0]["does_not_claim"],
            "package_acceptance_or_import",
        )

    def test_projection_outputs_are_copy_safe(self) -> None:
        package = open_package(PACKAGE)
        measurement = package.measurement("legacy-rabi-001")

        package_summary = package.as_open_summary()
        package_findings = package.findings
        measurement_context = measurement.linked_context
        table_records = measurement.primary_table.to_records()
        plot_points = measurement.plot_series[0].points

        package_summary["package"]["package_id"] = "mutated"
        package_findings[0]["finding"] = "mutated"
        measurement_context[0]["materialization"] = "mutated"
        table_records[0]["signal"] = "mutated"
        plot_points[0]["y"] = "mutated"

        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(
            package.findings[0]["finding"],
            "linked_context_not_packaged_visible_reference",
        )
        self.assertEqual(measurement.linked_context[0]["materialization"], "reference_only")
        self.assertEqual(measurement.primary_table.row(0)["signal"], "0.12")
        self.assertEqual(measurement.plot_series[0].points[0]["y"], "0.12")

    def test_degraded_preview_rejects_open_before_primary_file_read(self) -> None:
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
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").unlink()

            with self.assertRaisesRegex(ValueError, "requires preview_ready metadata"):
                open_package(package_dir)

    def test_missing_measurement_id_raises_key_error(self) -> None:
        package = open_package(PACKAGE)

        with self.assertRaisesRegex(KeyError, "missing-measurement"):
            package.measurement("missing-measurement")

    def test_module_cli_prints_read_only_orientation_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "scopecat.handoff", str(PACKAGE)],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        summary = json.loads(result.stdout)

        self.assertEqual(summary["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["measurement_ids"], ["legacy-rabi-001"])
        self.assertEqual(summary["preview_classification"], "needs_review_before_acceptance")
        self.assertEqual(summary["finding_count"], 1)
        self.assertEqual(summary["linked_context_count"], 1)
        self.assertIsNone(summary["html_artifact"])

    def test_module_cli_can_write_local_html_inspection_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scopecat.handoff",
                    str(PACKAGE),
                    "--html-dir",
                    temp_dir,
                ],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            artifact_path = Path(temp_dir) / HANDOFF_INSPECTION_ARTIFACT_NAME
            html = artifact_path.read_text(encoding="utf-8")

        summary = json.loads(result.stdout)

        self.assertEqual(summary["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["html_artifact"]["filename"], HANDOFF_INSPECTION_ARTIFACT_NAME)
        self.assertEqual(summary["html_artifact"]["portable_package_member"], False)
        self.assertIn("Rabi calibration follow-up", html)

    def test_route_pressure_fixture_exposes_multi_plot_and_table_only_measurements(self) -> None:
        package = open_package(RICHER_PACKAGE)
        rabi = package.measurement("pressure-rabi-001")
        check = package.measurement("pressure-check-001")

        self.assertEqual(package.package_id, "handoff-package-reader-pressure-001")
        self.assertEqual(package.measurement_ids, ("pressure-rabi-001", "pressure-check-001"))
        self.assertEqual(rabi.primary_table.columns, ("drive_frequency", "signal", "residual"))
        self.assertEqual(len(rabi.plot_series), 2)
        self.assertEqual(
            rabi.plot_series_by_columns(x="drive_frequency", y="residual").y[2],
            "0.01",
        )
        self.assertEqual(check.primary_table.columns, ("delay", "contrast"))
        self.assertEqual(check.plot_series, ())
        self.assertEqual(check.preview_table.row_count, 4)

    def test_route_pressure_fixture_associates_shared_context_with_each_measurement(self) -> None:
        package = open_package(RICHER_PACKAGE)

        for measurement_id in ("pressure-rabi-001", "pressure-check-001"):
            measurement = package.measurement(measurement_id)
            self.assertEqual(
                measurement.linked_context[0]["link_id"],
                "pressure-shared-setup-snapshot",
            )
            self.assertEqual(
                measurement.findings[0]["subject_id"],
                "pressure-shared-setup-snapshot",
            )

    def test_degraded_route_pressure_package_remains_not_openable(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires preview_ready metadata"):
            open_package(DEGRADED_PACKAGE)


if __name__ == "__main__":
    unittest.main()

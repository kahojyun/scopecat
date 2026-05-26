from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from implementation_candidates.handoff_package_read_view import HandoffPlotSeries, HandoffTable
from implementation_candidates.handoff_package_sdk_view_model import (
    SdkColumn,
    SdkMeasurementCollection,
    SdkPlotCollection,
    SdkPlotSpec,
    SdkTable,
    open_handoff_package_sdk_view,
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


class _FakeFrame:
    def __init__(self, records: list[dict[str, str]], columns: list[str]) -> None:
        self.records = records
        self.columns = columns
        self.attrs: dict[str, object] = {}

    @classmethod
    def from_records(
        cls,
        records: list[dict[str, str]],
        *,
        columns: list[str],
    ) -> _FakeFrame:
        return cls(records, columns)


class _FakePandas:
    DataFrame = _FakeFrame


class _FakeNumpy:
    @staticmethod
    def asarray(values: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        return ("array", tuple(values))


def _copy_package(temp_dir: str) -> Path:
    destination = Path(temp_dir) / PACKAGE.name
    shutil.copytree(PACKAGE, destination)
    return destination


def _read_manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict) -> None:
    (package_dir / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class HandoffPackageSdkViewModelCandidateTest(unittest.TestCase):
    def test_package_and_measurement_support_id_and_position_lookup(self) -> None:
        package = open_handoff_package_sdk_view(PACKAGE)

        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        self.assertEqual(package["legacy-rabi-001"].label, "Rabi calibration follow-up")
        self.assertEqual(package[0].measurement_record_id, "legacy-rabi-001")
        self.assertEqual(package.measurements["legacy-rabi-001"].target, "qA")
        self.assertEqual(package.measurements[0].experiment_type, "rabi")
        with self.assertRaisesRegex(IndexError, "measurement position out of range"):
            _ = package.measurements[-1]

    def test_primary_table_uses_string_or_position_column_access(self) -> None:
        measurement = open_handoff_package_sdk_view(PACKAGE)["legacy-rabi-001"]

        table = measurement.primary

        self.assertEqual(table.column_names, ("drive_frequency", "signal"))
        self.assertEqual(table["drive_frequency"], ("4.98", "5.00", "5.02", "5.04", "5.06"))
        self.assertEqual(table[1], ("0.12", "0.44", "0.81", "0.45", "0.13"))
        self.assertEqual(table.columns[0].label, "Drive frequency")
        self.assertEqual(table.columns[0].unit, "GHz")
        self.assertEqual(table.row_count, 5)
        with self.assertRaisesRegex(IndexError, "column position out of range"):
            _ = table[-1]

    def test_preview_table_uses_same_table_surface_as_primary(self) -> None:
        measurement = open_handoff_package_sdk_view(PACKAGE)["legacy-rabi-001"]

        preview = measurement.preview
        frame = preview.to_pandas(pandas_module=_FakePandas)

        self.assertEqual(preview.column_names, ("drive_frequency", "signal"))
        self.assertEqual(preview[0], ("4.98", "5.00", "5.02", "5.04", "5.06"))
        self.assertEqual(preview["signal"], ("0.12", "0.44", "0.81", "0.45", "0.13"))
        self.assertEqual(preview.row(0), {"drive_frequency": "4.98", "signal": "0.12"})
        self.assertEqual(preview.to_records()[1], {"drive_frequency": "5.00", "signal": "0.44"})
        self.assertEqual(frame.attrs["scopecat"]["role"], "preview")
        self.assertEqual(frame.attrs["scopecat"]["columns"][0]["label"], "Drive frequency")

    def test_table_to_pandas_uses_column_names_and_attaches_metadata(self) -> None:
        measurement = open_handoff_package_sdk_view(PACKAGE)[0]

        frame = measurement.primary.to_pandas(pandas_module=_FakePandas)

        self.assertEqual(frame.columns, ["drive_frequency", "signal"])
        self.assertEqual(frame.records[2], {"drive_frequency": "5.02", "signal": "0.81"})
        self.assertEqual(frame.attrs["scopecat"]["role"], "primary")
        self.assertEqual(
            frame.attrs["scopecat"]["columns"][0],
            {
                "name": "drive_frequency",
                "label": "Drive frequency",
                "role": "sweep_axis",
                "unit": "GHz",
                "position": 0,
            },
        )

    def test_table_to_pandas_reports_missing_optional_dependency(self) -> None:
        measurement = open_handoff_package_sdk_view(PACKAGE)[0]

        with (
            patch(
                "implementation_candidates.handoff_package_sdk_view_model.view_model."
                "importlib.import_module",
                side_effect=ModuleNotFoundError("pandas"),
            ),
            self.assertRaisesRegex(RuntimeError, "pandas is required"),
        ):
            measurement.primary.to_pandas()

    def test_plot_to_numpy_reports_missing_optional_dependency(self) -> None:
        plot = open_handoff_package_sdk_view(PACKAGE)[0].plots.primary

        with (
            patch(
                "implementation_candidates.handoff_package_sdk_view_model.view_model."
                "importlib.import_module",
                side_effect=ModuleNotFoundError("numpy"),
            ),
            self.assertRaisesRegex(RuntimeError, "numpy is required"),
        ):
            plot.to_numpy()

    def test_context_and_findings_remain_visible(self) -> None:
        package = open_handoff_package_sdk_view(PACKAGE)
        measurement = package["legacy-rabi-001"]

        self.assertEqual(
            package.linked_context[0]["link_id"],
            "package-legacy-001-parameter-snapshot",
        )
        self.assertEqual(
            measurement.linked_context[0]["label"],
            "Run-local parameter snapshot",
        )
        self.assertEqual(
            package.findings[0]["finding"],
            "linked_context_not_packaged_visible_reference",
        )
        self.assertEqual(
            measurement.findings[0]["subject_id"],
            "package-legacy-001-parameter-snapshot",
        )

    def test_plot_collection_exposes_primary_and_saved_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _read_manifest(package_dir)
            plot_candidates = manifest["selected_measurements"][0]["declared_preview_metadata"][
                "plot_candidates"
            ]
            plot_candidates.append(dict(plot_candidates[0]))
            _write_manifest(package_dir, manifest)

            plots = open_handoff_package_sdk_view(package_dir)[0].plots

        self.assertEqual(plots.available, ("legacy-rabi-001-plot-0", "legacy-rabi-001-plot-1"))
        self.assertTrue(plots.primary.is_primary)
        self.assertEqual(plots.primary.plot_id, "legacy-rabi-001-plot-0")
        self.assertEqual(plots[1].label, "Rabi calibration follow-up view 2")
        self.assertEqual(plots["legacy-rabi-001-plot-1"].position, 1)
        with self.assertRaisesRegex(IndexError, "plot position out of range"):
            _ = plots[-1]

    def test_plot_spec_exports_records_pandas_and_numpy_for_notebooks(self) -> None:
        plot = open_handoff_package_sdk_view(PACKAGE)[0].plots.primary

        x_values, y_values = plot.to_numpy(numpy_module=_FakeNumpy)
        frame = plot.to_pandas(pandas_module=_FakePandas)

        self.assertEqual(plot.kind, "xy")
        self.assertEqual(plot.x_column.name, "drive_frequency")
        self.assertEqual(plot.y_column.name, "signal")
        self.assertEqual(x_values, ("array", ("4.98", "5.00", "5.02", "5.04", "5.06")))
        self.assertEqual(y_values, ("array", ("0.12", "0.44", "0.81", "0.45", "0.13")))
        self.assertEqual(frame.columns, ["drive_frequency", "signal"])
        self.assertEqual(frame.attrs["scopecat"]["kind"], "xy")
        self.assertEqual(frame.attrs["scopecat"]["fit_execution"], "not_performed")

    def test_free_text_column_names_remain_dataframe_keys(self) -> None:
        table = HandoffTable.from_records(
            ["Drive frequency (GHz)", "Signal / a.u."],
            [
                {"Drive frequency (GHz)": "5.00", "Signal / a.u.": "0.44"},
                {"Drive frequency (GHz)": "5.02", "Signal / a.u.": "0.81"},
            ],
        )
        sdk_table = SdkTable.from_handoff_table(
            table,
            declared_columns=(
                SdkColumn(
                    name="Drive frequency (GHz)",
                    label="Drive frequency",
                    role="sweep_axis",
                    unit="GHz",
                    position=0,
                ),
                SdkColumn(
                    name="Signal / a.u.",
                    label="Signal",
                    role="response",
                    unit="a.u.",
                    position=1,
                ),
            ),
            source="measurements/free-text/primary.csv",
            role="primary",
        )

        frame = sdk_table.to_pandas(pandas_module=_FakePandas)

        self.assertEqual(frame.columns, ["Drive frequency (GHz)", "Signal / a.u."])
        self.assertEqual(sdk_table["Drive frequency (GHz)"], ("5.00", "5.02"))
        self.assertEqual(frame.attrs["scopecat"]["columns"][1]["role"], "response")

    def test_iq_roles_classify_saved_plot_as_iq_scatter(self) -> None:
        series = HandoffPlotSeries.from_points(
            source="measurements/readout/primary.csv",
            x_name="I",
            y_name="Q",
            points=[{"x": "0.1", "y": "-0.2"}],
        )

        plot = SdkPlotSpec.from_series(
            measurement_record_id="readout-001",
            measurement_label="Readout IQ",
            position=0,
            series=series,
            columns_by_name={
                "I": SdkColumn("I", "I", "iq_i", "a.u.", 0),
                "Q": SdkColumn("Q", "Q", "iq_q", "a.u.", 1),
            },
        )

        self.assertEqual(plot.kind, "iq_scatter")
        self.assertEqual(plot.as_dict()["rendering"], "not_performed")

    def test_long_table_heatmap_plot_uses_x_y_z_columns_without_pivoting(self) -> None:
        table = HandoffTable.from_records(
            ["freq", "bias", "signal"],
            [
                {"freq": "5.00", "bias": "0.10", "signal": "-12.0"},
                {"freq": "5.10", "bias": "0.10", "signal": "-11.4"},
                {"freq": "5.00", "bias": "0.20", "signal": "-9.2"},
            ],
        )
        sdk_table = SdkTable.from_handoff_table(
            table,
            declared_columns=(
                SdkColumn("freq", "Drive frequency", "sweep_axis", "GHz", 0),
                SdkColumn("bias", "Bias", "sweep_axis", "V", 1),
                SdkColumn("signal", "Signal", "response", "dB", 2),
            ),
            source="measurements/flux-scan/primary.csv",
            role="primary",
        )

        plot = SdkPlotSpec.from_long_table(
            plot_id="flux-scan-heatmap",
            label="Flux scan",
            source=sdk_table.source,
            table=sdk_table,
            x="freq",
            y="bias",
            z="signal",
            is_primary=True,
            position=0,
        )

        self.assertEqual(plot.kind, "heatmap")
        self.assertEqual(plot.z_column.name, "signal")
        self.assertEqual(
            plot.to_records()[0],
            {"freq": "5.00", "bias": "0.10", "signal": "-12.0"},
        )
        self.assertEqual(
            plot.to_pandas(pandas_module=_FakePandas).columns, ["freq", "bias", "signal"]
        )
        self.assertEqual(plot.as_dict()["z_column"]["unit"], "dB")

    def test_sdk_objects_defensively_copy_caller_collections(self) -> None:
        columns = [
            SdkColumn("x", "X", "sweep_axis", None, 0),
            SdkColumn("y", "Y", "response", None, 1),
        ]
        records = [["1", "2"]]
        plot = SdkPlotSpec(
            plot_id="plot-1",
            label="Plot",
            kind="xy",
            source="measurements/example/primary.csv",
            columns=columns,
            _records=records,
            is_primary=True,
            position=0,
        )
        plots = [plot]
        plot_collection = SdkPlotCollection(plots)
        measurement = open_handoff_package_sdk_view(PACKAGE)[0]
        measurements = [measurement]
        measurement_collection = SdkMeasurementCollection(measurements)

        columns.append(SdkColumn("z", "Z", "response", None, 2))
        records[0].append("3")
        plots.append(plot)
        measurements.append(measurement)

        self.assertIsInstance(plot.columns, tuple)
        self.assertEqual(len(plot.columns), 2)
        self.assertEqual(plot.to_records(), [{"x": "1", "y": "2"}])
        self.assertEqual(plot_collection.available, ("plot-1",))
        self.assertEqual(len(plot_collection), 1)
        self.assertEqual(measurement_collection.ids, ("legacy-rabi-001",))
        self.assertEqual(len(measurement_collection), 1)

    def test_analysis_and_fit_results_are_reserved_read_only_extension_points(self) -> None:
        package = open_handoff_package_sdk_view(PACKAGE)
        measurement = package[0]

        self.assertEqual(measurement.analysis_results, ())
        self.assertEqual(measurement.fits, ())
        self.assertEqual(package.sdk_view_policy["analysis_writeback"], "not_performed")
        self.assertEqual(package.sdk_view_policy["scan_shape_inference"], "not_performed")


if __name__ == "__main__":
    unittest.main()

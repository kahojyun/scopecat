from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from implementation_candidates.handoff_package_sdk_view_model import (
    open_handoff_package_sdk_view,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_route_pressure"
    / "richer_reader_package"
    / "package"
    / "handoff-package-reader-pressure-001"
)


class _NotebookFrame:
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
    ) -> _NotebookFrame:
        return cls(records, columns)


class _NotebookPandas:
    DataFrame = _NotebookFrame


class _NotebookNumpy:
    @staticmethod
    def asarray(values: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        return ("array", tuple(values))


def _notebook_orientation(package_dir: Path) -> dict[str, Any]:
    package = open_handoff_package_sdk_view(package_dir)
    measurements = []
    for position, measurement in enumerate(package.measurements):
        primary_frame = measurement.primary.to_pandas(pandas_module=_NotebookPandas)
        plot_summaries = []
        for plot in measurement.plots:
            plot_frame = plot.to_pandas(pandas_module=_NotebookPandas)
            arrays = plot.to_numpy(numpy_module=_NotebookNumpy)
            plot_summaries.append(
                {
                    "plot_id": plot.plot_id,
                    "kind": plot.kind,
                    "label": plot.label,
                    "columns": list(plot_frame.columns),
                    "records": plot_frame.records,
                    "array_lengths": [len(array[1]) for array in arrays],
                    "metadata": plot_frame.attrs["scopecat"],
                }
            )
        measurements.append(
            {
                "position": position,
                "measurement_record_id": measurement.measurement_record_id,
                "label": measurement.label,
                "primary_columns": list(primary_frame.columns),
                "primary_records": primary_frame.records,
                "primary_metadata": primary_frame.attrs["scopecat"],
                "plot_count": len(measurement.plots),
                "plots": plot_summaries,
                "linked_context_ids": [item["link_id"] for item in measurement.linked_context],
                "fit_count": len(measurement.fits),
                "analysis_result_count": len(measurement.analysis_results),
            }
        )
    return {
        "package_id": package.package_id,
        "preview_classification": package.preview_classification,
        "measurement_ids": list(package.measurement_ids),
        "measurements": measurements,
        "package_finding_codes": [item["finding"] for item in package.findings],
        "policy": package.sdk_view_policy,
    }


class HandoffPackageSdkErgonomicsSpikeTest(unittest.TestCase):
    def test_notebook_script_discovers_measurements_tables_and_plots(self) -> None:
        summary = _notebook_orientation(PACKAGE)

        self.assertEqual(summary["package_id"], "handoff-package-reader-pressure-001")
        self.assertEqual(
            summary["measurement_ids"],
            ["pressure-rabi-001", "pressure-check-001"],
        )

        rabi = summary["measurements"][0]
        self.assertEqual(rabi["measurement_record_id"], "pressure-rabi-001")
        self.assertEqual(rabi["primary_columns"], ["drive_frequency", "signal", "residual"])
        self.assertEqual(rabi["primary_records"][2]["residual"], "0.01")
        self.assertEqual(rabi["primary_metadata"]["role"], "primary")
        self.assertEqual(rabi["primary_metadata"]["schema_inference"], "not_performed")
        self.assertEqual(rabi["plot_count"], 2)
        self.assertEqual(
            [plot["columns"] for plot in rabi["plots"]],
            [
                ["drive_frequency", "signal"],
                ["drive_frequency", "residual"],
            ],
        )
        self.assertEqual(rabi["plots"][1]["records"][2]["residual"], "0.01")
        self.assertEqual(rabi["plots"][1]["array_lengths"], [5, 5])
        self.assertEqual(rabi["plots"][1]["metadata"]["rendering"], "not_performed")
        self.assertEqual(rabi["fit_count"], 0)
        self.assertEqual(rabi["analysis_result_count"], 0)

    def test_table_only_measurement_still_supports_dataframe_first_use(self) -> None:
        summary = _notebook_orientation(PACKAGE)
        check = summary["measurements"][1]

        self.assertEqual(check["measurement_record_id"], "pressure-check-001")
        self.assertEqual(check["primary_columns"], ["delay", "contrast"])
        self.assertEqual(check["primary_records"][0], {"delay": "0.0", "contrast": "0.98"})
        self.assertEqual(check["plot_count"], 0)
        self.assertEqual(check["plots"], [])
        self.assertEqual(
            check["linked_context_ids"],
            ["pressure-shared-setup-snapshot"],
        )

    def test_sdk_policy_keeps_pandas_optional_and_read_only(self) -> None:
        summary = _notebook_orientation(PACKAGE)

        self.assertEqual(summary["policy"]["dataframe_adapter"], "optional_pandas")
        self.assertEqual(summary["policy"]["plot_rendering"], "not_performed")
        self.assertEqual(summary["policy"]["fit_execution"], "not_performed")
        self.assertEqual(summary["policy"]["analysis_writeback"], "not_performed")
        self.assertEqual(summary["policy"]["package_acceptance"], "not_performed")
        self.assertEqual(
            summary["package_finding_codes"],
            ["linked_context_not_packaged_visible_reference"],
        )


if __name__ == "__main__":
    unittest.main()

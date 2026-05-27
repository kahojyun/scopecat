from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_preview_shape_view import (
    DeclaredPreviewShape,
    open_handoff_package_preview_shape_view,
)
from implementation_candidates.handoff_package_read_view import open_handoff_package_view

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
SHAPE_FIXTURES = ROOT / "tests" / "fixtures" / "scan_data_shapes"


def _shape_input(name: str) -> dict:
    return json.loads((SHAPE_FIXTURES / name / "shape-input.json").read_text(encoding="utf-8"))


def _declared_shape(
    fixture_name: str,
    plot_candidates: tuple[dict, ...],
) -> DeclaredPreviewShape:
    source = _shape_input(fixture_name)
    return DeclaredPreviewShape.from_declared_preview(
        data_shape=source["data_shape"],
        declared_columns=tuple(source["declared_columns"]),
        plot_candidates=plot_candidates,
    )


class HandoffPackagePreviewShapeViewCandidateTest(unittest.TestCase):
    def test_opener_and_read_view_preserve_declared_data_shape(self) -> None:
        measurement = open_handoff_package_view(PACKAGE).measurement("legacy-rabi-001")

        shape = measurement.declared_preview_shape
        shape["kind"] = "mutated"

        self.assertEqual(measurement.declared_preview_shape["kind"], "declared_1d_table")
        self.assertEqual(
            measurement.declared_preview_plot_candidates[0]["x"],
            "drive_frequency",
        )

    def test_package_shape_view_exposes_declared_preview_table_affordance(self) -> None:
        package = open_handoff_package_preview_shape_view(PACKAGE)
        measurement = package.measurement("legacy-rabi-001")
        shape = measurement.preview_shape

        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        self.assertEqual(shape.kind, "declared_1d_table")
        self.assertEqual(shape.preview_affordance, "xy_series")
        self.assertEqual(shape.status, "declared_preview_affordance_ready")
        self.assertEqual(shape.axis_order, ("drive_frequency", "signal"))
        self.assertEqual(shape.axis_columns[0]["name"], "drive_frequency")
        self.assertEqual(shape.response_columns[0]["name"], "signal")
        self.assertEqual(shape.plot_candidates[0].plot_kind, "xy_series")
        self.assertEqual(
            dict(shape.plot_candidates[0].bindings),
            {"x": "drive_frequency", "y": "signal"},
        )
        self.assertEqual(
            package.preview_shape_policy["schema_inference"],
            "not_performed",
        )
        self.assertEqual(
            package.preview_shape_policy["scan_shape_owner"],
            "measurement_record_declared_semantics",
        )
        self.assertEqual(
            package.preview_shape_policy["table_shape_owner"],
            "primary_data_item_physical_table",
        )
        self.assertEqual(
            package.preview_shape_policy["preview_shape_owner"],
            "declared_reader_projection",
        )
        self.assertEqual(
            package.as_dict()["measurements"][0]["preview_projection"]["kind"],
            "declared_1d_table",
        )

    def test_rectangular_grid_preview_uses_declared_heatmap_binding(self) -> None:
        shape = _declared_shape(
            "2d_grid_table",
            (
                {
                    "title": "Signal map",
                    "x": "drive_frequency_ghz",
                    "y": "bias_v",
                    "z": "signal_db",
                    "source": "source/declared-2d-frequency-response-grid.csv",
                },
            ),
        )

        self.assertEqual(shape.preview_affordance, "heatmap_grid")
        self.assertEqual(shape.plot_candidates[0].plot_kind, "heatmap_grid")
        self.assertEqual(shape.plot_candidates[0].bindings["z"], "signal_db")
        self.assertEqual(shape.findings, ())

    def test_ragged_preview_uses_declared_line_family_binding(self) -> None:
        shape = _declared_shape(
            "ragged_adaptive_table",
            (
                {
                    "title": "Ragged lines",
                    "plot_kind": "ragged_line_family",
                    "x": "drive_frequency_ghz",
                    "series": "bias_v",
                    "y": "signal_db",
                    "source": "source/ragged-adaptive-frequency-response.csv",
                },
            ),
        )

        self.assertEqual(shape.preview_affordance, "ragged_line_family")
        self.assertEqual(shape.plot_candidates[0].plot_kind, "ragged_line_family")
        self.assertEqual(shape.plot_candidates[0].bindings["series"], "bias_v")

    def test_observed_ragged_preview_uses_distinct_declared_line_family_binding(self) -> None:
        shape = _declared_shape(
            "ragged_observed_only_table",
            (
                {
                    "title": "Observed ragged lines",
                    "plot_kind": "ragged_observed_line_family",
                    "x": "drive_frequency_ghz",
                    "series": "bias_v",
                    "y": "signal_db",
                    "source": "source/ragged-observed-frequency-response.csv",
                },
            ),
        )

        self.assertEqual(shape.preview_affordance, "ragged_observed_line_family")
        self.assertEqual(
            shape.plot_candidates[0].plot_kind,
            "ragged_observed_line_family",
        )

    def test_trace_preview_uses_declared_trace_family_binding_without_opening_traces(self) -> None:
        shape = _declared_shape(
            "trace_per_point_table",
            (
                {
                    "title": "Trace family",
                    "plot_kind": "trace_family",
                    "x": "time_ns",
                    "series": "bias_v",
                    "y": "signal_v",
                    "trace_ref_column": "trace_ref",
                    "source": "source/trace-point-index.csv",
                },
            ),
        )

        self.assertEqual(shape.preview_affordance, "trace_family")
        self.assertEqual(shape.declared_metadata_snapshot["kind"], "trace_per_point_table")
        self.assertEqual(shape.plot_candidates[0].plot_kind, "trace_family")
        self.assertEqual(shape.as_dict()["file_observation"], "not_performed")

    def test_fixed_vector_previews_use_declared_component_bindings(self) -> None:
        fixed = _declared_shape(
            "fixed_vector_response_table",
            (
                {
                    "title": "IQ scatter",
                    "plot_kind": "component_pair_scatter",
                    "x_component": "I",
                    "y_component": "Q",
                    "vector_column": "shot_iq",
                    "source": "source/single-shot-iq-vector.csv",
                },
            ),
        )
        complex_shape = _declared_shape(
            "complex_fixed_vector_response_table",
            (
                {
                    "title": "Complex IQ scatter",
                    "plot_kind": "complex_component_pair_scatter",
                    "x_component": "I",
                    "y_component": "Q",
                    "vector_column": "iq_v",
                    "source": "source/complex-iq-vector.csv",
                    "logical_value_type": "complex128",
                },
            ),
        )

        self.assertEqual(fixed.preview_affordance, "component_pair_scatter")
        self.assertEqual(fixed.plot_candidates[0].plot_kind, "component_pair_scatter")
        self.assertEqual(
            complex_shape.preview_affordance,
            "complex_component_pair_scatter",
        )
        self.assertEqual(
            complex_shape.plot_candidates[0].plot_kind,
            "complex_component_pair_scatter",
        )
        self.assertEqual(
            complex_shape.declared_metadata_snapshot["stability"],
            "debug_snapshot_not_final_schema",
        )

    def test_unsupported_preview_affordance_is_a_review_finding(self) -> None:
        shape = DeclaredPreviewShape.from_declared_preview(
            data_shape={"kind": "matrix_heatmap", "axis_order": ["row", "col"]},
            declared_columns=(
                {"name": "row", "label": "Row", "role": "sweep_axis", "unit": "index"},
                {"name": "col", "label": "Column", "role": "sweep_axis", "unit": "index"},
            ),
            plot_candidates=({"x": "row", "y": "col", "source": "matrix.csv"},),
        )

        self.assertEqual(shape.status, "unsupported_preview_affordance")
        self.assertEqual(shape.findings[0]["finding"], "declared_preview_affordance_unsupported")
        self.assertEqual(shape.plot_candidates, ())

    def test_incomplete_plot_binding_is_a_review_finding(self) -> None:
        shape = _declared_shape(
            "2d_grid_table",
            (
                {
                    "title": "Incomplete heatmap",
                    "x": "drive_frequency_ghz",
                    "y": "bias_v",
                    "source": "source/declared-2d-frequency-response-grid.csv",
                },
            ),
        )

        self.assertEqual(shape.status, "declared_preview_affordance_needs_review")
        self.assertEqual(shape.plot_candidates, ())
        self.assertEqual(
            shape.findings[0]["finding"],
            "declared_preview_plot_binding_incomplete",
        )
        self.assertEqual(shape.findings[0]["missing_bindings"], ("z",))

    def test_mismatched_declared_plot_kind_is_a_review_finding(self) -> None:
        shape = _declared_shape(
            "2d_grid_table",
            (
                {
                    "title": "Mismatched map",
                    "plot_kind": "component_pair_scatter",
                    "x": "drive_frequency_ghz",
                    "y": "bias_v",
                    "z": "signal_db",
                    "source": "source/declared-2d-frequency-response-grid.csv",
                },
            ),
        )

        self.assertEqual(shape.status, "declared_preview_affordance_needs_review")
        self.assertEqual(shape.plot_candidates, ())
        self.assertEqual(
            shape.findings[0]["finding"],
            "declared_preview_plot_kind_mismatch",
        )
        self.assertEqual(shape.findings[0]["expected_plot_kind"], "heatmap_grid")

    def test_invalid_table_plot_binding_is_a_review_finding(self) -> None:
        shape = _declared_shape(
            "2d_grid_table",
            (
                {
                    "title": "Invalid heatmap",
                    "x": "drive_frequency_ghz",
                    "y": "bias_v",
                    "z": "missing_column",
                    "source": "source/declared-2d-frequency-response-grid.csv",
                },
            ),
        )

        self.assertEqual(shape.status, "declared_preview_affordance_needs_review")
        self.assertEqual(shape.plot_candidates, ())
        self.assertEqual(
            shape.findings[0]["finding"],
            "declared_preview_plot_binding_invalid",
        )
        self.assertEqual(shape.findings[0]["invalid_bindings"][0]["binding"], "z")

    def test_invalid_trace_plot_binding_is_a_review_finding(self) -> None:
        shape = _declared_shape(
            "trace_per_point_table",
            (
                {
                    "title": "Wrong trace reference",
                    "plot_kind": "trace_family",
                    "x": "time_ns",
                    "series": "bias_v",
                    "y": "signal_v",
                    "trace_ref_column": "trace_path",
                    "source": "source/trace-point-index.csv",
                },
            ),
        )

        self.assertEqual(shape.status, "declared_preview_affordance_needs_review")
        self.assertEqual(shape.plot_candidates, ())
        self.assertEqual(
            shape.findings[0]["finding"],
            "declared_preview_plot_binding_invalid",
        )
        self.assertEqual(
            shape.findings[0]["invalid_bindings"][0]["binding"],
            "trace_ref_column",
        )

    def test_invalid_vector_component_binding_is_a_review_finding(self) -> None:
        shape = _declared_shape(
            "fixed_vector_response_table",
            (
                {
                    "title": "Invalid IQ scatter",
                    "plot_kind": "component_pair_scatter",
                    "x_component": "I",
                    "y_component": "phase",
                    "vector_column": "shot_iq",
                    "source": "source/single-shot-iq-vector.csv",
                },
            ),
        )

        self.assertEqual(shape.status, "declared_preview_affordance_needs_review")
        self.assertEqual(shape.plot_candidates, ())
        self.assertEqual(
            shape.findings[0]["finding"],
            "declared_preview_plot_binding_invalid",
        )
        self.assertEqual(
            shape.findings[0]["invalid_bindings"][0]["binding"],
            "y_component",
        )

    def test_preview_projection_nested_values_are_read_only(self) -> None:
        shape = _declared_shape(
            "2d_grid_table",
            (
                {
                    "title": "Signal map",
                    "x": "drive_frequency_ghz",
                    "y": "bias_v",
                    "z": "signal_db",
                    "source": "source/declared-2d-frequency-response-grid.csv",
                },
            ),
        )

        with self.assertRaises(TypeError):
            shape.axis_columns[0]["name"] = "mutated"
        with self.assertRaises(TypeError):
            shape.plot_candidates[0].bindings["z"] = "mutated"

        projected = shape.as_dict()
        projected["axis_columns"][0]["name"] = "mutated"
        projected["plot_candidates"][0]["bindings"]["z"] = "mutated"

        self.assertEqual(shape.axis_columns[0]["name"], "bias_v")
        self.assertEqual(shape.plot_candidates[0].bindings["z"], "signal_db")


if __name__ == "__main__":
    unittest.main()

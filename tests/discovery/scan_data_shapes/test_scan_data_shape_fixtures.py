from __future__ import annotations

import csv
import json
import unittest
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "discovery" / "scan_data_shapes"
GRID_FIXTURE = FIXTURE_ROOT / "2d_grid_table"
SIDECAR_FIXTURE = FIXTURE_ROOT / "sidecar_declared_table"
RAGGED_FIXTURE = FIXTURE_ROOT / "ragged_adaptive_table"
OBSERVED_RAGGED_FIXTURE = FIXTURE_ROOT / "ragged_observed_only_table"
TRACE_FIXTURE = FIXTURE_ROOT / "trace_per_point_table"
FIXED_VECTOR_FIXTURE = FIXTURE_ROOT / "fixed_vector_response_table"
COMPLEX_FIXED_VECTOR_FIXTURE = FIXTURE_ROOT / "complex_fixed_vector_response_table"


class ScanDataShapeFixtureTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_2d_grid_fixture_json_files_are_valid(self) -> None:
        for path in [
            GRID_FIXTURE / "shape-input.json",
            GRID_FIXTURE / "expected-shape-summary.json",
        ]:
            with self.subTest(path=path):
                self._load_json(path)

    def test_2d_grid_summary_matches_source_table_shape(self) -> None:
        shape_input = self._load_json(GRID_FIXTURE / "shape-input.json")
        summary = self._load_json(GRID_FIXTURE / "expected-shape-summary.json")
        source_path = GRID_FIXTURE / summary["measurement"]["source_table"]
        with source_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        axis_order = summary["shape"]["axis_order"]
        axis_values = {axis: sorted({row[axis] for row in rows}) for axis in axis_order}
        axis_cardinality = {axis: len(values) for axis, values in axis_values.items()}
        expected_point_count = 1
        for count in axis_cardinality.values():
            expected_point_count *= count
        observed_coordinates = {tuple(row[axis] for axis in axis_order) for row in rows}
        expected_coordinates = set(product(*(axis_values[axis] for axis in axis_order)))

        self.assertEqual(shape_input["measurement"], summary["measurement"])
        self.assertEqual(shape_input["data_shape"]["kind"], summary["shape"]["kind"])
        self.assertEqual(
            shape_input["data_shape"]["grid_assumption"],
            summary["shape"]["grid_assumption"],
        )
        self.assertEqual(shape_input["data_shape"]["axis_order"], axis_order)
        self.assertEqual(axis_cardinality, summary["shape"]["axis_cardinality"])
        self.assertEqual(expected_point_count, summary["shape"]["expected_point_count"])
        self.assertEqual(len(rows), summary["shape"]["actual_row_count"])
        self.assertEqual(len(rows), summary["shape"]["expected_point_count"])
        self.assertEqual(observed_coordinates, expected_coordinates)
        self.assertEqual(len(observed_coordinates), len(rows))
        self.assertEqual(summary["shape"]["status"], "pass")

    def test_2d_grid_column_validation_reports_extra_source_column(self) -> None:
        shape_input = self._load_json(GRID_FIXTURE / "shape-input.json")
        summary = self._load_json(GRID_FIXTURE / "expected-shape-summary.json")
        validation = summary["column_validation"]
        declared_names = [column["name"] for column in shape_input["declared_columns"]]

        self.assertEqual(declared_names, validation["declared_columns"])
        self.assertEqual(validation["status"], "pass")
        self.assertEqual(validation["missing_declared_columns"], [])
        self.assertEqual(validation["extra_source_columns"], ["operator_note"])
        self.assertIn("operator_note", validation["source_columns"])
        self.assertEqual(
            shape_input["held_conditions"],
            summary["held_conditions"],
        )

    def test_2d_grid_review_states_model_adequacy_boundary(self) -> None:
        review = (GRID_FIXTURE / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertIn("kind: `2d_grid_table`", review)
        self.assertIn("grid assumption: `rectangular_complete_grid`", review)
        self.assertIn("declared 2D grid plot candidates only", review)
        self.assertIn("model adequacy, not a final storage or plotting API", review)

    def test_sidecar_fixture_json_files_are_valid(self) -> None:
        for path in [
            SIDECAR_FIXTURE / "shape-input.json",
            SIDECAR_FIXTURE / "expected-shape-summary.json",
        ]:
            with self.subTest(path=path):
                self._load_json(path)

    def test_sidecar_declared_columns_map_to_physical_columns(self) -> None:
        shape_input = self._load_json(SIDECAR_FIXTURE / "shape-input.json")
        summary = self._load_json(SIDECAR_FIXTURE / "expected-shape-summary.json")
        source_path = SIDECAR_FIXTURE / summary["measurement"]["source_table"]
        with source_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        physical_columns = reader.fieldnames or []
        mapped_physical_columns = [item["physical_name"] for item in summary["column_mapping"]]
        declared_names = [item["declared_name"] for item in summary["column_mapping"]]
        roles = {item["role"] for item in summary["column_mapping"]}

        self.assertEqual(shape_input["measurement"], summary["measurement"])
        self.assertEqual(shape_input["data_shape"]["kind"], summary["shape"]["kind"])
        self.assertEqual(shape_input["data_shape"]["table_shape"], summary["shape"]["table_shape"])
        self.assertEqual(shape_input["data_shape"]["axis_order"], summary["shape"]["axis_order"])
        self.assertEqual(shape_input["column_mapping"], summary["column_mapping"])
        self.assertEqual(shape_input["held_conditions"], summary["held_conditions"])
        self.assertEqual(physical_columns, summary["column_validation"]["physical_columns"])
        self.assertEqual(mapped_physical_columns, physical_columns)
        self.assertEqual(len(declared_names), len(set(declared_names)))
        self.assertEqual(declared_names, summary["column_validation"]["declared_names"])
        self.assertIn("sweep_axis", roles)
        self.assertIn("measured_response", roles)
        self.assertEqual(summary["shape"]["row_count"], len(rows))

    def test_sidecar_review_states_no_schema_inference_boundary(self) -> None:
        review = (SIDECAR_FIXTURE / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertIn("kind: `sidecar_declared_table`", review)
        self.assertIn("metadata source: `sidecar_declaration`", review)
        self.assertIn("not source header inference", review)
        self.assertIn("not a sidecar importer or schema", review)

    def test_ragged_fixture_json_files_are_valid(self) -> None:
        for path in [
            RAGGED_FIXTURE / "shape-input.json",
            RAGGED_FIXTURE / "expected-shape-summary.json",
        ]:
            with self.subTest(path=path):
                self._load_json(path)

    def test_ragged_summary_matches_declared_group_coverage(self) -> None:
        shape_input = self._load_json(RAGGED_FIXTURE / "shape-input.json")
        summary = self._load_json(RAGGED_FIXTURE / "expected-shape-summary.json")
        source_path = RAGGED_FIXTURE / summary["measurement"]["source_table"]
        with source_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        axis_order = summary["shape"]["axis_order"]
        grouping_axis = summary["shape"]["grouping_axis"]
        observed_coordinates = {tuple(row[axis] for axis in axis_order) for row in rows}
        group_counts: dict[str, int] = {}
        for row in rows:
            group = row[grouping_axis]
            group_counts[group] = group_counts.get(group, 0) + 1

        self.assertEqual(shape_input["measurement"], summary["measurement"])
        self.assertEqual(shape_input["data_shape"]["kind"], summary["shape"]["kind"])
        self.assertEqual(
            shape_input["data_shape"]["ragged_assumption"],
            summary["shape"]["ragged_assumption"],
        )
        self.assertEqual(shape_input["data_shape"]["axis_order"], axis_order)
        self.assertEqual(shape_input["data_shape"]["grouping_axis"], grouping_axis)
        self.assertEqual(
            shape_input["data_shape"]["ragged_axis"],
            summary["shape"]["ragged_axis"],
        )
        self.assertEqual(
            shape_input["data_shape"]["expected_group_point_counts"],
            summary["shape"]["expected_group_point_counts"],
        )
        self.assertEqual(group_counts, summary["shape"]["group_point_counts"])
        self.assertEqual(len(rows), summary["shape"]["total_row_count"])
        self.assertEqual(len(observed_coordinates), len(rows))
        self.assertEqual(summary["shape"]["status"], "pass")

    def test_ragged_plot_candidates_are_line_families_not_heatmaps(self) -> None:
        summary = self._load_json(RAGGED_FIXTURE / "expected-shape-summary.json")

        self.assertEqual(
            ["ragged_line_family", "ragged_line_family"],
            [candidate["plot_kind"] for candidate in summary["plot_candidates"]],
        )
        self.assertEqual(
            ["signal_db", "phase_deg"],
            [candidate["y"] for candidate in summary["plot_candidates"]],
        )
        self.assertTrue(all("z" not in candidate for candidate in summary["plot_candidates"]))

    def test_ragged_review_states_no_rectangular_grid_coercion_boundary(self) -> None:
        review = (RAGGED_FIXTURE / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertIn("kind: `ragged_adaptive_table`", review)
        self.assertIn("ragged assumption: `declared_variable_inner_axis`", review)
        self.assertIn("treated as missing rectangular grid points", review)
        self.assertIn("not rectangular grid coercion", review)

    def test_observed_ragged_fixture_json_files_are_valid(self) -> None:
        for path in [
            OBSERVED_RAGGED_FIXTURE / "shape-input.json",
            OBSERVED_RAGGED_FIXTURE / "expected-shape-summary.json",
        ]:
            with self.subTest(path=path):
                self._load_json(path)

    def test_observed_ragged_summary_reports_counts_without_expected_counts(self) -> None:
        shape_input = self._load_json(OBSERVED_RAGGED_FIXTURE / "shape-input.json")
        summary = self._load_json(OBSERVED_RAGGED_FIXTURE / "expected-shape-summary.json")
        source_path = OBSERVED_RAGGED_FIXTURE / summary["measurement"]["source_table"]
        with source_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        axis_order = summary["shape"]["axis_order"]
        grouping_axis = summary["shape"]["grouping_axis"]
        observed_coordinates = {tuple(row[axis] for axis in axis_order) for row in rows}
        group_counts: dict[str, int] = {}
        for row in rows:
            group = row[grouping_axis]
            group_counts[group] = group_counts.get(group, 0) + 1

        self.assertEqual(shape_input["measurement"], summary["measurement"])
        self.assertEqual(shape_input["data_shape"]["kind"], summary["shape"]["kind"])
        self.assertEqual("observed_only", summary["shape"]["coverage_policy"])
        self.assertNotIn("expected_group_point_counts", summary["shape"])
        self.assertNotIn("missing_expected_groups", summary["shape"])
        self.assertNotIn("unexpected_observed_groups", summary["shape"])
        self.assertEqual(group_counts, summary["shape"]["group_point_counts"])
        self.assertEqual(len(rows), summary["shape"]["total_row_count"])
        self.assertEqual(len(observed_coordinates), len(rows))
        self.assertEqual(summary["shape"]["status"], "pass")

    def test_observed_ragged_review_disclaims_completeness(self) -> None:
        review = (OBSERVED_RAGGED_FIXTURE / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertIn("kind: `ragged_observed_only_table`", review)
        self.assertIn("coverage policy: `observed_only`", review)
        self.assertIn("Observed group coverage", review)
        self.assertIn("completeness against planned group counts is not claimed", review)

    def test_trace_fixture_json_files_are_valid(self) -> None:
        for path in [
            TRACE_FIXTURE / "shape-input.json",
            TRACE_FIXTURE / "expected-shape-summary.json",
        ]:
            with self.subTest(path=path):
                self._load_json(path)

    def test_trace_summary_matches_outer_table_and_trace_files(self) -> None:
        shape_input = self._load_json(TRACE_FIXTURE / "shape-input.json")
        summary = self._load_json(TRACE_FIXTURE / "expected-shape-summary.json")
        source_path = TRACE_FIXTURE / summary["measurement"]["source_table"]
        with source_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        trace_ref_column = summary["shape"]["trace_ref_column"]
        trace_refs = [row[trace_ref_column] for row in rows]
        trace_row_counts = []
        for trace_ref in trace_refs:
            with (TRACE_FIXTURE / trace_ref).open(newline="", encoding="utf-8") as handle:
                trace_reader = csv.DictReader(handle)
                trace_rows = list(trace_reader)
                trace_row_counts.append(len(trace_rows))
                self.assertEqual(["time_ns", "signal_v"], trace_reader.fieldnames)

        self.assertEqual(shape_input["measurement"], summary["measurement"])
        self.assertEqual(shape_input["data_shape"]["kind"], summary["shape"]["kind"])
        self.assertEqual(shape_input["data_shape"]["axis_order"], summary["shape"]["axis_order"])
        self.assertEqual(
            shape_input["data_shape"]["trace_ref_column"],
            summary["shape"]["trace_ref_column"],
        )
        self.assertEqual(len(rows), summary["shape"]["point_count"])
        self.assertEqual(trace_refs, summary["trace_validation"]["trace_refs"])
        self.assertEqual(
            trace_row_counts,
            [item["row_count"] for item in summary["trace_validation"]["trace_summaries"]],
        )
        self.assertEqual(summary["shape"]["status"], "pass")

    def test_trace_review_states_trace_family_boundary(self) -> None:
        review = (TRACE_FIXTURE / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertIn("kind: `trace_per_point_table`", review)
        self.assertIn("Trace Validation", review)
        self.assertIn("trace-family plot candidate", review)
        self.assertIn("not a binary container", review)

    def test_fixed_vector_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXED_VECTOR_FIXTURE / "shape-input.json",
            FIXED_VECTOR_FIXTURE / "expected-shape-summary.json",
        ]:
            with self.subTest(path=path):
                self._load_json(path)

    def test_fixed_vector_summary_matches_declared_value_shape(self) -> None:
        shape_input = self._load_json(FIXED_VECTOR_FIXTURE / "shape-input.json")
        summary = self._load_json(FIXED_VECTOR_FIXTURE / "expected-shape-summary.json")
        source_path = FIXED_VECTOR_FIXTURE / summary["measurement"]["source_table"]
        with source_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        vector_column = shape_input["data_shape"]["vector_columns"][0]
        vector_summary = summary["vector_validation"]["column_summaries"][0]
        parsed_vectors = [json.loads(row[vector_column["name"]]) for row in rows]
        observed_coordinates = {
            tuple(row[axis] for axis in summary["shape"]["axis_order"]) for row in rows
        }

        self.assertEqual(shape_input["measurement"], summary["measurement"])
        self.assertEqual(shape_input["data_shape"]["kind"], summary["shape"]["kind"])
        self.assertEqual(
            shape_input["data_shape"]["vector_assumption"],
            summary["shape"]["vector_assumption"],
        )
        self.assertEqual(shape_input["data_shape"]["axis_order"], summary["shape"]["axis_order"])
        self.assertEqual(len(rows), summary["shape"]["row_count"])
        self.assertEqual(len(observed_coordinates), len(rows))
        self.assertFalse(summary["shape"]["duplicate_coordinates"])
        self.assertEqual(vector_column["value_shape"], vector_summary["value_shape"])
        self.assertEqual(
            [len(rows), *vector_column["value_shape"]], vector_summary["reader_ndarray_shape"]
        )
        self.assertTrue(all(len(vector) == 2 for vector in parsed_vectors))
        self.assertEqual(vector_summary["observed_lengths"], ["2"])
        self.assertEqual(summary["shape"]["status"], "pass")

    def test_fixed_vector_review_states_no_general_ndarray_boundary(self) -> None:
        review = (FIXED_VECTOR_FIXTURE / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertIn("kind: `fixed_vector_response_table`", review)
        self.assertIn("reader ndarray shape", review)
        self.assertIn("not a general array-column API", review)
        self.assertIn("not arbitrary ndarray", review)

    def test_complex_fixed_vector_fixture_json_files_are_valid(self) -> None:
        for path in [
            COMPLEX_FIXED_VECTOR_FIXTURE / "shape-input.json",
            COMPLEX_FIXED_VECTOR_FIXTURE / "expected-shape-summary.json",
        ]:
            with self.subTest(path=path):
                self._load_json(path)

    def test_complex_fixed_vector_summary_reports_logical_value_views(self) -> None:
        shape_input = self._load_json(COMPLEX_FIXED_VECTOR_FIXTURE / "shape-input.json")
        summary = self._load_json(COMPLEX_FIXED_VECTOR_FIXTURE / "expected-shape-summary.json")
        vector_column = shape_input["data_shape"]["vector_columns"][0]
        vector_summary = summary["vector_validation"]["column_summaries"][0]
        plot_candidate = summary["plot_candidates"][0]

        self.assertEqual("complex_fixed_vector_response_table", summary["shape"]["kind"])
        self.assertEqual(vector_column["logical_value"], vector_summary["logical_value"])
        self.assertEqual("complex128", vector_summary["logical_value"]["type"])
        self.assertEqual("cartesian_vector", vector_summary["logical_value"]["representation"])
        self.assertEqual(
            ["real", "imag", "magnitude", "phase"],
            vector_summary["logical_value"]["derived_components"],
        )
        self.assertEqual("complex_component_pair_scatter", plot_candidate["plot_kind"])
        self.assertEqual("complex128", plot_candidate["logical_value_type"])
        self.assertEqual(
            ["real", "imag", "magnitude", "phase"],
            plot_candidate["derived_components"],
        )

    def test_complex_fixed_vector_review_states_no_complex_primitive_boundary(self) -> None:
        review = (COMPLEX_FIXED_VECTOR_FIXTURE / "expected-shape-review.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("kind: `complex_fixed_vector_response_table`", review)
        self.assertIn("Logical Value Views", review)
        self.assertIn("`complex128`", review)
        self.assertIn("not arbitrary ndarray", review)


if __name__ == "__main__":
    unittest.main()

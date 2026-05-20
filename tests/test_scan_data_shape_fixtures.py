from __future__ import annotations

import csv
import json
import unittest
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRID_FIXTURE = ROOT / "tests" / "fixtures" / "scan_data_shapes" / "2d_grid_table"
SIDECAR_FIXTURE = ROOT / "tests" / "fixtures" / "scan_data_shapes" / "sidecar_declared_table"


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


if __name__ == "__main__":
    unittest.main()

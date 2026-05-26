from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spikes.scan_data_shapes.generate import generate_review, generate_summary

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "scan_data_shapes"


class ScanDataShapeGeneratorTest(unittest.TestCase):
    def _write_2d_grid_fixture(self, fixture: Path, source_text: str) -> None:
        source = json.loads(
            (FIXTURE_ROOT / "2d_grid_table" / "shape-input.json").read_text(encoding="utf-8")
        )
        source_dir = fixture / "source"
        source_dir.mkdir(parents=True)
        (fixture / "shape-input.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
        (source_dir / "declared-2d-frequency-response-grid.csv").write_text(
            source_text,
            encoding="utf-8",
        )

    def _write_sidecar_fixture(self, fixture: Path, source_text: str) -> None:
        source = json.loads(
            (FIXTURE_ROOT / "sidecar_declared_table" / "shape-input.json").read_text(
                encoding="utf-8"
            )
        )
        source_dir = fixture / "source"
        source_dir.mkdir(parents=True)
        (fixture / "shape-input.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
        (source_dir / "sidecar-declared-rabi-table.csv").write_text(
            source_text,
            encoding="utf-8",
        )

    def _write_ragged_fixture(self, fixture: Path, source_text: str) -> None:
        source = json.loads(
            (FIXTURE_ROOT / "ragged_adaptive_table" / "shape-input.json").read_text(
                encoding="utf-8"
            )
        )
        source_dir = fixture / "source"
        source_dir.mkdir(parents=True)
        (fixture / "shape-input.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
        (source_dir / "ragged-adaptive-frequency-response.csv").write_text(
            source_text,
            encoding="utf-8",
        )

    def _write_trace_fixture(self, fixture: Path, source_text: str) -> None:
        source = json.loads(
            (FIXTURE_ROOT / "trace_per_point_table" / "shape-input.json").read_text(
                encoding="utf-8"
            )
        )
        source_dir = fixture / "source"
        trace_dir = source_dir / "traces"
        trace_dir.mkdir(parents=True)
        (fixture / "shape-input.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
        (source_dir / "trace-point-index.csv").write_text(source_text, encoding="utf-8")
        (trace_dir / "bias-0p0.csv").write_text(
            "\n".join(["time_ns,signal_v", "0,0.91", "20,0.61", ""]),
            encoding="utf-8",
        )

    def _write_fixed_vector_fixture(self, fixture: Path, source_text: str) -> None:
        source = json.loads(
            (FIXTURE_ROOT / "fixed_vector_response_table" / "shape-input.json").read_text(
                encoding="utf-8"
            )
        )
        source_dir = fixture / "source"
        source_dir.mkdir(parents=True)
        (fixture / "shape-input.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
        (source_dir / "single-shot-iq-vector.csv").write_text(source_text, encoding="utf-8")

    def _write_complex_fixed_vector_fixture(self, fixture: Path, source_text: str) -> None:
        source = json.loads(
            (FIXTURE_ROOT / "complex_fixed_vector_response_table" / "shape-input.json").read_text(
                encoding="utf-8"
            )
        )
        source_dir = fixture / "source"
        source_dir.mkdir(parents=True)
        (fixture / "shape-input.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
        (source_dir / "complex-iq-vector.csv").write_text(source_text, encoding="utf-8")

    def test_generates_2d_grid_expected_summary(self) -> None:
        fixture = FIXTURE_ROOT / "2d_grid_table"

        expected = json.loads((fixture / "expected-shape-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(generate_summary(fixture), expected)

    def test_generates_2d_grid_expected_review(self) -> None:
        fixture = FIXTURE_ROOT / "2d_grid_table"

        expected = (fixture / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertEqual(generate_review(generate_summary(fixture)), expected)

    def test_generates_sidecar_expected_summary(self) -> None:
        fixture = FIXTURE_ROOT / "sidecar_declared_table"

        expected = json.loads((fixture / "expected-shape-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(generate_summary(fixture), expected)

    def test_generates_sidecar_expected_review(self) -> None:
        fixture = FIXTURE_ROOT / "sidecar_declared_table"

        expected = (fixture / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertEqual(generate_review(generate_summary(fixture)), expected)

    def test_generates_ragged_expected_summary(self) -> None:
        fixture = FIXTURE_ROOT / "ragged_adaptive_table"

        expected = json.loads((fixture / "expected-shape-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(generate_summary(fixture), expected)

    def test_generates_ragged_expected_review(self) -> None:
        fixture = FIXTURE_ROOT / "ragged_adaptive_table"

        expected = (fixture / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertEqual(generate_review(generate_summary(fixture)), expected)

    def test_generates_ragged_observed_only_expected_summary(self) -> None:
        fixture = FIXTURE_ROOT / "ragged_observed_only_table"

        expected = json.loads((fixture / "expected-shape-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(generate_summary(fixture), expected)

    def test_generates_ragged_observed_only_expected_review(self) -> None:
        fixture = FIXTURE_ROOT / "ragged_observed_only_table"

        expected = (fixture / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertEqual(generate_review(generate_summary(fixture)), expected)

    def test_generates_trace_per_point_expected_summary(self) -> None:
        fixture = FIXTURE_ROOT / "trace_per_point_table"

        expected = json.loads((fixture / "expected-shape-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(generate_summary(fixture), expected)

    def test_generates_trace_per_point_expected_review(self) -> None:
        fixture = FIXTURE_ROOT / "trace_per_point_table"

        expected = (fixture / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertEqual(generate_review(generate_summary(fixture)), expected)

    def test_generates_fixed_vector_response_expected_summary(self) -> None:
        fixture = FIXTURE_ROOT / "fixed_vector_response_table"

        expected = json.loads((fixture / "expected-shape-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(generate_summary(fixture), expected)

    def test_generates_fixed_vector_response_expected_review(self) -> None:
        fixture = FIXTURE_ROOT / "fixed_vector_response_table"

        expected = (fixture / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertEqual(generate_review(generate_summary(fixture)), expected)

    def test_generates_complex_fixed_vector_response_expected_summary(self) -> None:
        fixture = FIXTURE_ROOT / "complex_fixed_vector_response_table"

        expected = json.loads((fixture / "expected-shape-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(generate_summary(fixture), expected)

    def test_generates_complex_fixed_vector_response_expected_review(self) -> None:
        fixture = FIXTURE_ROOT / "complex_fixed_vector_response_table"

        expected = (fixture / "expected-shape-review.md").read_text(encoding="utf-8")

        self.assertEqual(generate_review(generate_summary(fixture)), expected)

    def test_2d_grid_reports_missing_axis_cell_as_failed_shape(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_2d_grid_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,drive_frequency_ghz,signal_db,phase_deg",
                        "0.100",
                        "0.100,4.900,-43.5,18.0",
                        "0.100,5.000,-40.8,25.0",
                        "0.200,4.800,-39.7,8.0",
                        "0.200,4.900,-44.1,15.0",
                        "0.200,5.000,-42.0,21.0",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["shape"]["actual_row_count"], 6)

    def test_2d_grid_rejects_unsafe_source_table_reference(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "fixture"
            fixture.mkdir()
            self._write_2d_grid_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,drive_frequency_ghz,signal_db,phase_deg",
                        "0.100,4.800,-41.2,12.0",
                        "",
                    ]
                ),
            )
            outside = Path(temp_dir) / "outside.csv"
            outside.write_text(
                "\n".join(
                    [
                        "bias_v,drive_frequency_ghz,signal_db,phase_deg",
                        "0.100,4.800,-41.2,12.0",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["measurement"]["source_table"] = "../outside.csv"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["column_validation"]["source_columns"], [])
        self.assertEqual(
            summary["column_validation"]["missing_declared_columns"],
            ["bias_v", "drive_frequency_ghz", "signal_db", "phase_deg"],
        )

    def test_2d_grid_review_handles_no_extra_source_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_2d_grid_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,drive_frequency_ghz,signal_db,phase_deg",
                        "0.100,4.800,-41.2,12.0",
                        "0.100,4.900,-43.5,18.0",
                        "0.100,5.000,-40.8,25.0",
                        "0.200,4.800,-39.7,8.0",
                        "0.200,4.900,-44.1,15.0",
                        "0.200,5.000,-42.0,21.0",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)
            review = generate_review(summary)

        self.assertEqual(summary["shape"]["status"], "pass")
        self.assertEqual(summary["column_validation"]["extra_source_columns"], [])
        self.assertIn("## Warnings\n\n- `none`", review)

    def test_2d_grid_rejects_malformed_axis_order_without_plot_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_2d_grid_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,drive_frequency_ghz,signal_db,phase_deg",
                        "0.100,4.800,-41.2,12.0",
                        "0.100,4.900,-43.5,18.0",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["axis_order"] = ["bias_v"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])

    def test_sidecar_missing_response_role_returns_failed_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_sidecar_fixture(
                fixture,
                "\n".join(
                    [
                        "c0,c1,c2",
                        "0.00,0.02,200",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["column_mapping"][1]["role"] = "supporting_count"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["column_validation"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])

    def test_ragged_missing_grouping_column_returns_failed_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_ragged_fixture(
                fixture,
                "\n".join(
                    [
                        "drive_frequency_ghz,signal_db,phase_deg",
                        "4.96,-13.2,10",
                        "5.02,-18.5,42",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["shape"]["group_point_counts"], {})
        self.assertEqual(summary["column_validation"]["missing_declared_columns"], ["bias_v"])

    def test_ragged_undeclared_shape_axis_returns_failed_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_ragged_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,hidden_group,drive_frequency_ghz,signal_db,phase_deg",
                        "0.0,A,4.96,-13.2,10",
                        "0.0,A,5.02,-18.5,42",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["grouping_axis"] = "hidden_group"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["shape"]["group_point_counts"], {})
        self.assertEqual(summary["column_validation"]["undeclared_shape_columns"], ["hidden_group"])

    def test_ragged_unexpected_group_is_visible_in_review(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_ragged_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,drive_frequency_ghz,signal_db,phase_deg",
                        "0.0,4.96,-13.2,10",
                        "0.0,5.02,-18.5,42",
                        "0.1,4.92,-11.8,8",
                        "0.1,4.96,-16.9,25",
                        "0.1,5.00,-21.1,55",
                        "0.1,5.04,-17.4,31",
                        "0.2,4.94,-12.6,12",
                        "0.2,5.00,-19.8,48",
                        "0.2,5.06,-13.1,19",
                        "0.3,5.08,-12.7,21",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)
            review = generate_review(summary)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["shape"]["unexpected_observed_groups"], ["0.3"])
        self.assertIn("| `0.3` | `undeclared` | `1` |", review)

    def test_ragged_review_handles_no_extra_source_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_ragged_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,drive_frequency_ghz,signal_db,phase_deg",
                        "0.0,4.96,-13.2,10",
                        "0.0,5.02,-18.5,42",
                        "0.1,4.92,-11.8,8",
                        "0.1,4.96,-16.9,25",
                        "0.1,5.00,-21.1,55",
                        "0.1,5.04,-17.4,31",
                        "0.2,4.94,-12.6,12",
                        "0.2,5.00,-19.8,48",
                        "0.2,5.06,-13.1,19",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)
            review = generate_review(summary)

        self.assertEqual(summary["warnings"], [])
        self.assertEqual(summary["column_validation"]["extra_source_columns"], [])
        self.assertIn("## Warnings\n\n- `none`", review)

    def test_trace_per_point_rejects_unsafe_trace_reference(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,../outside.csv,ringdown",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["trace_validation"]["unsafe_trace_refs"], ["../outside.csv"])
        self.assertEqual(
            summary["trace_validation"]["trace_summaries"][0]["status"], "unsafe_reference"
        )

    def test_trace_per_point_rejects_missing_trace_reference_cell(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["trace_validation"]["unsafe_trace_refs"], [None])
        self.assertEqual(
            summary["trace_validation"]["trace_summaries"][0]["status"], "unsafe_reference"
        )

    def test_trace_per_point_rejects_empty_axis_order_without_plot_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["axis_order"] = []
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])

    def test_trace_per_point_rejects_null_axis_order_without_crashing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["axis_order"] = None
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["trace_validation"]["invalid_trace_metadata_fields"],
            ["axis_order"],
        )
        self.assertEqual(summary["trace_validation"]["trace_refs"], [])
        self.assertEqual(summary["plot_candidates"], [])

    def test_trace_per_point_rejects_non_string_axis_order_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["axis_order"] = ["bias_v", ["nested_axis"]]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["trace_validation"]["invalid_trace_metadata_fields"],
            ["axis_order"],
        )
        self.assertEqual(summary["trace_validation"]["trace_refs"], [])
        self.assertEqual(summary["plot_candidates"], [])

    def test_trace_per_point_reports_missing_trace_schema_field(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            del source["data_shape"]["trace_schema"]["response_column"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["trace_validation"]["missing_trace_schema_fields"],
            ["response_column"],
        )
        self.assertEqual(summary["plot_candidates"], [])

    def test_trace_per_point_rejects_non_string_trace_ref_column(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["trace_ref_column"] = ["trace_ref"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["trace_validation"]["invalid_trace_metadata_fields"],
            ["trace_ref_column"],
        )
        self.assertEqual(summary["trace_validation"]["trace_refs"], [])
        self.assertEqual(summary["plot_candidates"], [])

    def test_trace_per_point_reports_missing_trace_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            (fixture / "source" / "traces" / "bias-0p0.csv").write_text(
                "\n".join(["time_ns,other_v", "0,0.91", "20,0.61", ""]),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["trace_validation"]["missing_trace_columns_by_ref"],
            {"source/traces/bias-0p0.csv": ["signal_v"]},
        )

    def test_trace_per_point_rejects_symlink_escape_before_reading(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "fixture"
            fixture.mkdir()
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            outside = Path(temp_dir) / "outside.csv"
            outside.write_text(
                "\n".join(["time_ns,signal_v", "0,999", ""]),
                encoding="utf-8",
            )
            trace_path = fixture / "source" / "traces" / "bias-0p0.csv"
            trace_path.unlink()
            trace_path.symlink_to(outside)

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["trace_validation"]["missing_trace_files"],
            ["source/traces/bias-0p0.csv"],
        )
        self.assertEqual(summary["trace_validation"]["trace_summaries"][0]["status"], "missing")

    def test_trace_per_point_reports_unresolvable_trace_path_as_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "fixture"
            fixture.mkdir()
            self._write_trace_fixture(
                fixture,
                "\n".join(
                    [
                        "bias_v,trace_ref,trace_kind",
                        "0.0,source/traces/bias-0p0.csv,ringdown",
                        "",
                    ]
                ),
            )
            trace_path = fixture / "source" / "traces" / "bias-0p0.csv"
            trace_path.unlink()
            trace_path.symlink_to(trace_path)

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["trace_validation"]["missing_trace_files"],
            ["source/traces/bias-0p0.csv"],
        )
        self.assertEqual(summary["trace_validation"]["trace_summaries"][0]["status"], "missing")

    def test_fixed_vector_rejects_ragged_cell_length(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        '0.12,"[0.08, 0.01, 0.02]",ground',
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["shape_failures"], 1)
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "shape_mismatch"
        )

    def test_fixed_vector_rejects_non_numeric_dtype(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, ""bad""]",ground',
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["dtype_failures"], 1)
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "dtype_mismatch"
        )

    def test_fixed_vector_rejects_duplicate_coordinates_without_plot_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        '0.10,"[0.08, 0.01]",ground',
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertTrue(summary["shape"]["duplicate_coordinates"])
        self.assertEqual(summary["vector_validation"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])

    def test_fixed_vector_rejects_unsupported_shape_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["shape_policy"] = "ragged_per_row"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["unsupported_shape_policies"],
            [{"column": "shot_iq", "shape_policy": "ragged_per_row"}],
        )

    def test_fixed_vector_rejects_multi_dimensional_value_shape(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03, 0.01, 0.02]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["value_shape"] = [2, 2]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["unsupported_value_shapes"],
            [{"column": "shot_iq", "value_shape": [2, 2]}],
        )

    def test_fixed_vector_rejects_missing_dtype(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            del source["data_shape"]["vector_columns"][0]["dtype"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["unsupported_dtypes"],
            [{"column": "shot_iq", "dtype": None}],
        )

    def test_fixed_vector_rejects_missing_components(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            del source["data_shape"]["vector_columns"][0]["components"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["unsupported_components"],
            [{"column": "shot_iq", "failure": "components_not_list", "components": None}],
        )

    def test_fixed_vector_rejects_null_components(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["components"] = None
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["unsupported_components"],
            [{"column": "shot_iq", "failure": "components_not_list", "components": None}],
        )

    def test_fixed_vector_rejects_empty_vector_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"] = []
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["missing_vector_columns"],
            ["vector_columns"],
        )

    def test_fixed_vector_rejects_missing_vector_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            del source["data_shape"]["vector_columns"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["missing_vector_columns"],
            ["vector_columns"],
        )
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["invalid_vector_columns"],
            [{"index": None, "failure": "vector_columns_not_list"}],
        )

    def test_fixed_vector_rejects_non_list_vector_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"] = {"name": "shot_iq"}
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["invalid_vector_columns"],
            [{"index": None, "failure": "vector_columns_not_list"}],
        )

    def test_fixed_vector_rejects_malformed_vector_column_entry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"] = [{"label": "nameless vector"}]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"]["invalid_vector_columns"],
            [{"index": 0, "failure": "vector_column_missing_name"}],
        )

    def test_fixed_vector_rejects_invalid_declared_roles(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["declared_columns"][0]["role"] = "annotation"
            source["declared_columns"][1]["role"] = "annotation"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["column_validation"]["invalid_axis_roles"], ["pulse_amplitude_v"])
        self.assertEqual(summary["column_validation"]["invalid_vector_roles"], ["shot_iq"])

    def test_fixed_vector_reports_parse_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12,",ground',
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["parse_failures"], 1)
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "malformed_json"
        )

    def test_fixed_vector_reports_missing_vector_cell(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        "0.10",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["parse_failures"], 1)
        self.assertEqual(summary["vector_validation"]["failed_cells"][0]["failure"], "not_string")
        self.assertIsNone(summary["vector_validation"]["failed_cells"][0]["value"])

    def test_fixed_vector_rejects_non_list_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        "0.10,0.12,ground",
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["parse_failures"], 1)
        self.assertEqual(summary["vector_validation"]["failed_cells"][0]["failure"], "not_list")

    def test_fixed_vector_rejects_non_finite_float(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[NaN, 0.12]",ground',
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["dtype_failures"], 1)
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "dtype_mismatch"
        )

    def test_fixed_vector_rejects_int32_out_of_range(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[2147483648, 0]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["dtype"] = "int32"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["dtype_failures"], 1)
        self.assertEqual(summary["plot_candidates"], [])

    def test_fixed_vector_rejects_float32_out_of_range(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[1e39, 0.12]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["dtype"] = "float32"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["dtype_failures"], 1)
        self.assertEqual(summary["plot_candidates"], [])

    def test_fixed_vector_reports_huge_integer_overflow_as_dtype_mismatch(self) -> None:
        huge_integer = "9" * 4000
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        f'0.10,"[{huge_integer}, 0.12]",ground',
                        "",
                    ]
                ),
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["vector_validation"]["column_summaries"][0]["dtype_failures"], 1)
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "dtype_mismatch"
        )
        self.assertEqual(summary["plot_candidates"], [])

    def test_complex_fixed_vector_rejects_unsupported_representation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_complex_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "readout_power_dbm,iq_v",
                        '-35,"[0.120, -0.030]"',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["logical_value"]["representation"] = (
                "polar_vector"
            )
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"][
                "unsupported_complex_logical_values"
            ],
            [{"column": "iq_v", "failure": "unsupported_representation"}],
        )

    def test_complex_fixed_vector_requires_logical_value(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_complex_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "readout_power_dbm,iq_v",
                        '-35,"[0.120, -0.030]"',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            del source["data_shape"]["vector_columns"][0]["logical_value"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"][
                "unsupported_complex_logical_values"
            ],
            [{"column": "iq_v", "failure": "missing_logical_value"}],
        )

    def test_complex_fixed_vector_requires_declared_components(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_complex_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "readout_power_dbm,iq_v",
                        '-35,"[0.120, -0.030]"',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["components"] = ["I", "aux"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"][
                "unsupported_complex_logical_values"
            ],
            [{"column": "iq_v", "failure": "complex_components_not_declared"}],
        )

    def test_complex_fixed_vector_rejects_extra_components(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_complex_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "readout_power_dbm,iq_v",
                        '-35,"[0.120, -0.030]"',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["components"] = ["I", "Q", "aux"]
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(summary["plot_candidates"], [])
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"][
                "unsupported_complex_logical_values"
            ],
            [{"column": "iq_v", "failure": "complex_requires_two_components"}],
        )

    def test_complex_fixed_vector_plot_uses_declared_real_imag_mapping(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_complex_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "readout_power_dbm,iq_v",
                        '-35,"[0.120, -0.030]"',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["components"] = ["Q", "I"]
            source["data_shape"]["vector_columns"][0]["logical_value"]["real_component"] = "I"
            source["data_shape"]["vector_columns"][0]["logical_value"]["imag_component"] = "Q"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "pass")
        self.assertEqual(summary["plot_candidates"][0]["x_component"], "I")
        self.assertEqual(summary["plot_candidates"][0]["y_component"], "Q")

    def test_complex_fixed_vector_rejects_logical_type_dtype_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_complex_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "readout_power_dbm,iq_v",
                        '-35,"[0.120, -0.030]"',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["dtype"] = "float32"
            source["data_shape"]["vector_columns"][0]["logical_value"]["type"] = "complex128"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"][
                "unsupported_complex_logical_values"
            ],
            [{"column": "iq_v", "failure": "logical_type_dtype_mismatch"}],
        )

    def test_complex_fixed_vector_accepts_complex64_float32(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_complex_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "readout_power_dbm,iq_v",
                        '-35,"[0.120, -0.030]"',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["dtype"] = "float32"
            source["data_shape"]["vector_columns"][0]["logical_value"]["type"] = "complex64"
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "pass")
        self.assertEqual(
            summary["vector_validation"]["column_summaries"][0]["logical_value"]["type"],
            "complex64",
        )

    def test_plain_fixed_vector_rejects_complex_logical_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            self._write_fixed_vector_fixture(
                fixture,
                "\n".join(
                    [
                        "pulse_amplitude_v,shot_iq,shot_state",
                        '0.10,"[0.12, -0.03]",ground',
                        "",
                    ]
                ),
            )
            source = json.loads((fixture / "shape-input.json").read_text(encoding="utf-8"))
            source["data_shape"]["vector_columns"][0]["logical_value"] = {
                "type": "complex128",
                "representation": "cartesian_vector",
                "real_component": "I",
                "imag_component": "Q",
                "derived_components": ["real", "imag", "magnitude", "phase"],
                "phase_unit": "rad",
            }
            (fixture / "shape-input.json").write_text(
                json.dumps(source, indent=2),
                encoding="utf-8",
            )

            summary = generate_summary(fixture)

        self.assertEqual(summary["shape"]["status"], "fail")
        self.assertEqual(
            summary["vector_validation"]["declaration_validation"][
                "unsupported_complex_logical_values"
            ],
            [{"column": "shot_iq", "failure": "complex_logical_value_requires_complex_shape"}],
        )


if __name__ == "__main__":
    unittest.main()

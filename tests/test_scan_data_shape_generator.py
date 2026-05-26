from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spikes.scan_data_shapes.generate import generate_review, generate_summary

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "scan_data_shapes"


class ScanDataShapeGeneratorTest(unittest.TestCase):
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
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "dtype_mismatch"
        )

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
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "malformed_json"
        )

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
        self.assertEqual(
            summary["vector_validation"]["failed_cells"][0]["failure"], "dtype_mismatch"
        )


if __name__ == "__main__":
    unittest.main()

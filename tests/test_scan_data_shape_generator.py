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


if __name__ == "__main__":
    unittest.main()

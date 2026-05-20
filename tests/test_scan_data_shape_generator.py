from __future__ import annotations

import json
import unittest
from pathlib import Path

from spikes.scan_data_shapes.generate import generate_review, generate_summary

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "scan_data_shapes"


class ScanDataShapeGeneratorTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

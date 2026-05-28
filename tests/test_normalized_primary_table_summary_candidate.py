from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.normalized_primary_table import summarize_normalized_csv_table

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "normalized_primary_table" / "basic_table"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_input() -> dict:
    return _load_json(FIXTURE / "table-input.json")


def _summarize(content: bytes | None = None, **overrides: object) -> dict:
    source = _fixture_input()
    source.update(overrides)
    if content is None:
        content = (FIXTURE / source["source"]).read_bytes()
    return summarize_normalized_csv_table(
        content,
        source=source["source"],
        declared_columns=source["declared_columns"],
        declared_row_count=source.get("declared_row_count"),
        preview_row_limit=source.get("preview_row_limit", 5),
    )


class NormalizedPrimaryTableSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_normalized_primary_table_summary(self) -> None:
        summary = _summarize()
        expected = _load_json(FIXTURE / "expected-normalized-primary-table-summary.json")[
            "candidate_summary"
        ]

        self.assertEqual(summary, expected)

    def test_extra_table_columns_are_available_but_not_preview_columns(self) -> None:
        summary = _summarize()

        self.assertEqual(
            [column["name"] for column in summary["columns"]],
            ["drive_frequency", "signal", "comment"],
        )
        self.assertEqual(summary["columns"][2]["declared"], False)
        self.assertEqual(
            set(summary["preview"]["rows"][0]),
            {"drive_frequency", "signal"},
        )

    def test_declared_row_count_mismatch_is_review_finding(self) -> None:
        summary = _summarize(declared_row_count=6)

        self.assertEqual(summary["classification"], "normalized_table_review_needed")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["normalized_table_row_count_mismatch"],
        )
        self.assertEqual(summary["row_count"], 5)

    def test_duplicate_csv_header_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique CSV headers"):
            _summarize(b"drive_frequency,signal,signal\n5.00,0.44,0.45\n")

    def test_blank_csv_header_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be non-blank"):
            _summarize(b"drive_frequency, \n5.00,0.44\n")

    def test_ragged_rows_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "rows must match the CSV header"):
            _summarize(b"drive_frequency,signal\n5.00,0.44,extra\n")
        with self.assertRaisesRegex(ValueError, "rows must match the CSV header"):
            _summarize(b"drive_frequency,signal\n5.00\n")

    def test_quoted_multiline_cells_are_preserved(self) -> None:
        summary = _summarize(b'drive_frequency,signal,comment\n5.00,0.44,"line 1\nline 2"\n')

        self.assertEqual(summary["rows"][0]["comment"], "line 1\nline 2")

    def test_missing_declared_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing declared columns"):
            _summarize(b"drive_frequency,comment\n5.00,start\n")

    def test_malformed_declared_columns_are_rejected(self) -> None:
        source = _fixture_input()
        source["declared_columns"] = [
            {
                "name": "drive_frequency",
                "role": "sweep_axis",
                "label": "Drive frequency",
                "unit": "GHz",
            },
            {
                "name": "drive_frequency",
                "role": "response",
                "label": "Duplicate",
                "unit": None,
            },
        ]

        with self.assertRaisesRegex(ValueError, "declared columns must be unique"):
            summarize_normalized_csv_table(
                (FIXTURE / source["source"]).read_bytes(),
                source=source["source"],
                declared_columns=source["declared_columns"],
                declared_row_count=source["declared_row_count"],
                preview_row_limit=source["preview_row_limit"],
            )

    def test_unsupported_declared_column_role_is_rejected(self) -> None:
        source = _fixture_input()
        source["declared_columns"][0]["role"] = "swep_axis"

        with self.assertRaisesRegex(ValueError, "role is unsupported"):
            summarize_normalized_csv_table(
                (FIXTURE / source["source"]).read_bytes(),
                source=source["source"],
                declared_columns=source["declared_columns"],
                declared_row_count=source["declared_row_count"],
                preview_row_limit=source["preview_row_limit"],
            )

    def test_non_utf8_csv_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be utf-8 CSV"):
            _summarize(b"\xff\xfe")

    def test_does_not_accept_filesystem_or_dataframe_authority(self) -> None:
        summary = _summarize()

        policy = summary["normalized_table_policy"]
        self.assertEqual(policy["file_observation"], "not_performed")
        self.assertEqual(policy["dataframe_adapter"], "not_invoked")
        self.assertEqual(policy["schema_inference"], "not_performed")
        self.assertEqual(policy["scan_shape_inference"], "not_performed")


if __name__ == "__main__":
    unittest.main()

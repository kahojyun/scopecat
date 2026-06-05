from __future__ import annotations

import json
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordNormalizedPrimaryColumnDeclaration,
    MeasurementRecordNormalizedPrimaryTableRequest,
    summarize_normalized_primary_table,
    summarize_normalized_primary_table_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "normalized_primary_table"
    / "basic_table"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_input() -> dict:
    return _load_json(FIXTURE / "table-input.json")


def _request(**overrides: object) -> MeasurementRecordNormalizedPrimaryTableRequest:
    source = _fixture_input()
    source.update(overrides)
    return MeasurementRecordNormalizedPrimaryTableRequest(
        source=source["source"],
        declared_columns=tuple(
            MeasurementRecordNormalizedPrimaryColumnDeclaration(**column)
            for column in source["declared_columns"]
        ),
        declared_row_count=source.get("declared_row_count"),
        preview_row_limit=source.get("preview_row_limit", 5),
    )


def _raw_source(**overrides: object) -> dict:
    source = _fixture_input()
    source.update(overrides)
    return {
        "source": source["source"],
        "declared_columns": [dict(column) for column in source["declared_columns"]],
        "declared_row_count": source.get("declared_row_count"),
        "preview_row_limit": source.get("preview_row_limit", 5),
    }


def _content() -> bytes:
    return (FIXTURE / _fixture_input()["source"]).read_bytes()


class MeasurementRecordNormalizedPrimaryTablePrototypeTest(unittest.TestCase):
    def test_typed_request_summarizes_declared_preview_table(self) -> None:
        run = summarize_normalized_primary_table_from_request(_request(), content=_content())

        self.assertEqual(run.classification, "normalized_table_ready")
        self.assertEqual(run.table["row_count"], 5)
        self.assertEqual(
            [column["name"] for column in run.table["columns"]],
            ["drive_frequency", "signal", "comment"],
        )
        self.assertEqual(run.table["columns"][0]["declared"], True)
        self.assertEqual(run.table["columns"][2]["declared"], False)
        self.assertEqual(run.table["preview"]["columns"], ["drive_frequency", "signal"])
        self.assertEqual(run.table["preview"]["rows"][0]["drive_frequency"], "5.00")
        self.assertEqual(
            set(run.table),
            {
                "normalized_table_schema",
                "classification",
                "source",
                "format",
                "columns",
                "declared_columns",
                "row_count",
                "declared_row_count",
                "rows",
                "preview",
                "review_findings",
            },
        )

    def test_declared_row_count_mismatch_is_review_finding(self) -> None:
        run = summarize_normalized_primary_table_from_request(
            _request(declared_row_count=6),
            content=_content(),
        )

        self.assertEqual(run.classification, "normalized_table_review_needed")
        self.assertEqual(
            [finding["code"] for finding in run.review_findings],
            ["normalized_table_row_count_mismatch"],
        )
        self.assertEqual(
            set(run.review_findings[0]),
            {"code", "severity", "target", "message"},
        )

    def test_missing_declared_preview_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing declared columns"):
            summarize_normalized_primary_table_from_request(
                _request(),
                content=b"drive_frequency,comment\n5.00,start\n",
            )

    def test_non_rectangular_csv_is_rejected_before_summary(self) -> None:
        with self.assertRaisesRegex(ValueError, "rows must match the CSV header"):
            summarize_normalized_primary_table_from_request(
                _request(),
                content=b"drive_frequency,signal\n5.00,0.44,extra\n",
            )

    def test_run_summary_uses_table_facts(self) -> None:
        summary = summarize_normalized_primary_table(
            _raw_source(),
            content=_content(),
        ).to_dict()

        self.assertEqual(
            set(summary),
            {"artifact_posture", "request", "table", "review_findings"},
        )
        self.assertEqual(summary["artifact_posture"], "local_normalized_primary_table_summary")
        self.assertEqual(summary["table"]["classification"], "normalized_table_ready")


if __name__ == "__main__":
    unittest.main()

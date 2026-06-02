from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordNormalizedPrimaryColumnDeclaration,
    MeasurementRecordNormalizedPrimaryTableRequest,
    summarize_normalized_primary_table,
    summarize_normalized_primary_table_from_request,
)
from scopecat.measurement_records.normalized_primary_table import (
    NORMALIZED_PRIMARY_TABLE_POLICY,
    NORMALIZED_PRIMARY_TABLE_REQUEST_SCHEMA,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "normalized_primary_table" / "basic_table"


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
        "normalized_table_request_schema": NORMALIZED_PRIMARY_TABLE_REQUEST_SCHEMA,
        "normalized_table_policy": copy.deepcopy(NORMALIZED_PRIMARY_TABLE_POLICY),
        "source": source["source"],
        "declared_columns": copy.deepcopy(source["declared_columns"]),
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
            run.table["normalized_table_policy"]["stable_public_api"],
            "route_local_engineering_prototype",
        )

    def test_raw_source_requires_matching_policy_boundary(self) -> None:
        source = _raw_source()
        source["normalized_table_policy"] = {
            **NORMALIZED_PRIMARY_TABLE_POLICY,
            "storage_mutation": "performed",
        }

        with self.assertRaisesRegex(ValueError, "policy"):
            summarize_normalized_primary_table(source, content=_content())

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

    def test_run_summary_keeps_local_non_claim_boundary(self) -> None:
        summary = summarize_normalized_primary_table(
            _raw_source(),
            content=_content(),
        ).to_dict()

        self.assertEqual(summary["artifact_posture"], "local_normalized_primary_table_summary")
        self.assertEqual(summary["workflow"]["classification"], "normalized_table_ready")
        self.assertIn("adapter_transport", summary["workflow"]["does_not_claim"])
        self.assertIn("storage_mutation", summary["workflow"]["does_not_claim"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records.durable_import import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRequest,
    read_created_record_primary_table_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "normalized_primary_table"
    / "basic_table"
    / "source"
    / "primary.csv"
)


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _read_request(**overrides: object) -> MeasurementRecordReadRequest:
    values = {
        "request_id": "read-primary-run-3101-rabi",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "preview_row_limit": 2,
    }
    values.update(overrides)
    return MeasurementRecordReadRequest(**values)


def _populate_record(storage_root: Path, content_root: Path) -> None:
    source_path = content_root / "source" / "primary.csv"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(SOURCE_FIXTURE.read_bytes())
    run = import_measurement_record_from_request(
        MeasurementRecordDurableImportRequest(
            request_id="import-run-3101-rabi",
            approval_state="approved",
            record_id="run-3101-rabi",
            record_dir="records/run-3101-rabi",
            primary_data_path="records/run-3101-rabi/primary.csv",
            writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
            finalization_receipt_path="records/run-3101-rabi/finalization-receipt.json",
            read_model_path="records/run-3101-rabi/record-read-model.json",
            import_source=MeasurementRecordImportSource(
                source_kind="fixture_normalized_primary_data",
                source_id="read-view-fixture",
                source_item_id="read-view-primary",
                content_ref="source/primary.csv",
                declared_digest=_digest(source_path),
                size_bytes=source_path.stat().st_size,
                rows_recorded=5,
            ),
            label="Stored Rabi run 3101",
            experiment_type="rabi_amplitude",
        ),
        content_root=content_root,
        storage_root=storage_root,
    )
    if not run.imported:
        raise AssertionError(run.to_dict())


class MeasurementRecordReadViewPrototypeTest(unittest.TestCase):
    def test_reads_primary_table_through_writer_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)

            run = read_created_record_primary_table_from_request(
                _read_request(),
                storage_root=storage_root,
            )
            creation_manifest = json.loads(
                (storage_root / "records" / "run-3101-rabi" / "record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(run.classification, "primary_table_ready")
        self.assertEqual(run.table["row_count"], 5)
        self.assertEqual(run.table["declared_row_count"], 5)
        self.assertEqual(
            set(run.table),
            {
                "table_schema",
                "source",
                "format",
                "classification",
                "columns",
                "row_count",
                "declared_row_count",
                "rows",
                "preview",
            },
        )
        self.assertEqual(
            [column["name"] for column in run.table["columns"]],
            ["drive_frequency", "signal", "comment"],
        )
        self.assertEqual(len(run.table["preview"]["rows"]), 2)
        self.assertEqual(run.table["preview"]["rows"][0]["drive_frequency"], "5.00")
        self.assertEqual(creation_manifest["primary_data"]["state"], "not_recorded")

        summary = run.to_dict()
        self.assertEqual(
            set(summary),
            {
                "artifact_posture",
                "classification",
                "request",
                "record_manifest",
                "writer_receipt",
                "table",
                "review_findings",
            },
        )
        self.assertEqual(summary["artifact_posture"], "local_record_read_view")
        self.assertEqual(summary["classification"], "primary_table_ready")
        self.assertEqual(
            summary["writer_receipt"]["primary_data_path"],
            "records/run-3101-rabi/primary.csv",
        )

    def test_requires_writer_receipt_record_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "writer-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["record"]["record_id"] = "other-record"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "record_id"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_primary_data_digest_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            primary_path.write_text("drive_frequency,signal,comment\n5.00,broken,start\n")

            with self.assertRaisesRegex(ValueError, "digest"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_missing_writer_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            (storage_root / "records" / "run-3101-rabi" / "writer-receipt.json").unlink()

            with self.assertRaisesRegex(ValueError, "writer receipt"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_writer_receipt_row_count_mismatch_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "writer-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["primary_data"]["rows_recorded"] = 4
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            run = read_created_record_primary_table_from_request(
                _read_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "primary_table_review_needed")
        self.assertEqual(
            [finding["code"] for finding in run.review_findings],
            ["primary_table_row_count_mismatch"],
        )

    def test_malformed_primary_csv_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            content = b"drive_frequency,signal,comment\n5.00,0.44,start,extra\n"
            primary_path.write_bytes(content)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "writer-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["primary_data"]["digest"] = f"sha256:{hashlib.sha256(content).hexdigest()}"
            receipt["primary_data"]["size_bytes"] = len(content)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "rows must match"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_symlink_primary_data_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            primary_path.unlink()
            primary_path.symlink_to(Path(temp_dir) / "external-primary.csv")

            with self.assertRaisesRegex(ValueError, "primary data must not be a symlink"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_read_request_writer_receipt_must_stay_under_record_dir(self) -> None:
        with self.assertRaisesRegex(ValueError, "writer_receipt_path"):
            _read_request(writer_receipt_path="outside/writer-receipt.json")


if __name__ == "__main__":
    unittest.main()

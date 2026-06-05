from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    LegacyPrimaryImportRequest,
    LegacyRunLocator,
    LegacyRunRecordRequest,
    MeasurementRecordImportSource,
    MeasurementRecordReadRequest,
    attach_converted_primary_data_to_legacy_record,
    attach_converted_primary_data_to_legacy_record_from_request,
    read_created_record_primary_table_from_request,
    record_legacy_measurement_run_from_request,
)

NORMALIZED_CSV = (
    b"time_s,signal_counts,detuning_mhz\n0.000,101,-2.0\n0.100,128,-1.0\n0.200,155,0.0\n"
)


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _write_source(content_root: Path, content: bytes = NORMALIZED_CSV) -> Path:
    path = content_root / "normalized" / "run-001.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return path


def _record_legacy(storage_root: Path) -> None:
    run = record_legacy_measurement_run_from_request(
        LegacyRunRecordRequest(
            request_id="record-legacy-run-001",
            approval_state="approved",
            record_id="legacy-run-001",
            record_dir="records/legacy-run-001",
            legacy_system_id="legacy-labview",
            legacy_run_id="lv-run-001",
            label="Legacy Run 001",
            experiment_type="rabi",
            locators=(
                LegacyRunLocator(
                    locator_id="legacy-primary",
                    kind="workspace_relative_path",
                    role="primary_data",
                    value="legacy/run-001.tsv",
                ),
            ),
        ),
        storage_root=storage_root,
    )
    if not run.recorded:
        raise AssertionError(run.to_dict())


def _request(**overrides: object) -> LegacyPrimaryImportRequest:
    values = {
        "request_id": "attach-legacy-primary-001",
        "approval_state": "approved",
        "record_id": "legacy-run-001",
        "record_dir": "records/legacy-run-001",
        "legacy_receipt_path": "records/legacy-run-001/legacy-run-receipt.json",
        "primary_data_path": "records/legacy-run-001/primary.csv",
        "writer_receipt_path": "records/legacy-run-001/writer-receipt.json",
        "finalization_receipt_path": "records/legacy-run-001/finalization-receipt.json",
        "read_model_path": "records/legacy-run-001/record-read-model.json",
        "import_source": MeasurementRecordImportSource(
            source_kind="adapter_normalized_primary_data",
            source_id="legacy-run-001",
            source_item_id="normalized-legacy-run-001",
            content_ref="normalized/run-001.csv",
            declared_digest=_digest(NORMALIZED_CSV),
            size_bytes=len(NORMALIZED_CSV),
            rows_recorded=3,
        ),
    }
    values.update(overrides)
    return LegacyPrimaryImportRequest(**values)


def _raw_source(**overrides: object) -> dict:
    return {
        "legacy_primary_import_request": _request(**overrides).to_dict(),
    }


class MeasurementRecordLegacyPrimaryImportPrototypeTest(unittest.TestCase):
    def test_attach_converted_primary_data_to_existing_legacy_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _record_legacy(storage_root)
            _write_source(content_root)

            run = attach_converted_primary_data_to_legacy_record_from_request(
                _request(),
                content_root=content_root,
                storage_root=storage_root,
            )
            record_dir = storage_root / "records" / "legacy-run-001"
            read_view = read_created_record_primary_table_from_request(
                MeasurementRecordReadRequest(
                    request_id="read-legacy-run-001",
                    record_id="legacy-run-001",
                    record_dir="records/legacy-run-001",
                    writer_receipt_path="records/legacy-run-001/writer-receipt.json",
                ),
                storage_root=storage_root,
            )
            self.assertTrue((record_dir / "legacy-run-receipt.json").exists())
            self.assertTrue((record_dir / "primary.csv").exists())
            self.assertTrue((record_dir / "writer-receipt.json").exists())
            self.assertTrue((record_dir / "finalization-receipt.json").exists())
            self.assertTrue((record_dir / "record-read-model.json").exists())

        self.assertEqual(run.classification, "attached_legacy_primary_data")
        self.assertTrue(run.attached)
        self.assertEqual(read_view.table["row_count"], 3)
        self.assertEqual(run.to_dict()["pipeline"]["projection"], "projected_read_model")

    def test_raw_source_attach_converted_primary_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _record_legacy(storage_root)
            _write_source(content_root)

            run = attach_converted_primary_data_to_legacy_record(
                _raw_source(),
                content_root=content_root,
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "attached_legacy_primary_data")

    def test_unapproved_attach_does_not_require_converted_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _record_legacy(storage_root)

            run = attach_converted_primary_data_to_legacy_record_from_request(
                _request(approval_state="needs_review"),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records" / "legacy-run-001" / "primary.csv").exists())

        self.assertEqual(run.classification, "blocked_before_legacy_primary_import")
        self.assertIsNone(run.import_error)
        self.assertEqual(run.to_dict()["classification"], "blocked_before_legacy_primary_import")

    def test_source_id_must_match_existing_legacy_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _record_legacy(storage_root)
            _write_source(content_root)

            run = attach_converted_primary_data_to_legacy_record_from_request(
                _request(
                    import_source=MeasurementRecordImportSource(
                        source_kind="adapter_normalized_primary_data",
                        source_id="other-legacy-run",
                        source_item_id="normalized-legacy-run-001",
                        content_ref="normalized/run-001.csv",
                        declared_digest=_digest(NORMALIZED_CSV),
                        size_bytes=len(NORMALIZED_CSV),
                        rows_recorded=3,
                    )
                ),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records" / "legacy-run-001" / "primary.csv").exists())

        self.assertEqual(run.classification, "blocked_before_legacy_primary_import")
        self.assertIn("source_id", run.import_error or "")

    def test_malformed_converted_csv_blocks_before_mutation(self) -> None:
        malformed_csv = b"time_s,signal_counts\n0.000\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _record_legacy(storage_root)
            _write_source(content_root, malformed_csv)

            run = attach_converted_primary_data_to_legacy_record_from_request(
                _request(
                    import_source=MeasurementRecordImportSource(
                        source_kind="adapter_normalized_primary_data",
                        source_id="legacy-run-001",
                        source_item_id="normalized-legacy-run-001",
                        content_ref="normalized/run-001.csv",
                        declared_digest=_digest(malformed_csv),
                        size_bytes=len(malformed_csv),
                        rows_recorded=1,
                    )
                ),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records" / "legacy-run-001" / "primary.csv").exists())

        self.assertEqual(run.classification, "blocked_before_legacy_primary_import")
        self.assertIn("rows must match", run.import_error or "")

    def test_projection_failure_rolls_back_attached_artifacts_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _record_legacy(storage_root)
            _write_source(content_root)
            record_dir = storage_root / "records" / "legacy-run-001"

            def failing_projection_writer(path: Path, content: bytes) -> None:
                path.write_bytes(content)
                raise RuntimeError("simulated projection failure")

            run = attach_converted_primary_data_to_legacy_record_from_request(
                _request(),
                content_root=content_root,
                storage_root=storage_root,
                projection_model_writer=failing_projection_writer,
            )

            self.assertTrue((record_dir / "record-manifest.json").exists())
            self.assertTrue((record_dir / "legacy-run-receipt.json").exists())
            self.assertFalse((record_dir / "primary.csv").exists())
            self.assertFalse((record_dir / "writer-receipt.json").exists())
            self.assertFalse((record_dir / "finalization-receipt.json").exists())
            self.assertFalse((record_dir / "record-read-model.json").exists())

        self.assertEqual(
            run.classification,
            "rolled_back_after_legacy_primary_import_failure",
        )
        self.assertTrue(run.rollback_performed)


if __name__ == "__main__":
    unittest.main()

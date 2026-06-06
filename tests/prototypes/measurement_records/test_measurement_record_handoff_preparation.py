from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordImportByIdRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_source_by_id,
)
from scopecat.measurement_records.handoff_preparation import (
    MeasurementRecordHandoffLinkedContextSelection,
    prepare_measurement_record_for_handoff,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNK_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "durable_import"
    / "basic_append"
)


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _import_request(record_id: str = "run-3101-rabi") -> MeasurementRecordImportByIdRequest:
    source_path = CHUNK_FIXTURE / "chunks" / "chunk-1.csv"
    return MeasurementRecordImportByIdRequest(
        request_id=f"import-{record_id}",
        approval_state="approved",
        record_id=record_id,
        import_source=MeasurementRecordImportSource(
            source_kind="adapter_normalized_primary_data",
            source_id="adapter-output-3101",
            source_item_id=f"primary-{record_id}",
            content_ref="chunks/chunk-1.csv",
            declared_digest=_digest(source_path),
            size_bytes=source_path.stat().st_size,
            rows_recorded=3,
            primary_data_format="csv_table",
        ),
        creation_source_kind="import",
        label="Imported Rabi run",
        experiment_type="rabi",
    )


def _create_imported_record(temp_root: Path) -> Path:
    storage_root = temp_root / "storage"
    content_root = temp_root / "content"
    storage_root.mkdir()
    shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
    run = import_measurement_record_from_source_by_id(
        _import_request(),
        content_root=content_root,
        storage_root=storage_root,
    )
    if not run.imported:
        raise AssertionError(run.to_dict())
    return storage_root


class MeasurementRecordHandoffPreparationTest(unittest.TestCase):
    def test_prepares_complete_record_without_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
            )

        self.assertTrue(run.prepared)
        self.assertIsNone(run.refresh_run)
        self.assertEqual(run.packageable_record.primary_data_row_count, 3)
        self.assertEqual(run.packageable_record.label, "Imported Rabi run")

    def test_refreshes_missing_read_model_before_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model_path.unlink()

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
            )

        self.assertTrue(run.prepared)
        self.assertEqual(run.initial_error, "record read model is required")
        self.assertEqual(run.refresh_run.classification, "refreshed_read_model")

    def test_refreshes_stale_read_model_before_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            read_model["primary_data"]["digest"] = (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
            read_model_path.write_text(json.dumps(read_model, indent=2), encoding="utf-8")

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
            )

        self.assertTrue(run.prepared)
        self.assertEqual(run.initial_error, "primary data digest must match writer receipt")
        self.assertEqual(run.refresh_run.classification, "refreshed_read_model")
        self.assertTrue(run.refresh_run.replacement_performed)

    def test_missing_finalization_receipt_blocks_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))
            record_dir = storage_root / "records" / "run-3101-rabi"
            (record_dir / "record-read-model.json").unlink()
            (record_dir / "finalization-receipt.json").unlink()

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
            )

        self.assertFalse(run.prepared)
        self.assertEqual(run.block_reason, "read_model_refresh_failed")
        self.assertIn("finalization receipt is required", run.preparation_error or "")

    def test_incomplete_read_model_is_not_packageable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            content = read_model_path.read_text(encoding="utf-8")
            read_model_path.write_text(
                content.replace('"lifecycle_state": "complete"', '"lifecycle_state": "failed"'),
                encoding="utf-8",
            )

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
            )

        self.assertFalse(run.prepared)
        self.assertEqual(run.block_reason, "record_not_complete")

    def test_primary_data_must_stay_under_record_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            content = read_model_path.read_text(encoding="utf-8")
            read_model_path.write_text(
                content.replace(
                    '"path": "records/run-3101-rabi/primary.csv"',
                    '"path": "records/other-run/primary.csv"',
                ),
                encoding="utf-8",
            )

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
            )

        self.assertFalse(run.prepared)
        self.assertEqual(run.block_reason, "record_path_scope_violation")

    def test_missing_writer_receipt_blocks_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))
            (storage_root / "records" / "run-3101-rabi" / "writer-receipt.json").unlink()

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
            )

        self.assertFalse(run.prepared)
        self.assertEqual(run.block_reason, "missing_record_evidence")

    def test_linked_context_payload_must_stay_under_record_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _create_imported_record(Path(temp_dir))

            run = prepare_measurement_record_for_handoff(
                "run-3101-rabi",
                storage_root=storage_root,
                linked_context_selection=(
                    MeasurementRecordHandoffLinkedContextSelection(
                        link_id="run-3101-parameter-state",
                        kind="parameter_state",
                        label="Reviewed parameter state",
                        relation="run_start_context",
                        reason="Attempt to package an out-of-record payload.",
                        source_path="records/other-run/parameter-state.json",
                        package_path="context/run-3101-parameter-state.json",
                        expected_digest=(
                            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                        ),
                        expected_size_bytes=10,
                    ),
                ),
            )

        self.assertFalse(run.prepared)
        self.assertEqual(run.block_reason, "record_path_scope_violation")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordReference,
    MeasurementRecordReferenceRequest,
    list_measurement_record_references,
    record_measurement_record_references_from_request,
)
from scopecat.measurement_records.durable_import import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "measurement_storage_writer"
    / "basic_append"
    / "chunks"
    / "chunk-1.csv"
)


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _create_record(storage_root: Path) -> None:
    content_root = storage_root.parent / "content"
    content_root.mkdir()
    source_path = content_root / "source" / "primary.csv"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(SOURCE_FIXTURE.read_bytes())
    run = import_measurement_record_from_request(
        MeasurementRecordDurableImportRequest(
            request_id="import-run-ctx",
            approval_state="approved",
            record_id="run-ctx-001",
            record_dir="records/run-ctx-001",
            primary_data_path="records/run-ctx-001/primary.csv",
            writer_receipt_path="records/run-ctx-001/writer-receipt.json",
            finalization_receipt_path="records/run-ctx-001/finalization-receipt.json",
            read_model_path="records/run-ctx-001/record-read-model.json",
            import_source=MeasurementRecordImportSource(
                source_kind="fixture_normalized_primary_data",
                source_id="reference-fixture",
                source_item_id="reference-primary",
                content_ref="source/primary.csv",
                declared_digest=_digest(source_path),
                size_bytes=source_path.stat().st_size,
                rows_recorded=3,
            ),
        ),
        content_root=content_root,
        storage_root=storage_root,
    )
    if not run.imported:
        raise AssertionError(run.to_dict())


def _references() -> tuple[MeasurementRecordReference, ...]:
    return (
        MeasurementRecordReference(
            reference_id="param-file-001",
            family="parameter_state",
            role="parameter_file",
            reference_kind="workspace_relative_path",
            reference_value="legacy-system/params/run-ctx-001.json",
            label="Legacy parameter file",
        ),
        MeasurementRecordReference(
            reference_id="setup-binding-001",
            family="setup_binding",
            role="setup_binding_file",
            reference_kind="workspace_relative_path",
            reference_value="legacy-system/setup/run-ctx-001.json",
            label="Setup binding file",
        ),
        MeasurementRecordReference(
            reference_id="code-dir-001",
            family="experiment_code",
            role="code_directory",
            reference_kind="workspace_relative_path",
            reference_value="legacy-system/code/rabi",
            label="Legacy acquisition code",
        ),
        MeasurementRecordReference(
            reference_id="analysis-summary-001",
            family="derived_artifact",
            role="preliminary_analysis_result",
            reference_kind="workspace_relative_path",
            reference_value="analysis/run-ctx-001/summary.csv",
            label="Initial fit summary",
            preview="contrast=0.82",
        ),
    )


def _request(**overrides: object) -> MeasurementRecordReferenceRequest:
    values = {
        "request_id": "record-references-run-ctx",
        "approval_state": "approved",
        "record_id": "run-ctx-001",
        "record_dir": "records/run-ctx-001",
        "reference_set_id": "references-set-001",
        "references": _references(),
        "operator_notes": "Recorded user-selected references.",
    }
    values.update(overrides)
    return MeasurementRecordReferenceRequest(**values)


def _source(**overrides: object) -> dict:
    return {
        "recorded_reference_request": _request(**overrides).to_dict(),
    }


class MeasurementRecordReferencePrototypeTest(unittest.TestCase):
    def test_records_references_without_rewriting_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)
            manifest_path = storage_root / "records" / "run-ctx-001" / "record-manifest.json"
            before = manifest_path.read_text(encoding="utf-8")

            run = record_measurement_record_references_from_request(
                _request(),
                storage_root=storage_root,
            )
            after = manifest_path.read_text(encoding="utf-8")
            receipt_path = (
                storage_root
                / "records"
                / "run-ctx-001"
                / "recorded-references"
                / "references-set-001.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            review = list_measurement_record_references(storage_root=storage_root)

        self.assertEqual(run.classification, "recorded_measurement_record_references")
        self.assertEqual(before, after)
        self.assertEqual(receipt["record"]["record_id"], "run-ctx-001")
        self.assertEqual(receipt["reference_set"]["reference_set_id"], "references-set-001")
        self.assertEqual(
            [references["role"] for references in receipt["references"]],
            [
                "parameter_file",
                "setup_binding_file",
                "code_directory",
                "preliminary_analysis_result",
            ],
        )
        self.assertEqual(
            review["classification"],
            "measurement_record_recorded_reference_review_ready",
        )
        self.assertEqual(review["entries"][0]["reference_count"], 4)

    def test_unapproved_request_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)

            run = record_measurement_record_references_from_request(
                _request(approval_state="needs_review"),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "blocked_before_recorded_reference")
        self.assertFalse(
            (
                storage_root
                / "records"
                / "run-ctx-001"
                / "recorded-references"
                / "references-set-001.json"
            ).exists()
        )

    def test_second_receipt_can_declare_previous_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)
            first = record_measurement_record_references_from_request(
                _request(),
                storage_root=storage_root,
            )
            second = record_measurement_record_references_from_request(
                _request(
                    request_id="record-references-run-ctx-2",
                    reference_set_id="references-set-002",
                    previous_reference_receipt_path=(
                        "records/run-ctx-001/recorded-references/references-set-001.json"
                    ),
                ),
                storage_root=storage_root,
            )
            review = list_measurement_record_references(storage_root=storage_root)

        self.assertTrue(first.recorded)
        self.assertTrue(second.recorded)
        self.assertEqual(len(review["entries"]), 2)
        self.assertEqual(
            review["entries"][1]["reference_set"]["previous_reference_receipt"]["path"],
            "records/run-ctx-001/recorded-references/references-set-001.json",
        )

    def test_receipt_collision_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)
            first = record_measurement_record_references_from_request(
                _request(),
                storage_root=storage_root,
            )
            second = record_measurement_record_references_from_request(
                _request(request_id="record-references-run-ctx-again"),
                storage_root=storage_root,
            )

        self.assertTrue(first.recorded)
        self.assertEqual(second.classification, "blocked_before_recorded_reference")
        self.assertIn("already exists", second.to_dict()["receipt"]["references_error"])


if __name__ == "__main__":
    unittest.main()

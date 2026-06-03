from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import (
    HandoffDurableImportDestination,
    HandoffDurableImportRequest,
    HandoffImportPlanRequest,
    HandoffReceivingReviewRequest,
    SelectedMeasurementRecordExportRequest,
    export_selected_measurement_record_from_request,
    open_package,
    run_handoff_durable_import_from_plan,
)
from scopecat.handoff.import_plan import build_import_plan
from scopecat.handoff.receiving import run_receiving_gate_from_request
from scopecat.measurement_records import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNK_FIXTURE = ROOT / "tests" / "fixtures" / "measurement_storage_writer" / "basic_append"


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _source_import_request() -> MeasurementRecordDurableImportRequest:
    source_path = CHUNK_FIXTURE / "chunks" / "chunk-1.csv"
    return MeasurementRecordDurableImportRequest(
        request_id="import-source-run-3101",
        approval_state="approved",
        record_id="run-3101-rabi",
        record_dir="records/run-3101-rabi",
        primary_data_path="records/run-3101-rabi/primary.csv",
        writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
        finalization_receipt_path="records/run-3101-rabi/finalization-receipt.json",
        read_model_path="records/run-3101-rabi/record-read-model.json",
        import_source=MeasurementRecordImportSource(
            source_kind="adapter_normalized_primary_data",
            source_id="adapter-output-3101",
            source_item_id="primary-3101-rabi",
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


def _preview_metadata() -> dict:
    return {
        "status": "preview_ready",
        "metadata_authority": "scopecat_export_manifest",
        "data_shape": {
            "kind": "declared_1d_table",
            "axis_order": ["drive_amplitude", "excited_state_probability"],
        },
        "declared_columns": [
            {
                "name": "drive_amplitude",
                "role": "sweep_axis",
                "label": "Drive amplitude",
                "unit": "a.u.",
            },
            {
                "name": "excited_state_probability",
                "role": "response",
                "label": "Excited state probability",
                "unit": "probability",
            },
        ],
        "plot_candidates": [
            {
                "x": "drive_amplitude",
                "y": "excited_state_probability",
                "source": "measurements/run-3101-rabi/primary.csv",
            }
        ],
    }


def _export_request() -> SelectedMeasurementRecordExportRequest:
    return SelectedMeasurementRecordExportRequest(
        request_id="export-run-3101-rabi",
        approval_state="approved",
        package_id="handoff-package-run-3101-rabi",
        display_name="Run 3101 selected measurement handoff",
        source_export_summary_id="export-summary-run-3101-rabi",
        display_path="HANDOFF_PACKAGE:/redacted/run-3101-rabi",
        record_id="run-3101-rabi",
        record_dir="records/run-3101-rabi",
        read_model_path="records/run-3101-rabi/record-read-model.json",
        legacy_data_id=3101,
        target="qA",
        declared_preview_metadata=_preview_metadata(),
    )


def _receiving_request(
    package_id: str, preview_classification: str
) -> HandoffReceivingReviewRequest:
    return HandoffReceivingReviewRequest(
        request_id="receive-run-3101-rabi",
        reviewed_package_id=package_id,
        reviewed_preview_classification=preview_classification,
        reviewed_integrity_classification="declared_integrity_verified",
    )


def _import_plan_request(package_id: str) -> HandoffImportPlanRequest:
    return HandoffImportPlanRequest(
        request_id="plan-import-run-3101-rabi",
        requested_package_id=package_id,
        measurement_selection="selected_measurements",
        requested_measurement_ids=("run-3101-rabi",),
    )


def _durable_import_request(package_id: str) -> HandoffDurableImportRequest:
    return HandoffDurableImportRequest(
        request_id="durably-import-run-3101-rabi",
        approval_state="approved",
        requested_package_id=package_id,
        measurement_record_id="run-3101-rabi",
        destination=HandoffDurableImportDestination(
            record_id="received-run-3101-rabi",
            record_dir="records/received-run-3101-rabi",
            primary_data_path="records/received-run-3101-rabi/primary.csv",
            writer_receipt_path="records/received-run-3101-rabi/writer-receipt.json",
            finalization_receipt_path="records/received-run-3101-rabi/finalization-receipt.json",
            read_model_path="records/received-run-3101-rabi/record-read-model.json",
        ),
    )


class HandoffJny001SingleMeasurementWorkflowTest(unittest.TestCase):
    """Integration/workflow coverage for the JNY-001 single-measurement path."""

    def test_single_measurement_handoff_runs_from_source_storage_to_receiving_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_storage = temp_root / "source-storage"
            source_content = temp_root / "source-content"
            package_root = temp_root / "packages"
            receiving_storage = temp_root / "receiving-storage"
            source_storage.mkdir()
            package_root.mkdir()
            receiving_storage.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", source_content / "chunks")

            source_import = import_measurement_record_from_request(
                _source_import_request(),
                content_root=source_content,
                storage_root=source_storage,
            )
            export_run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=source_storage,
                package_root=package_root,
            )
            package_dir = package_root / "handoff-package-run-3101-rabi"
            package = open_package(package_dir)
            receiving_gate = run_receiving_gate_from_request(
                _receiving_request(
                    package.package_id,
                    package.preview_classification,
                ),
                package_dir=package_dir,
            )
            import_plan = build_import_plan(
                _import_plan_request(package.package_id),
                receiving_gate=receiving_gate,
            )
            durable_import = run_handoff_durable_import_from_plan(
                _durable_import_request(package.package_id),
                import_plan=import_plan,
                storage_root=receiving_storage,
            )
            received_read_model = json.loads(
                (
                    receiving_storage
                    / "records"
                    / "received-run-3101-rabi"
                    / "record-read-model.json"
                ).read_text(encoding="utf-8")
            )

        self.assertTrue(source_import.imported)
        self.assertTrue(export_run.exported)
        self.assertEqual(package.measurement_ids, ("run-3101-rabi",))
        self.assertTrue(receiving_gate.acceptance_allowed)
        self.assertTrue(import_plan.import_plan_allowed)
        self.assertEqual(durable_import.classification, "imported_handoff_measurement_record")
        self.assertEqual(received_read_model["record"]["lifecycle_state"], "complete")
        self.assertEqual(received_read_model["record"]["record_id"], "received-run-3101-rabi")
        self.assertEqual(received_read_model["primary_data"]["observed_row_count"], 3)


if __name__ == "__main__":
    unittest.main()

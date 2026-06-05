from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import (
    HandoffArchiveCreationRequest,
    HandoffArchiveMaterializationRequest,
    HandoffDurableImportDestination,
    HandoffDurableImportRequest,
    HandoffImportPlanRequest,
    HandoffReceivingReviewRequest,
    SelectedMeasurementRecordExportRequest,
    create_handoff_archive_package_from_request,
    export_selected_measurement_record_from_request,
    materialize_handoff_archive_package_from_request,
    open_package,
    run_handoff_durable_import_from_plan,
    summarize_handoff_durable_import_receipt,
)
from scopecat.handoff.import_plan import build_import_plan
from scopecat.handoff.receiving import run_receiving_gate_from_request
from scopecat.measurement_records import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNK_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "measurement_storage_writer"
    / "basic_append"
)


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


def _archive_creation_request() -> HandoffArchiveCreationRequest:
    return HandoffArchiveCreationRequest(
        request_id="create-archive-run-3101-rabi",
        approval_state="approved",
        package_dir="handoff-package-run-3101-rabi",
        archive_path="handoff-package-run-3101-rabi.zip",
    )


def _archive_materialization_request() -> HandoffArchiveMaterializationRequest:
    return HandoffArchiveMaterializationRequest(
        request_id="materialize-archive-run-3101-rabi",
        approval_state="approved",
        archive_path="handoff-package-run-3101-rabi.zip",
        package_dir="handoff-package-run-3101-rabi",
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

    def _prepare_ready_handoff(self, temp_root: Path) -> dict[str, object]:
        source_storage = temp_root / "source-storage"
        source_content = temp_root / "source-content"
        package_root = temp_root / "packages"
        archive_root = temp_root / "archives"
        materialization_root = temp_root / "materialized-packages"
        receiving_storage = temp_root / "receiving-storage"
        source_storage.mkdir()
        package_root.mkdir()
        archive_root.mkdir()
        materialization_root.mkdir()
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
        archive_creation = create_handoff_archive_package_from_request(
            _archive_creation_request(),
            package_root=package_root,
            archive_root=archive_root,
        )
        archive_materialization = materialize_handoff_archive_package_from_request(
            _archive_materialization_request(),
            archive_root=archive_root,
            materialization_root=materialization_root,
        )
        package_dir = materialization_root / "handoff-package-run-3101-rabi"
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
        return {
            "source_import": source_import,
            "export_run": export_run,
            "archive_creation": archive_creation,
            "archive_materialization": archive_materialization,
            "source_storage": source_storage,
            "package_root": package_root,
            "source_package_dir": package_root / "handoff-package-run-3101-rabi",
            "archive_root": archive_root,
            "materialization_root": materialization_root,
            "package_dir": package_dir,
            "package": package,
            "receiving_gate": receiving_gate,
            "import_plan": import_plan,
            "receiving_storage": receiving_storage,
        }

    def test_single_measurement_handoff_runs_from_source_storage_to_receiving_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            package = workflow["package"]
            import_plan = workflow["import_plan"]
            receiving_storage = workflow["receiving_storage"]
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

        self.assertTrue(workflow["source_import"].imported)
        self.assertTrue(workflow["export_run"].exported)
        self.assertTrue(workflow["archive_creation"].created)
        self.assertTrue(workflow["archive_materialization"].materialized)
        self.assertEqual(package.measurement_ids, ("run-3101-rabi",))
        self.assertTrue(workflow["receiving_gate"].acceptance_allowed)
        self.assertTrue(import_plan.import_plan_allowed)
        self.assertEqual(durable_import.classification, "imported_handoff_measurement_record")
        self.assertEqual(received_read_model["record"]["lifecycle_state"], "complete")
        self.assertEqual(received_read_model["record"]["record_id"], "received-run-3101-rabi")
        self.assertEqual(received_read_model["primary_data"]["observed_row_count"], 3)

    def test_workflow_creates_and_materializes_zip_transport(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            source_package_dir = workflow["source_package_dir"]
            package_root = workflow["package_root"]
            package_dir = workflow["package_dir"]
            archive_root = workflow["archive_root"]
            materialization_root = workflow["materialization_root"]
            export_summary = workflow["export_run"].to_dict()
            creation_summary = workflow["archive_creation"].to_dict()
            materialization_summary = workflow["archive_materialization"].to_dict()
            receiving_summary = workflow["receiving_gate"].to_dict()
            import_plan_summary = workflow["import_plan"].to_dict()
            package_root_entries = sorted(path.name for path in package_root.iterdir())

            self.assertTrue(source_package_dir.is_dir())
            self.assertTrue(package_dir.is_dir())
            self.assertTrue((package_dir / "package-manifest.json").is_file())
            self.assertTrue((archive_root / "handoff-package-run-3101-rabi.zip").is_file())
            self.assertEqual(
                sorted(path.name for path in materialization_root.iterdir()),
                ["handoff-package-run-3101-rabi"],
            )

        self.assertEqual(package_root_entries, ["handoff-package-run-3101-rabi"])
        self.assertEqual(
            export_summary["package_write"]["package"]["classification"],
            "package_written_ready_for_transfer_review",
        )
        self.assertEqual(creation_summary["classification"], "created_zip_transport_archive")
        self.assertEqual(
            materialization_summary["classification"],
            "materialized_dec010_package_from_archive",
        )
        self.assertEqual(receiving_summary["classification"], "ready_for_acceptance_mutation")
        self.assertEqual(
            import_plan_summary["classification"],
            "ready_for_import_acceptance_decision",
        )

    def test_workflow_treats_package_integrity_as_external_authenticity_agnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            package = workflow["package"]
            import_plan = workflow["import_plan"]
            receiving_storage = workflow["receiving_storage"]
            durable_import = run_handoff_durable_import_from_plan(
                _durable_import_request(package.package_id),
                import_plan=import_plan,
                storage_root=receiving_storage,
            )
            export_summary = workflow["export_run"].to_dict()
            integrity_summary = workflow["receiving_gate"].integrity_report.to_dict()
            durable_import_summary = durable_import.to_dict()

        self.assertEqual(export_summary["classification"], "exported_selected_measurement_record")
        self.assertEqual(integrity_summary["classification"], "declared_integrity_verified")
        self.assertEqual(
            durable_import_summary["classification"],
            "imported_handoff_measurement_record",
        )

    def test_export_collision_blocks_without_rewriting_existing_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))

            second_export = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=workflow["source_storage"],
                package_root=workflow["package_root"],
            )
            package = open_package(workflow["package_dir"])

        self.assertEqual(second_export.classification, "blocked_before_export")
        self.assertIn("target already exists", second_export.export_error or "")
        self.assertEqual(package.measurement_ids, ("run-3101-rabi",))

    def test_export_blocks_when_record_receipt_evidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            new_package_root = Path(temp_dir) / "new-packages"
            new_package_root.mkdir()
            writer_receipt = (
                workflow["source_storage"] / "records" / "run-3101-rabi" / "writer-receipt.json"
            )
            writer_receipt.unlink()

            export_run = export_selected_measurement_record_from_request(
                SelectedMeasurementRecordExportRequest(
                    **{
                        **_export_request().to_dict(),
                        "package_id": "handoff-package-run-3101-rabi-retry",
                        "display_path": "HANDOFF_PACKAGE:/redacted/run-3101-rabi-retry",
                    }
                ),
                storage_root=workflow["source_storage"],
                package_root=new_package_root,
            )

            self.assertFalse((new_package_root / "handoff-package-run-3101-rabi-retry").exists())

        self.assertEqual(export_run.classification, "blocked_before_export")
        self.assertIn("writer receipt is required", export_run.export_error or "")

    def test_export_blocks_when_read_model_disagrees_with_source_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            new_package_root = Path(temp_dir) / "new-packages"
            new_package_root.mkdir()
            read_model_path = (
                workflow["source_storage"] / "records" / "run-3101-rabi" / "record-read-model.json"
            )
            read_model = read_model_path.read_text(encoding="utf-8")
            read_model_path.write_text(
                read_model.replace(
                    '"digest": "sha256:',
                    '"digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000',
                    1,
                ),
                encoding="utf-8",
            )

            export_run = export_selected_measurement_record_from_request(
                SelectedMeasurementRecordExportRequest(
                    **{
                        **_export_request().to_dict(),
                        "package_id": "handoff-package-run-3101-rabi-stale",
                        "display_path": "HANDOFF_PACKAGE:/redacted/run-3101-rabi-stale",
                    }
                ),
                storage_root=workflow["source_storage"],
                package_root=new_package_root,
            )

            self.assertFalse((new_package_root / "handoff-package-run-3101-rabi-stale").exists())

        self.assertEqual(export_run.classification, "blocked_before_export")
        self.assertIn("digest must match writer receipt", export_run.export_error or "")

    def test_corrupted_package_bytes_block_receiving_and_keep_storage_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            package_dir = workflow["package_dir"]
            primary_path = package_dir / "measurements" / "run-3101-rabi" / "primary.csv"
            primary_path.write_text(
                "drive_amplitude,excited_state_probability\n0.00,0.03\n0.25,0.18\n0.50,0.51\n",
                encoding="utf-8",
            )
            package = open_package(package_dir)

            receiving_gate = run_receiving_gate_from_request(
                HandoffReceivingReviewRequest(
                    request_id="receive-run-3101-rabi-corrupted",
                    reviewed_package_id=package.package_id,
                    reviewed_preview_classification=package.preview_classification,
                    reviewed_integrity_classification="integrity_review_required",
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
                storage_root=workflow["receiving_storage"],
            )

            self.assertFalse((workflow["receiving_storage"] / "records").exists())

        self.assertFalse(receiving_gate.acceptance_allowed)
        self.assertFalse(import_plan.import_plan_allowed)
        self.assertEqual(durable_import.classification, "blocked_before_handoff_durable_import")

    def test_receiving_review_mismatch_is_rejected_before_import_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            package = workflow["package"]

            with self.assertRaisesRegex(ValueError, "reviewed package id"):
                run_receiving_gate_from_request(
                    HandoffReceivingReviewRequest(
                        request_id="receive-run-3101-rabi-mismatch",
                        reviewed_package_id="different-package-id",
                        reviewed_preview_classification=package.preview_classification,
                        reviewed_integrity_classification="declared_integrity_verified",
                    ),
                    package_dir=workflow["package_dir"],
                )

    def test_import_summary_reports_destination_conflict_without_authorizing_retry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = self._prepare_ready_handoff(Path(temp_dir))
            package = workflow["package"]
            receiving_storage = workflow["receiving_storage"]
            (receiving_storage / "records" / "received-run-3101-rabi").mkdir(parents=True)

            durable_import = run_handoff_durable_import_from_plan(
                _durable_import_request(package.package_id),
                import_plan=workflow["import_plan"],
                storage_root=receiving_storage,
            )
            summary = summarize_handoff_durable_import_receipt(durable_import.to_dict())

        self.assertEqual(durable_import.classification, "blocked_before_handoff_durable_import")
        self.assertEqual(summary.block_reason, "durable_import_blocked_before_import")


if __name__ == "__main__":
    unittest.main()

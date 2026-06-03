from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scopecat.handoff import (
    SELECTED_RECORD_EXPORT_POLICY,
    SelectedMeasurementRecordExportLinkedContext,
    SelectedMeasurementRecordExportRequest,
    export_selected_measurement_record,
    export_selected_measurement_record_from_request,
    observe_package_integrity,
    open_package,
)
from scopecat.measurement_records import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNK_FIXTURE = ROOT / "tests" / "fixtures" / "measurement_storage_writer" / "basic_append"


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _import_request() -> MeasurementRecordDurableImportRequest:
    source_path = CHUNK_FIXTURE / "chunks" / "chunk-1.csv"
    return MeasurementRecordDurableImportRequest(
        request_id="import-rabi-3101",
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
        linked_context=(
            SelectedMeasurementRecordExportLinkedContext(
                link_id="run-3101-parameter-state",
                kind="parameter_state",
                label="Reviewed parameter state",
                relation="run_start_context",
                reason=(
                    "The selected record exposes this context as reference-only; "
                    "payload packaging was not requested for this package."
                ),
                context_reference={
                    "reference_id": "parameter-state-run-3101",
                    "reference_kind": "parameter_state",
                    "reference_family": "parameter_state",
                    "materialization": "reference_only",
                    "payload_import": "not_performed",
                },
            ),
        ),
    )


class HandoffSelectedRecordExportPrototypeTest(unittest.TestCase):
    def _create_imported_record(self, temp_root: Path) -> tuple[Path, Path]:
        storage_root = temp_root / "storage"
        content_root = temp_root / "content"
        package_root = temp_root / "packages"
        storage_root.mkdir()
        package_root.mkdir()
        shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

        import_run = import_measurement_record_from_request(
            _import_request(),
            content_root=content_root,
            storage_root=storage_root,
        )
        self.assertTrue(import_run.imported)
        return storage_root, package_root

    def test_exports_selected_stored_record_to_openable_handoff_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))

            run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )
            package = open_package(package_root / "handoff-package-run-3101-rabi")

        self.assertTrue(run.exported)
        self.assertEqual(run.classification, "exported_selected_measurement_record")
        self.assertEqual(package.measurement_ids, ("run-3101-rabi",))
        measurement = package.measurement("run-3101-rabi")
        self.assertEqual(measurement.label, "Imported Rabi run")
        self.assertEqual(measurement.primary_table.row_count, 3)
        self.assertEqual(
            [
                (series.x_name, series.y_name, len(series.points))
                for series in measurement.plot_series
            ],
            [("drive_amplitude", "excited_state_probability", 3)],
        )
        self.assertEqual(measurement.linked_context[0].materialization, "reference_only")
        payload = run.to_dict()
        self.assertEqual(payload["artifact_posture"], "local_selected_record_export_receipt")
        self.assertEqual(
            payload["selected_record_export_policy"]["record_storage_mutation"],
            "not_performed",
        )
        self.assertEqual(
            payload["package_write"]["package"]["classification"],
            "package_written_ready_for_transfer_review",
        )

    def test_raw_source_entrypoint_uses_explicit_export_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            source = {
                "selected_record_export_policy": SELECTED_RECORD_EXPORT_POLICY,
                "selected_record_export_request": _export_request().to_dict(),
            }

            run = export_selected_measurement_record(
                source,
                storage_root=storage_root,
                package_root=package_root,
            )

        self.assertTrue(run.exported)

    def test_exports_declared_record_local_linked_context_payload(self) -> None:
        context_content = b'{"attenuation_db":"12"}\n'
        context_digest = f"sha256:{hashlib.sha256(context_content).hexdigest()}"
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            context_path = storage_root / "records" / "run-3101-rabi" / "parameter-state.json"
            context_path.write_bytes(context_content)
            request = replace(
                _export_request(),
                linked_context=(
                    SelectedMeasurementRecordExportLinkedContext(
                        link_id="run-3101-parameter-state",
                        kind="parameter_state",
                        label="Reviewed parameter state",
                        relation="run_start_context",
                        reason="Packaged from explicit record-local linked payload.",
                        source_path="records/run-3101-rabi/parameter-state.json",
                        package_path="context/run-3101-parameter-state.json",
                        expected_digest=context_digest,
                        expected_size_bytes=len(context_content),
                        context_reference={
                            "reference_id": "parameter-state-run-3101",
                            "reference_kind": "parameter_state",
                            "reference_family": "parameter_state",
                            "materialization": "reference_only",
                            "payload_import": "not_performed",
                        },
                    ),
                ),
            )

            run = export_selected_measurement_record_from_request(
                request,
                storage_root=storage_root,
                package_root=package_root,
            )
            package_dir = package_root / "handoff-package-run-3101-rabi"
            package = open_package(package_dir)
            integrity_report = observe_package_integrity(package_dir)

        context = package.linked_context[0].to_dict()
        observations = {
            member.package_path: member.to_dict() for member in integrity_report.member_observations
        }
        receipt_summary = run.to_dict()

        self.assertTrue(run.exported)
        self.assertEqual(context["materialization"], "packaged_payload")
        self.assertEqual(context["package_path"], "context/run-3101-parameter-state.json")
        self.assertEqual(context["declared_digest"], context_digest)
        self.assertEqual(context["declared_size_bytes"], len(context_content))
        self.assertEqual(integrity_report.classification, "declared_integrity_verified")
        self.assertEqual(
            observations["context/run-3101-parameter-state.json"]["comparison"],
            "verified",
        )
        self.assertIn(
            {
                "path": "handoff-package-run-3101-rabi/context/run-3101-parameter-state.json",
                "kind": "linked_context",
                "result": "written",
                "bytes_written": len(context_content),
                "digest": context_digest,
                "does_not_claim": "linked_context_payload_import_or_reference_resolution",
            },
            receipt_summary["package_write"]["write_results"],
        )

    def test_export_rejects_linked_context_payload_outside_selected_record_dir(self) -> None:
        context_content = b'{"attenuation_db":"12"}\n'
        context_digest = f"sha256:{hashlib.sha256(context_content).hexdigest()}"
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            outside_path = storage_root / "records" / "other-run" / "parameter-state.json"
            outside_path.parent.mkdir()
            outside_path.write_bytes(context_content)

            with self.assertRaisesRegex(ValueError, "must stay under record_dir"):
                replace(
                    _export_request(),
                    linked_context=(
                        SelectedMeasurementRecordExportLinkedContext(
                            link_id="run-3101-parameter-state",
                            kind="parameter_state",
                            label="Reviewed parameter state",
                            relation="run_start_context",
                            reason="Attempt to package an out-of-record payload.",
                            source_path="records/other-run/parameter-state.json",
                            package_path="context/run-3101-parameter-state.json",
                            expected_digest=context_digest,
                            expected_size_bytes=len(context_content),
                        ),
                    ),
                )

    def test_unapproved_export_does_not_write_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            request = replace(_export_request(), approval_state="needs_review")

            run = export_selected_measurement_record_from_request(
                request,
                storage_root=storage_root,
                package_root=package_root,
            )

            self.assertFalse((package_root / "handoff-package-run-3101-rabi").exists())

        self.assertFalse(run.exported)
        self.assertIsNone(run.package_write)

    def test_export_requires_complete_read_model_before_package_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            content = read_model_path.read_text(encoding="utf-8")
            read_model_path.write_text(
                content.replace('"lifecycle_state": "complete"', '"lifecycle_state": "failed"'),
                encoding="utf-8",
            )

            run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

            self.assertFalse((package_root / "handoff-package-run-3101-rabi").exists())

        self.assertEqual(run.classification, "blocked_before_export")
        self.assertIn("requires complete", run.export_error or "")

    def test_export_rejects_primary_data_outside_selected_record_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            content = read_model_path.read_text(encoding="utf-8")
            read_model_path.write_text(
                content.replace(
                    '"path": "records/run-3101-rabi/primary.csv"',
                    '"path": "records/other-run/primary.csv"',
                ),
                encoding="utf-8",
            )

            run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

            self.assertFalse((package_root / "handoff-package-run-3101-rabi").exists())

        self.assertEqual(run.classification, "blocked_before_export")
        self.assertIn("must stay under record_dir", run.export_error or "")


if __name__ == "__main__":
    unittest.main()

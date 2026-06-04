from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scopecat.handoff import (
    SELECTED_RECORD_EXPORT_POLICY,
    SelectedMeasurementRecordBatchExportRecord,
    SelectedMeasurementRecordBatchExportRequest,
    SelectedMeasurementRecordExportLinkedContext,
    SelectedMeasurementRecordExportRequest,
    export_selected_measurement_record,
    export_selected_measurement_record_batch,
    export_selected_measurement_record_batch_from_request,
    export_selected_measurement_record_from_request,
    export_selected_measurement_record_with_preflight_refresh,
    observe_package_integrity,
    open_package,
)
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


def _import_request(
    *,
    record_id: str = "run-3101-rabi",
    record_dir: str = "records/run-3101-rabi",
    legacy_data_id: int = 3101,
    target_label: str = "Imported Rabi run",
) -> MeasurementRecordDurableImportRequest:
    source_path = CHUNK_FIXTURE / "chunks" / "chunk-1.csv"
    return MeasurementRecordDurableImportRequest(
        request_id=f"import-{record_id}",
        approval_state="approved",
        record_id=record_id,
        record_dir=record_dir,
        primary_data_path=f"{record_dir}/primary.csv",
        writer_receipt_path=f"{record_dir}/writer-receipt.json",
        finalization_receipt_path=f"{record_dir}/finalization-receipt.json",
        read_model_path=f"{record_dir}/record-read-model.json",
        import_source=MeasurementRecordImportSource(
            source_kind="adapter_normalized_primary_data",
            source_id=f"adapter-output-{legacy_data_id}",
            source_item_id=f"primary-{record_id}",
            content_ref="chunks/chunk-1.csv",
            declared_digest=_digest(source_path),
            size_bytes=source_path.stat().st_size,
            rows_recorded=3,
            primary_data_format="csv_table",
        ),
        creation_source_kind="import",
        label=target_label,
        experiment_type="rabi",
    )


def _preview_metadata(*, record_id: str = "run-3101-rabi") -> dict:
    primary_path = f"measurements/{record_id}/primary.csv"
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
                "source": primary_path,
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
        declared_preview_metadata=_preview_metadata(record_id="run-3101-rabi"),
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

    def _create_two_imported_records(self, temp_root: Path) -> tuple[Path, Path]:
        storage_root, package_root = self._create_imported_record(temp_root)
        content_root = temp_root / "content"
        import_run = import_measurement_record_from_request(
            _import_request(
                record_id="run-3102-rabi",
                record_dir="records/run-3102-rabi",
                legacy_data_id=3102,
                target_label="Imported Rabi repeat",
            ),
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
        self.assertEqual(
            payload["export_review"],
            {
                "classification": "exported_selected_measurement_record",
                "package_written": True,
                "block_reason": None,
                "next_action": "transfer_package_for_receiving_review",
                "retry_requires": None,
            },
        )
        self.assertEqual(
            payload["read_model_freshness_review"],
            {
                "classification": "fresh_read_model_evidence",
                "read_model_refresh": "not_performed",
                "block_reason": None,
                "next_action": "continue_selected_record_export",
                "retry_requires": None,
                "does_not_claim": [
                    "read_model_refresh",
                    "automatic_projection",
                    "storage_mutation",
                    "record_repair",
                ],
            },
        )

    def test_selected_record_export_leaves_source_record_artifacts_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            record_dir = storage_root / "records" / "run-3101-rabi"
            before = {
                path.relative_to(record_dir).as_posix(): _digest(path)
                for path in record_dir.rglob("*")
                if path.is_file()
            }

            run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

            after = {
                path.relative_to(record_dir).as_posix(): _digest(path)
                for path in record_dir.rglob("*")
                if path.is_file()
            }

        self.assertTrue(run.exported)
        self.assertEqual(after, before)
        self.assertEqual(
            run.to_dict()["selected_record_export_policy"]["record_storage_mutation"],
            "not_performed",
        )
        self.assertIn("existing_record_update", run.to_dict()["workflow"]["does_not_claim"])

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

    def test_preflight_export_uses_existing_fresh_read_model_without_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))

            run = export_selected_measurement_record_with_preflight_refresh(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

        payload = run.to_dict()
        self.assertTrue(run.exported)
        self.assertIsNone(run.refresh_run)
        self.assertEqual(
            payload["workflow"]["steps"],
            ["run_initial_selected_record_export_preflight"],
        )
        self.assertEqual(payload["preflight_review"]["refresh_performed"], False)
        self.assertEqual(payload["preflight_review"]["block_reason"], None)

    def test_preflight_export_refreshes_missing_read_model_then_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model_path.unlink()

            run = export_selected_measurement_record_with_preflight_refresh(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )
            package = open_package(package_root / "handoff-package-run-3101-rabi")

        payload = run.to_dict()
        self.assertTrue(run.exported)
        self.assertEqual(package.measurement_ids, ("run-3101-rabi",))
        self.assertEqual(
            payload["initial_export"]["read_model_freshness_review"]["classification"],
            "missing_read_model_requires_projection",
        )
        self.assertEqual(payload["refresh"]["workflow"]["classification"], "refreshed_read_model")
        self.assertEqual(payload["refresh"]["request"]["expected_target_condition"], "missing")
        self.assertEqual(payload["final_export"]["export"]["performed"], True)
        self.assertEqual(payload["preflight_review"]["refresh_performed"], True)
        self.assertEqual(payload["preflight_review"]["block_reason"], None)

    def test_preflight_export_refreshes_stale_read_model_then_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            previous_digest = _digest(read_model_path)
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            read_model["primary_data"]["digest"] = (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
            read_model_path.write_text(json.dumps(read_model, indent=2), encoding="utf-8")
            stale_digest = _digest(read_model_path)

            run = export_selected_measurement_record_with_preflight_refresh(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

        payload = run.to_dict()
        self.assertTrue(run.exported)
        self.assertNotEqual(stale_digest, previous_digest)
        self.assertEqual(
            payload["initial_export"]["read_model_freshness_review"]["classification"],
            "stale_read_model_requires_refresh",
        )
        self.assertEqual(
            payload["refresh"]["request"]["expected_current_read_model_digest"],
            stale_digest,
        )
        self.assertEqual(
            payload["refresh"]["request"]["expected_target_condition"], "replace_existing"
        )
        self.assertEqual(payload["final_export"]["export"]["performed"], True)

    def test_preflight_export_blocks_when_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            (storage_root / "records" / "run-3101-rabi" / "record-read-model.json").unlink()
            (storage_root / "records" / "run-3101-rabi" / "finalization-receipt.json").unlink()

            run = export_selected_measurement_record_with_preflight_refresh(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

            self.assertFalse((package_root / "handoff-package-run-3101-rabi").exists())

        payload = run.to_dict()
        self.assertFalse(run.exported)
        self.assertEqual(run.classification, "blocked_before_export_refresh_failed")
        self.assertEqual(payload["refresh"], None)
        self.assertEqual(payload["final_export"], None)
        self.assertEqual(payload["preflight_review"]["block_reason"], "read_model_refresh_failed")
        self.assertIn(
            "finalization receipt is required",
            payload["preflight_review"]["preflight_error"],
        )
        self.assertEqual(
            payload["preflight_review"]["retry_requires"],
            "successful_read_model_refresh_then_export_retry",
        )

    def test_exports_selected_stored_record_batch_to_one_openable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_two_imported_records(Path(temp_dir))
            request = SelectedMeasurementRecordBatchExportRequest(
                request_id="export-rabi-batch-3101-3102",
                approval_state="approved",
                package_id="handoff-package-rabi-batch-3101-3102",
                display_name="Rabi batch selected measurement handoff",
                source_export_summary_id="export-summary-rabi-batch-3101-3102",
                display_path="HANDOFF_PACKAGE:/redacted/rabi-batch-3101-3102",
                records=(
                    _export_request().to_batch_record(),
                    SelectedMeasurementRecordBatchExportRecord(
                        record_id="run-3102-rabi",
                        record_dir="records/run-3102-rabi",
                        read_model_path="records/run-3102-rabi/record-read-model.json",
                        legacy_data_id=3102,
                        target="qA",
                        declared_preview_metadata=_preview_metadata(record_id="run-3102-rabi"),
                    ),
                ),
            )

            run = export_selected_measurement_record_batch_from_request(
                request,
                storage_root=storage_root,
                package_root=package_root,
            )
            package = open_package(package_root / "handoff-package-rabi-batch-3101-3102")

        summary = run.to_dict()

        self.assertTrue(run.exported)
        self.assertEqual(run.classification, "exported_selected_measurement_record_batch")
        self.assertEqual(package.measurement_ids, ("run-3101-rabi", "run-3102-rabi"))
        self.assertEqual(package.measurement("run-3102-rabi").label, "Imported Rabi repeat")
        self.assertEqual(package.measurement("run-3102-rabi").primary_table.row_count, 3)
        self.assertIn("batch_durable_import", summary["workflow"]["does_not_claim"])
        self.assertEqual(len(summary["records"]), 2)
        self.assertEqual(
            [
                item["measurement_record_id"]
                for item in summary["package_write"]["selected_measurements"]
            ],
            ["run-3101-rabi", "run-3102-rabi"],
        )

    def test_raw_batch_source_entrypoint_uses_explicit_export_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_two_imported_records(Path(temp_dir))
            request = SelectedMeasurementRecordBatchExportRequest(
                request_id="export-rabi-batch-raw-3101-3102",
                approval_state="approved",
                package_id="handoff-package-rabi-batch-raw-3101-3102",
                display_name="Raw Rabi batch selected measurement handoff",
                source_export_summary_id="export-summary-rabi-batch-raw-3101-3102",
                display_path="HANDOFF_PACKAGE:/redacted/rabi-batch-raw-3101-3102",
                records=(
                    _export_request().to_batch_record(),
                    SelectedMeasurementRecordBatchExportRecord(
                        record_id="run-3102-rabi",
                        record_dir="records/run-3102-rabi",
                        read_model_path="records/run-3102-rabi/record-read-model.json",
                        legacy_data_id=3102,
                        target="qA",
                        declared_preview_metadata=_preview_metadata(record_id="run-3102-rabi"),
                    ),
                ),
            )
            source = {
                "selected_record_export_policy": SELECTED_RECORD_EXPORT_POLICY,
                "selected_record_batch_export_request": request.to_dict(),
            }

            run = export_selected_measurement_record_batch(
                source,
                storage_root=storage_root,
                package_root=package_root,
            )

        self.assertTrue(run.exported)

    def test_batch_export_rejects_duplicate_selected_record_ids(self) -> None:
        duplicate_record = _export_request().to_batch_record()
        with self.assertRaisesRegex(ValueError, "duplicate selected record batch export record_id"):
            SelectedMeasurementRecordBatchExportRequest(
                request_id="export-rabi-batch-duplicate",
                approval_state="approved",
                package_id="handoff-package-rabi-batch-duplicate",
                display_name="Duplicate Rabi batch handoff",
                source_export_summary_id="export-summary-rabi-batch-duplicate",
                display_path="HANDOFF_PACKAGE:/redacted/rabi-batch-duplicate",
                records=(duplicate_record, duplicate_record),
            )

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
        self.assertEqual(
            run.to_dict()["export_review"],
            {
                "classification": "blocked_before_export",
                "package_written": False,
                "block_reason": "request_not_approved",
                "next_action": "approve_selected_record_export_request",
                "retry_requires": "approved_selected_record_export_request",
            },
        )
        self.assertEqual(
            run.to_dict()["read_model_freshness_review"]["classification"],
            "not_checked_before_approval",
        )

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
        self.assertEqual(run.to_dict()["export_review"]["block_reason"], "record_not_complete")
        self.assertEqual(
            run.to_dict()["export_review"]["next_action"],
            "review_record_evidence_before_export_retry",
        )
        self.assertEqual(
            run.to_dict()["read_model_freshness_review"]["classification"],
            "read_model_not_complete_for_export",
        )

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
        self.assertEqual(
            run.to_dict()["export_review"]["block_reason"],
            "record_path_scope_violation",
        )

    def test_export_blocks_stale_read_model_before_package_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            read_model["primary_data"]["digest"] = (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
            read_model_path.write_text(json.dumps(read_model, indent=2), encoding="utf-8")

            run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

            self.assertFalse((package_root / "handoff-package-run-3101-rabi").exists())

        review = run.to_dict()["read_model_freshness_review"]
        self.assertFalse(run.exported)
        self.assertIn("must match writer receipt", run.export_error or "")
        self.assertEqual(review["classification"], "stale_read_model_requires_refresh")
        self.assertEqual(review["read_model_refresh"], "not_performed")
        self.assertEqual(review["block_reason"], "stale_read_model")
        self.assertEqual(
            review["next_action"],
            "project_or_refresh_read_model_before_selected_record_export",
        )
        self.assertEqual(review["retry_requires"], "fresh_projected_record_read_model")
        self.assertIn("storage_mutation", review["does_not_claim"])

    def test_export_blocks_missing_read_model_before_package_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            (storage_root / "records" / "run-3101-rabi" / "record-read-model.json").unlink()

            run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

            self.assertFalse((package_root / "handoff-package-run-3101-rabi").exists())

        review = run.to_dict()["read_model_freshness_review"]
        self.assertFalse(run.exported)
        self.assertEqual(review["classification"], "missing_read_model_requires_projection")
        self.assertEqual(review["read_model_refresh"], "not_performed")
        self.assertEqual(review["block_reason"], "missing_read_model")
        self.assertEqual(review["retry_requires"], "fresh_projected_record_read_model")

    def test_export_review_summarizes_missing_evidence_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            (storage_root / "records" / "run-3101-rabi" / "writer-receipt.json").unlink()

            run = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

        review = run.to_dict()["export_review"]
        self.assertEqual(run.classification, "blocked_before_export")
        self.assertEqual(review["block_reason"], "missing_record_evidence")
        self.assertEqual(
            review["retry_requires"],
            "fresh_matching_record_read_model_manifest_and_writer_receipt",
        )

    def test_export_review_summarizes_package_collision_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root, package_root = self._create_imported_record(Path(temp_dir))
            first = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )
            second = export_selected_measurement_record_from_request(
                _export_request(),
                storage_root=storage_root,
                package_root=package_root,
            )

        self.assertTrue(first.exported)
        self.assertEqual(
            second.to_dict()["export_review"],
            {
                "classification": "blocked_before_export",
                "package_written": False,
                "block_reason": "package_destination_collision",
                "next_action": "choose_new_package_destination_before_retry",
                "retry_requires": "fresh_package_destination_or_removed_collision",
            },
        )
        self.assertEqual(
            second.to_dict()["read_model_freshness_review"]["classification"],
            "fresh_read_model_evidence_not_exported",
        )


if __name__ == "__main__":
    unittest.main()

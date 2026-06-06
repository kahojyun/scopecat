from __future__ import annotations

import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordAdoptionLocator,
    MeasurementRecordAdoptionRequest,
    MeasurementRecordHandle,
    MeasurementRecordImportSource,
    MeasurementRecordReference,
    MeasurementRecordReferenceRequest,
    adopt_existing_run_from_request,
    open_measurement_record,
    record_measurement_record_references_from_request,
)

NORMALIZED_ROWS = (
    ("bias_v", "readout_i", "readout_q"),
    ("0.000", "0.11", "-0.02"),
    ("0.025", "0.17", "0.01"),
    ("0.050", "0.23", "0.04"),
)


def _write_normalized_source(content_root: Path) -> Path:
    path = content_root / "converted" / "run-00042-rabi-primary.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(NORMALIZED_ROWS)
    return path


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _source(path: Path, *, source_id: str) -> MeasurementRecordImportSource:
    return MeasurementRecordImportSource(
        source_kind="adapter_normalized_primary_data",
        source_id=source_id,
        source_item_id="run-00042-rabi-primary-csv",
        content_ref="converted/run-00042-rabi-primary.csv",
        declared_digest=_digest(path),
        size_bytes=path.stat().st_size,
        rows_recorded=3,
    )


def _locators() -> tuple[MeasurementRecordAdoptionLocator, ...]:
    return (
        MeasurementRecordAdoptionLocator(
            locator_id="legacy-primary",
            kind="opaque_reference",
            role="primary_data",
            value="Legacy data store run 00042",
        ),
        MeasurementRecordAdoptionLocator(
            locator_id="operator-notebook",
            kind="workspace_relative_path",
            role="notebook",
            value="legacy-workspace/notebooks/manual-run-review.ipynb",
        ),
    )


def _references() -> tuple[MeasurementRecordReference, ...]:
    return (
        MeasurementRecordReference(
            reference_id="active-parameters",
            family="parameter_state",
            role="parameter_file",
            reference_kind="workspace_relative_path",
            reference_value="legacy-workspace/config/active-parameters.json",
            label="Active parameters at review time",
        ),
        MeasurementRecordReference(
            reference_id="setup-registry",
            family="setup_binding",
            role="setup_binding_file",
            reference_kind="workspace_relative_path",
            reference_value="legacy-workspace/config/setup-registry.json",
            label="Setup registry at review time",
        ),
        MeasurementRecordReference(
            reference_id="experiment-code",
            family="experiment_code",
            role="code_directory",
            reference_kind="workspace_relative_path",
            reference_value="legacy-workspace/experiment-code",
            label="Editable experiment code directory",
        ),
        MeasurementRecordReference(
            reference_id="analysis-summary",
            family="derived_artifact",
            role="preliminary_analysis_result",
            reference_kind="workspace_relative_path",
            reference_value="legacy-workspace/analysis/run-00042-summary.csv",
            label="Preliminary analysis summary",
        ),
    )


class MeasurementRecordAdoptionReadApiTest(unittest.TestCase):
    def test_adopt_first_facade_returns_handle_and_record_opens_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            source_path = _write_normalized_source(content_root)

            run = adopt_existing_run_from_request(
                MeasurementRecordAdoptionRequest(
                    request_id="adopt-generic-rabi-run-00042",
                    approval_state="approved",
                    record_id="generic-rabi-run-00042",
                    route="adopt_first",
                    import_source=_source(source_path, source_id="generic-rabi-run-00042"),
                    legacy_system_id="legacy-workstation",
                    legacy_run_id="legacy-run-00042",
                    label="Generic Rabi Run 00042",
                    experiment_type="rabi_sweep",
                    locators=_locators(),
                    operator_notes="Fictional generic brownfield adoption.",
                    references=_references(),
                    reference_set_id="generic-context",
                    reference_operator_notes="Declared references only.",
                ),
                storage_root=storage_root,
                content_root=content_root,
            )
            opened = open_measurement_record(
                "generic-rabi-run-00042",
                storage_root=storage_root,
            )
            record_dir = storage_root / "records" / "generic-rabi-run-00042"
            primary_exists = (record_dir / "primary.csv").exists()
            writer_receipt_exists = (record_dir / "writer-receipt.json").exists()
            finalization_receipt_exists = (record_dir / "finalization-receipt.json").exists()
            primary_dir_exists = (record_dir / "primary").exists()
            receipts_dir_exists = (record_dir / "receipts").exists()

        self.assertEqual(run.classification, "adopted_measurement_record")
        self.assertIsInstance(run.handle, MeasurementRecordHandle)
        self.assertEqual(run.legacy_run.classification, "recorded_legacy_run")
        self.assertEqual(run.primary_data.classification, "attached_legacy_primary_data")
        self.assertEqual(
            run.recorded_references.classification,
            "recorded_measurement_record_references",
        )
        self.assertEqual(
            run.handle.to_dict(),
            {
                "record_id": "generic-rabi-run-00042",
                "primary_data_attached": True,
            },
        )
        self.assertTrue(primary_exists)
        self.assertTrue(writer_receipt_exists)
        self.assertTrue(finalization_receipt_exists)
        self.assertFalse(primary_dir_exists)
        self.assertFalse(receipts_dir_exists)
        self.assertEqual(opened.classification, "opened_measurement_record")
        self.assertEqual(opened.record.creation_source_kind, "legacy_system")
        self.assertEqual(opened.record.label, "Generic Rabi Run 00042")
        self.assertEqual(opened.source.legacy_system_id, "legacy-workstation")
        self.assertEqual(opened.source.legacy_run_id, "legacy-run-00042")
        self.assertEqual(len(opened.source.locators), 2)
        self.assertEqual(
            [locator.role for locator in opened.source.locators],
            ["primary_data", "notebook"],
        )
        self.assertEqual(
            opened.primary_data.openable_path, "records/generic-rabi-run-00042/primary.csv"
        )
        self.assertEqual(opened.primary_data.observed_row_count, 3)
        self.assertEqual(len(opened.reference_sets), 1)
        self.assertEqual(
            [reference.reference_value for reference in opened.reference_sets[0].references],
            [
                "legacy-workspace/config/active-parameters.json",
                "legacy-workspace/config/setup-registry.json",
                "legacy-workspace/experiment-code",
                "legacy-workspace/analysis/run-00042-summary.csv",
            ],
        )

    def test_import_ready_facade_returns_complete_record_openable_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            source_path = _write_normalized_source(content_root)

            run = adopt_existing_run_from_request(
                MeasurementRecordAdoptionRequest(
                    request_id="import-ready-generic-rabi-run-00043",
                    approval_state="approved",
                    record_id="generic-rabi-run-00043",
                    route="import_ready",
                    import_source=_source(source_path, source_id="generic-review-adapter"),
                    label="Generic Rabi Run 00043",
                    experiment_type="rabi_sweep",
                ),
                storage_root=storage_root,
                content_root=content_root,
            )
            opened = open_measurement_record(
                "generic-rabi-run-00043",
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "adopted_measurement_record")
        self.assertEqual(run.primary_data.classification, "imported_new_record")
        self.assertEqual(opened.classification, "opened_measurement_record")
        self.assertEqual(opened.record.creation_source_kind, "import")
        self.assertEqual(opened.primary_data.observed_row_count, 3)
        self.assertIsNone(opened.source)
        self.assertEqual(opened.reference_sets, ())

    def test_open_missing_record_returns_explicit_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            opened = open_measurement_record("missing-record-001", storage_root=storage_root)

        self.assertEqual(opened.classification, "missing_measurement_record")
        self.assertIn("missing", opened.read_error or "")

    def test_open_shell_only_legacy_record_allows_missing_optional_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = adopt_existing_run_from_request(
                MeasurementRecordAdoptionRequest(
                    request_id="adopt-shell-only-run",
                    approval_state="approved",
                    record_id="generic-shell-only-00044",
                    route="adopt_first",
                    legacy_system_id="legacy-workstation",
                    legacy_run_id="legacy-run-00044",
                    locators=_locators(),
                ),
                storage_root=storage_root,
            )
            opened = open_measurement_record(
                "generic-shell-only-00044",
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "adopted_measurement_record")
        self.assertEqual(opened.classification, "opened_measurement_record")
        self.assertIsNone(opened.primary_data)
        self.assertEqual(opened.reference_sets, ())
        self.assertEqual(len(opened.source.locators), 2)

    def test_open_record_lists_multiple_reference_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            adopt_existing_run_from_request(
                MeasurementRecordAdoptionRequest(
                    request_id="adopt-reference-run",
                    approval_state="approved",
                    record_id="generic-reference-run-00045",
                    route="adopt_first",
                    legacy_system_id="legacy-workstation",
                    legacy_run_id="legacy-run-00045",
                    references=_references(),
                    reference_set_id="generic-context-a",
                ),
                storage_root=storage_root,
            )
            second = record_measurement_record_references_from_request(
                MeasurementRecordReferenceRequest(
                    request_id="record-second-reference-set",
                    approval_state="approved",
                    record_id="generic-reference-run-00045",
                    record_dir="records/generic-reference-run-00045",
                    reference_set_id="generic-context-b",
                    references=_references(),
                    previous_reference_receipt_path=(
                        "records/generic-reference-run-00045/"
                        "recorded-references/generic-context-a.json"
                    ),
                ),
                storage_root=storage_root,
            )
            opened = open_measurement_record(
                "generic-reference-run-00045",
                storage_root=storage_root,
            )

        self.assertTrue(second.recorded)
        self.assertEqual(opened.classification, "opened_measurement_record")
        self.assertEqual(
            [reference_set.reference_set_id for reference_set in opened.reference_sets],
            ["generic-context-a", "generic-context-b"],
        )
        self.assertEqual(
            opened.reference_sets[1].previous_reference_set_id,
            "generic-context-a",
        )


if __name__ == "__main__":
    unittest.main()

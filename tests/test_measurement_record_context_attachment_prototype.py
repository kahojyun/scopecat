from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordContextAttachment,
    MeasurementRecordContextAttachmentRequest,
    MeasurementRecordCreationRequest,
    attach_measurement_record_context,
    attach_measurement_record_context_from_request,
    create_measurement_record_from_request,
    list_measurement_record_context_attachments,
)
from scopecat.measurement_records.context_attachment import (
    CONTEXT_ATTACHMENT_POLICY,
    CONTEXT_ATTACHMENT_SCHEMA,
)


def _create_record(storage_root: Path) -> None:
    run = create_measurement_record_from_request(
        MeasurementRecordCreationRequest(
            request_id="create-run-ctx",
            approval_state="approved",
            record_id="run-ctx-001",
            record_dir="records/run-ctx-001",
            initial_lifecycle_state="created",
            creation_source_kind="legacy_system",
        ),
        storage_root=storage_root,
    )
    if not run.created:
        raise AssertionError(run.to_dict())


def _attachments() -> tuple[MeasurementRecordContextAttachment, ...]:
    return (
        MeasurementRecordContextAttachment(
            attachment_id="param-file-001",
            family="parameter_state",
            role="parameter_file",
            reference_kind="workspace_relative_path",
            reference_value="legacy-system/params/run-ctx-001.json",
            label="Legacy parameter file",
        ),
        MeasurementRecordContextAttachment(
            attachment_id="setup-binding-001",
            family="setup_binding",
            role="setup_binding_file",
            reference_kind="workspace_relative_path",
            reference_value="legacy-system/setup/run-ctx-001.json",
            label="Setup binding file",
        ),
        MeasurementRecordContextAttachment(
            attachment_id="code-dir-001",
            family="experiment_code",
            role="code_directory",
            reference_kind="workspace_relative_path",
            reference_value="legacy-system/code/rabi",
            label="Legacy acquisition code",
        ),
        MeasurementRecordContextAttachment(
            attachment_id="analysis-summary-001",
            family="preliminary_analysis",
            role="analysis_result",
            reference_kind="workspace_relative_path",
            reference_value="analysis/run-ctx-001/summary.csv",
            label="Initial fit summary",
            preview="contrast=0.82",
        ),
    )


def _request(**overrides: object) -> MeasurementRecordContextAttachmentRequest:
    values = {
        "request_id": "attach-context-run-ctx",
        "approval_state": "approved",
        "record_id": "run-ctx-001",
        "record_dir": "records/run-ctx-001",
        "attachment_set_id": "context-set-001",
        "attachments": _attachments(),
        "operator_notes": "Recorded user-selected context references.",
    }
    values.update(overrides)
    return MeasurementRecordContextAttachmentRequest(**values)


def _source(**overrides: object) -> dict:
    return {
        "context_attachment_schema": CONTEXT_ATTACHMENT_SCHEMA,
        "context_attachment_policy": CONTEXT_ATTACHMENT_POLICY,
        "context_attachment_request": _request(**overrides).to_dict(),
    }


class MeasurementRecordContextAttachmentPrototypeTest(unittest.TestCase):
    def test_attaches_context_references_without_rewriting_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)
            manifest_path = storage_root / "records" / "run-ctx-001" / "record-manifest.json"
            before = manifest_path.read_text(encoding="utf-8")

            run = attach_measurement_record_context_from_request(
                _request(),
                storage_root=storage_root,
            )
            after = manifest_path.read_text(encoding="utf-8")
            receipt_path = (
                storage_root
                / "records"
                / "run-ctx-001"
                / "context-attachments"
                / "context-set-001.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            review = list_measurement_record_context_attachments(storage_root=storage_root)

        self.assertEqual(run.classification, "attached_measurement_record_context")
        self.assertEqual(before, after)
        self.assertEqual(receipt["record"]["record_id"], "run-ctx-001")
        self.assertEqual(receipt["attachment_set"]["attachment_set_id"], "context-set-001")
        self.assertEqual(
            [attachment["role"] for attachment in receipt["attachments"]],
            [
                "parameter_file",
                "setup_binding_file",
                "code_directory",
                "analysis_result",
            ],
        )
        self.assertEqual(
            review["workflow"]["classification"],
            "measurement_record_context_attachment_review_ready",
        )
        self.assertEqual(review["entries"][0]["attachment_count"], 4)

    def test_raw_source_uses_declared_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)

            run = attach_measurement_record_context(_source(), storage_root=storage_root)

        self.assertTrue(run.attached)

    def test_unapproved_request_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)

            run = attach_measurement_record_context_from_request(
                _request(approval_state="needs_review"),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "blocked_before_context_attachment")
        self.assertFalse(
            (
                storage_root
                / "records"
                / "run-ctx-001"
                / "context-attachments"
                / "context-set-001.json"
            ).exists()
        )

    def test_second_receipt_can_declare_previous_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)
            first = attach_measurement_record_context_from_request(
                _request(),
                storage_root=storage_root,
            )
            second = attach_measurement_record_context_from_request(
                _request(
                    request_id="attach-context-run-ctx-2",
                    attachment_set_id="context-set-002",
                    previous_attachment_receipt_path=(
                        "records/run-ctx-001/context-attachments/context-set-001.json"
                    ),
                ),
                storage_root=storage_root,
            )
            review = list_measurement_record_context_attachments(storage_root=storage_root)

        self.assertTrue(first.attached)
        self.assertTrue(second.attached)
        self.assertEqual(len(review["entries"]), 2)
        self.assertEqual(
            review["entries"][1]["attachment_set"]["previous_attachment_receipt"]["path"],
            "records/run-ctx-001/context-attachments/context-set-001.json",
        )

    def test_receipt_collision_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            _create_record(storage_root)
            first = attach_measurement_record_context_from_request(
                _request(),
                storage_root=storage_root,
            )
            second = attach_measurement_record_context_from_request(
                _request(request_id="attach-context-run-ctx-again"),
                storage_root=storage_root,
            )

        self.assertTrue(first.attached)
        self.assertEqual(second.classification, "blocked_before_context_attachment")
        self.assertIn("already exists", second.to_dict()["receipt"]["attachment_error"])


if __name__ == "__main__":
    unittest.main()

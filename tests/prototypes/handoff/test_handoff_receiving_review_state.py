from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scopecat.handoff import (
    HandoffContractError,
    HandoffDurableImportDestination,
    HandoffDurableImportRequest,
    HandoffImportPlanRequest,
    HandoffReceivingReviewRequest,
    HandoffReceivingReviewStateReceiptRequest,
    project_handoff_receiving_review_state,
    review_handoff_durable_import_retry,
    run_handoff_durable_import_from_plan,
    summarize_handoff_durable_import_receipt,
    write_handoff_receiving_review_state_receipt,
)
from scopecat.handoff.import_plan import build_import_plan
from scopecat.handoff.receiving import run_receiving_gate_from_request

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _receiving_request(
    *,
    integrity_classification: str = "declared_integrity_verified",
) -> HandoffReceivingReviewRequest:
    return HandoffReceivingReviewRequest(
        request_id="receive-handoff-package-legacy-rabi-001",
        reviewed_package_id="handoff-package-legacy-rabi-001",
        reviewed_preview_classification="needs_review_before_acceptance",
        reviewed_integrity_classification=integrity_classification,
    )


def _import_plan_request() -> HandoffImportPlanRequest:
    return HandoffImportPlanRequest(
        request_id="plan-import-handoff-package-legacy-rabi-001",
        requested_package_id="handoff-package-legacy-rabi-001",
        measurement_selection="all_measurements",
    )


def _destination() -> HandoffDurableImportDestination:
    return HandoffDurableImportDestination(
        record_id="imported-legacy-rabi-001",
        record_dir="records/imported-legacy-rabi-001",
        primary_data_path="records/imported-legacy-rabi-001/primary.csv",
        writer_receipt_path="records/imported-legacy-rabi-001/writer-receipt.json",
        finalization_receipt_path="records/imported-legacy-rabi-001/finalization-receipt.json",
        read_model_path="records/imported-legacy-rabi-001/record-read-model.json",
    )


def _durable_request(*, approval_state: str = "approved") -> HandoffDurableImportRequest:
    return HandoffDurableImportRequest(
        request_id="durably-import-handoff-package-legacy-rabi-001",
        approval_state=approval_state,
        requested_package_id="handoff-package-legacy-rabi-001",
        measurement_record_id="legacy-rabi-001",
        destination=_destination(),
    )


def _import_plan_run(package_dir: Path):
    receiving_gate = run_receiving_gate_from_request(
        _receiving_request(),
        package_dir=package_dir,
    )
    return build_import_plan(
        _import_plan_request(),
        receiving_gate=receiving_gate,
    )


class HandoffReceivingReviewStateProjectionTest(unittest.TestCase):
    def test_projects_ready_import_plan_without_persistence_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            import_plan = _import_plan_run(package_dir)

            projection = project_handoff_receiving_review_state(import_plan=import_plan)
            summary = projection.to_dict()

        self.assertEqual(summary["artifact_posture"], "local_receiving_review_state_projection")
        self.assertEqual(summary["classification"], "ready_for_import_acceptance_decision")
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            summary["receiving_gate"]["classification"], "ready_for_acceptance_mutation"
        )
        self.assertEqual(summary["import_plan"]["planned_measurement_ids"], ["legacy-rabi-001"])
        self.assertEqual(summary["linked_context"]["handling"], "keep_reference_only")
        self.assertEqual(
            summary["review_state"]["next_action"],
            "review_storage_acceptance_destination_before_durable_import",
        )
        self.assertIn("persisted_gui_state", summary["does_not_claim"])
        self.assertEqual(summary["review_state_policy"]["storage_mutation"], "not_performed")
        self.assertEqual(summary["review_state_policy"]["gui_state_persistence"], "not_performed")

    def test_writes_local_receiving_review_state_receipt_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_dir = _copy_package(temp_path)
            import_plan = _import_plan_run(package_dir)
            projection = project_handoff_receiving_review_state(import_plan=import_plan)
            state_root = temp_path / "receiving-state"
            state_root.mkdir()

            receipt = write_handoff_receiving_review_state_receipt(
                HandoffReceivingReviewStateReceiptRequest(
                    request_id="persist-receiving-review-state-001",
                    receipt_path="reviews/handoff-package-legacy-rabi-001/state-receipt.json",
                ),
                projection=projection,
                state_root=state_root,
            )
            written = json.loads(
                (
                    state_root / "reviews/handoff-package-legacy-rabi-001/state-receipt.json"
                ).read_text(encoding="utf-8")
            )

        self.assertTrue(receipt.written)
        self.assertEqual(written["artifact_posture"], "local_receiving_review_state_receipt")
        self.assertEqual(written["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            written["receipt_policy"]["authority"],
            "local_review_continuity_receipt",
        )
        self.assertEqual(
            written["projection"]["artifact_posture"],
            "local_receiving_review_state_projection",
        )
        self.assertIn("gui_state_store", written["does_not_claim"])
        self.assertIn("storage_mutation", written["does_not_claim"])

    def test_receiving_review_state_receipt_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_dir = _copy_package(temp_path)
            import_plan = _import_plan_run(package_dir)
            projection = project_handoff_receiving_review_state(import_plan=import_plan)
            state_root = temp_path / "receiving-state"
            state_root.mkdir()
            request = HandoffReceivingReviewStateReceiptRequest(
                request_id="persist-receiving-review-state-001",
                receipt_path="reviews/state-receipt.json",
            )
            write_handoff_receiving_review_state_receipt(
                request,
                projection=projection,
                state_root=state_root,
            )

            with self.assertRaises(HandoffContractError):
                write_handoff_receiving_review_state_receipt(
                    request,
                    projection=projection,
                    state_root=state_root,
                )

    def test_projects_blocked_receiving_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "corrupted\n",
                encoding="utf-8",
            )
            receiving_gate = run_receiving_gate_from_request(
                _receiving_request(integrity_classification="integrity_review_required"),
                package_dir=package_dir,
            )

            summary = project_handoff_receiving_review_state(
                receiving_gate=receiving_gate,
            ).to_dict()

        self.assertEqual(summary["classification"], "blocked_before_acceptance")
        self.assertFalse(summary["receiving_gate"]["acceptance_allowed"])
        self.assertEqual(
            summary["review_state"]["block_reason"],
            "package_integrity_review_required",
        )
        self.assertEqual(
            summary["review_state"]["retry_requires"],
            "fresh_matching_package_open_and_integrity_observation",
        )

    def test_projects_completed_durable_import_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_dir = _copy_package(temp_path)
            import_plan = _import_plan_run(package_dir)
            storage_root = temp_path / "storage"
            storage_root.mkdir()
            durable_run = run_handoff_durable_import_from_plan(
                _durable_request(),
                import_plan=import_plan,
                storage_root=storage_root,
            )
            durable_summary = summarize_handoff_durable_import_receipt(durable_run.to_dict())

            summary = project_handoff_receiving_review_state(
                import_plan=import_plan,
                durable_import_summary=durable_summary,
            ).to_dict()

        self.assertEqual(summary["classification"], "imported_handoff_measurement_record")
        self.assertEqual(
            summary["durable_import"]["destination_record_id"], "imported-legacy-rabi-001"
        )
        self.assertTrue(summary["durable_import"]["durable_import_performed"])
        self.assertIsNone(summary["review_state"]["block_reason"])
        self.assertEqual(summary["review_state"]["next_action"], "use_durable_measurement_record")

    def test_projects_retry_ready_prior_durable_import_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_dir = _copy_package(temp_path)
            import_plan = _import_plan_run(package_dir)
            durable_run = run_handoff_durable_import_from_plan(
                _durable_request(approval_state="needs_review"),
                import_plan=import_plan,
                storage_root=temp_path / "storage",
            )
            previous_summary = summarize_handoff_durable_import_receipt(durable_run.to_dict())
            retry_review = review_handoff_durable_import_retry(
                previous_summary,
                fresh_import_plan=import_plan,
            )

            summary = project_handoff_receiving_review_state(
                import_plan=import_plan,
                durable_import_summary=previous_summary,
                retry_review=retry_review,
            ).to_dict()

        self.assertEqual(summary["classification"], "fresh_import_plan_ready_for_retry")
        self.assertTrue(summary["retry_review"]["retry_allowed"])
        self.assertIsNone(summary["review_state"]["block_reason"])
        self.assertEqual(
            summary["review_state"]["next_action"],
            "prepare_fresh_handoff_durable_import_request",
        )
        self.assertEqual(
            summary["review_state"]["retry_requires"],
            "approved_handoff_durable_import_request",
        )

    def test_projects_error_diagnostic_as_blocked_local_review_state(self) -> None:
        diagnostic = HandoffContractError(
            "reviewed package id must match opened package",
            operation="run_receiving_gate",
        ).to_diagnostic()

        summary = project_handoff_receiving_review_state(
            error_diagnostic=diagnostic,
        ).to_dict()

        self.assertEqual(summary["classification"], "blocked_by_handoff_error_diagnostic")
        self.assertEqual(summary["error_diagnostic"]["code"], "handoff_contract_error")
        self.assertEqual(
            summary["review_state"]["retry_requires"],
            "fresh_valid_handoff_request_or_receipt",
        )
        self.assertIn("retry_authorization", summary["does_not_claim"])

    def test_rejects_inconsistent_receipt_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            import_plan = _import_plan_run(package_dir)
            durable_run = run_handoff_durable_import_from_plan(
                _durable_request(approval_state="needs_review"),
                import_plan=import_plan,
                storage_root=Path(temp_dir) / "storage",
            )
            durable_summary = summarize_handoff_durable_import_receipt(durable_run.to_dict())
            mismatched_summary = replace(durable_summary, package_id="different-package")

            with self.assertRaises(HandoffContractError):
                project_handoff_receiving_review_state(
                    import_plan=import_plan,
                    durable_import_summary=mismatched_summary,
                )

    def test_rejects_stale_same_package_receiving_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_dir = _copy_package(temp_path)
            import_plan = _import_plan_run(package_dir)
            stale_root = temp_path / "stale"
            stale_root.mkdir()
            stale_package_dir = _copy_package(stale_root)
            stale_receiving_gate = run_receiving_gate_from_request(
                _receiving_request(),
                package_dir=stale_package_dir,
            )

            with self.assertRaises(HandoffContractError):
                project_handoff_receiving_review_state(
                    receiving_gate=stale_receiving_gate,
                    import_plan=import_plan,
                )

    def test_rejects_retry_review_for_different_fresh_import_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_dir = _copy_package(temp_path)
            import_plan = _import_plan_run(package_dir)
            durable_run = run_handoff_durable_import_from_plan(
                _durable_request(approval_state="needs_review"),
                import_plan=import_plan,
                storage_root=temp_path / "storage",
            )
            previous_summary = summarize_handoff_durable_import_receipt(durable_run.to_dict())
            retry_review = review_handoff_durable_import_retry(
                previous_summary,
                fresh_import_plan=import_plan,
            )
            fresh_root = temp_path / "fresh"
            fresh_root.mkdir()
            second_package_dir = _copy_package(fresh_root)
            different_import_plan = _import_plan_run(second_package_dir)

            with self.assertRaises(HandoffContractError):
                project_handoff_receiving_review_state(
                    import_plan=different_import_plan,
                    retry_review=retry_review,
                )


if __name__ == "__main__":
    unittest.main()

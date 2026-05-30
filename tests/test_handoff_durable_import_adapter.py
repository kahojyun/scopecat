from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scopecat.handoff import (
    HandoffDurableImportDestination,
    HandoffDurableImportReceiptSummary,
    HandoffDurableImportRequest,
    HandoffImportPlanRequest,
    HandoffReceivingReviewRequest,
    build_durable_import_request_from_handoff_plan,
    review_handoff_durable_import_retry,
    run_handoff_durable_import,
    run_handoff_durable_import_from_plan,
    summarize_handoff_durable_import_receipt,
    write_package,
)
from scopecat.handoff.durable_import import (
    HANDOFF_DURABLE_IMPORT_POLICY,
    HANDOFF_DURABLE_IMPORT_SCHEMA,
)
from scopecat.handoff.import_plan import build_import_plan
from scopecat.handoff.receiving import run_receiving_gate_from_request

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)
WRITER_FIXTURE = (
    ROOT / "tests" / "fixtures" / "handoff_engineering_prototype_writer" / "basic_package"
)


def _receiving_gate_source() -> dict:
    return {
        "receiving_gate_schema": "scopecat.handoff_receiving_gate.v0",
        "receiving_gate_policy": {
            "workflow_authority": "approved_receiving_review_request",
            "package_open": "read_only_declared_preview",
            "integrity_observation": "read_only_package_local_member_observation",
            "acceptance_gate": "require_approved_review_and_declared_integrity_verified",
            "storage_mutation": "not_performed",
            "import_acceptance": "not_performed",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "package_root_concurrency": "not_supported",
            "schema_inference": "not_performed",
            "dataframe_adapter": "not_defined",
            "interactive_gui": "not_defined",
            "shared_measurement_schema": "not_defined",
        },
        "receiving_review_request": {
            "request_id": "receive-handoff-package-legacy-rabi-001",
            "review": {
                "approval_state": "approved",
                "reviewed_package_id": "handoff-package-legacy-rabi-001",
                "reviewed_preview_classification": "needs_review_before_acceptance",
                "reviewed_integrity_classification": "declared_integrity_verified",
            },
        },
    }


def _import_plan_source() -> dict:
    return {
        "import_plan_schema": "scopecat.handoff_import_plan.v0",
        "import_plan_policy": {
            "workflow_authority": "approved_import_planning_request",
            "package_open": "read_only_declared_preview",
            "inspection_artifact": "optional_local_static_review_artifact",
            "receiving_gate": "required_before_import_plan",
            "import_plan": "non_mutating_measurement_acceptance_plan",
            "storage_mutation": "not_performed",
            "import_acceptance": "not_performed",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "conflict_detection": "not_performed",
            "final_storage_schema": "not_defined",
            "rollback": "not_defined",
        },
        "receiving_gate_source": _receiving_gate_source(),
        "import_plan_request": {
            "request_id": "plan-import-handoff-package-legacy-rabi-001",
            "approval_state": "approved",
            "requested_package_id": "handoff-package-legacy-rabi-001",
            "measurement_scope": {
                "selection": "all_measurements",
            },
        },
    }


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _writer_source() -> dict:
    return json.loads((WRITER_FIXTURE / "package-writer-input.json").read_text(encoding="utf-8"))


def _receiving_request() -> HandoffReceivingReviewRequest:
    return HandoffReceivingReviewRequest(
        request_id="receive-handoff-package-legacy-rabi-001",
        reviewed_package_id="handoff-package-legacy-rabi-001",
        reviewed_preview_classification="needs_review_before_acceptance",
        reviewed_integrity_classification="declared_integrity_verified",
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


def _request(**overrides: object) -> HandoffDurableImportRequest:
    values = {
        "request_id": "durably-import-handoff-package-legacy-rabi-001",
        "approval_state": "approved",
        "requested_package_id": "handoff-package-legacy-rabi-001",
        "measurement_record_id": "legacy-rabi-001",
        "destination": _destination(),
    }
    values.update(overrides)
    return HandoffDurableImportRequest(**values)


def _raw_source(**request_overrides: object) -> dict:
    return {
        "handoff_durable_import_schema": HANDOFF_DURABLE_IMPORT_SCHEMA,
        "handoff_durable_import_policy": HANDOFF_DURABLE_IMPORT_POLICY,
        "import_plan_source": _import_plan_source(),
        "handoff_durable_import_request": _request(**request_overrides).to_dict(),
    }


def _import_plan_run(package_dir: Path):
    receiving_gate = run_receiving_gate_from_request(
        _receiving_request(),
        package_dir=package_dir,
    )
    return build_import_plan(
        _import_plan_request(),
        receiving_gate=receiving_gate,
    )


class HandoffDurableImportAdapterTest(unittest.TestCase):
    def test_writer_to_durable_import_carries_experiment_context_as_references(self) -> None:
        source = _writer_source()
        source["linked_context"].extend(
            [
                {
                    "link_id": "package-legacy-001-managed-code-version",
                    "kind": "managed_code_version",
                    "label": "Selected calibration code version",
                    "package_path": None,
                    "include_status": "visible_excluded",
                    "relation": "run_start_context",
                    "authority": "scopecat_export_manifest",
                    "package_state": "not_packaged_visible_reference",
                    "reason": (
                        "The package carries this code context as a reference-only "
                        "review fact; code payloads are not packaged."
                    ),
                    "linked_measurement_record_ids": ["legacy-rabi-001"],
                    "context_reference": {
                        "reference_id": "managed-code-version-rabi-001",
                        "reference_kind": "managed_code_version",
                        "reference_family": "experiment_code",
                        "materialization": "reference_only",
                        "payload_import": "not_performed",
                    },
                },
                {
                    "link_id": "package-legacy-001-environment-review",
                    "kind": "uv_sync_operation_review",
                    "label": "Selected environment operation review",
                    "package_path": None,
                    "include_status": "visible_excluded",
                    "relation": "run_start_context",
                    "authority": "scopecat_export_manifest",
                    "package_state": "not_packaged_visible_reference",
                    "reason": (
                        "The package carries this environment context as a "
                        "reference-only review fact; environment restoration is not "
                        "performed."
                    ),
                    "linked_measurement_record_ids": ["legacy-rabi-001"],
                    "context_reference": {
                        "reference_id": "uv-sync-operation-review-rabi-001",
                        "reference_kind": "uv_sync_operation_review",
                        "reference_family": "environment_operation",
                        "materialization": "reference_only",
                        "payload_import": "not_performed",
                    },
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            storage_root = temp_root / "storage"
            package_root.mkdir()
            storage_root.mkdir()
            write_package(
                source,
                source_root=WRITER_FIXTURE / "source",
                package_root=package_root,
            )
            package_dir = package_root / "handoff-package-legacy-rabi-001"

            import_plan = _import_plan_run(package_dir)
            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=import_plan,
                storage_root=storage_root,
            )
            summary = run.to_dict()

        self.assertEqual(run.classification, "imported_handoff_measurement_record")
        linked_context = summary["import_plan"]["linked_context"]
        context_by_id = {item["link_id"]: item for item in linked_context}
        self.assertEqual(
            context_by_id["package-legacy-001-managed-code-version"]["context_reference"],
            {
                "reference_id": "managed-code-version-rabi-001",
                "reference_kind": "managed_code_version",
                "reference_family": "experiment_code",
                "materialization": "reference_only",
                "payload_import": "not_performed",
            },
        )
        self.assertEqual(
            context_by_id["package-legacy-001-environment-review"]["context_reference"][
                "reference_family"
            ],
            "environment_operation",
        )
        self.assertNotIn(
            "context_reference",
            json.dumps(summary["durable_import_request"], sort_keys=True),
        )
        self.assertIn("linked_context_payload_import", summary["workflow"]["does_not_claim"])

    def test_imports_ready_single_measurement_plan_as_durable_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            record_dir = storage_root / "records" / "imported-legacy-rabi-001"
            manifest = json.loads((record_dir / "record-manifest.json").read_text())
            read_model = json.loads((record_dir / "record-read-model.json").read_text())
            summary = run.to_dict()

        self.assertEqual(run.classification, "imported_handoff_measurement_record")
        self.assertTrue(run.imported)
        self.assertEqual(manifest["creation"]["source_kind"], "handoff")
        self.assertEqual(manifest["record"]["label"], "Rabi calibration follow-up")
        self.assertEqual(read_model["primary_data"]["observed_row_count"], 5)
        self.assertEqual(
            summary["durable_import_request"]["import_source"],
            {
                "source_kind": "handoff_package",
                "source_id": "handoff-package-legacy-rabi-001",
                "source_item_id": "legacy-rabi-001",
                "content_ref": "measurements/legacy-rabi-001/primary.csv",
                "declared_digest": (
                    "sha256:e7407c74b4bb35e1cc350ae2cc4829981c5b48ac7db4364366f0b30802eab887"
                ),
                "size_bytes": 73,
                "rows_recorded": 5,
                "primary_data_format": "csv_table",
            },
        )
        self.assertIn("linked_context_payload_import", summary["workflow"]["does_not_claim"])

    def test_summarizes_successful_durable_import_receipt_for_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            summary = summarize_handoff_durable_import_receipt(run.to_dict()).to_dict()

        self.assertEqual(
            summary["artifact_posture"],
            "local_handoff_durable_import_receipt_summary",
        )
        self.assertEqual(summary["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["measurement_record_id"], "legacy-rabi-001")
        self.assertEqual(summary["destination_record_id"], "imported-legacy-rabi-001")
        self.assertEqual(summary["final_state"], "imported_handoff_measurement_record")
        self.assertEqual(summary["next_action"], "use_durable_measurement_record")
        self.assertTrue(summary["durable_import_performed"])
        self.assertEqual(summary["durable_import_classification"], "imported_new_record")
        self.assertIn("continuation_authorization", summary["does_not_claim"])

    def test_raw_source_runs_import_plan_then_durable_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import(
                _raw_source(),
                package_dir=package_dir,
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "imported_handoff_measurement_record")
        self.assertEqual(
            run.durable_import_run.classification if run.durable_import_run else None,
            "imported_new_record",
        )

    def test_blocked_import_plan_does_not_mutate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            source = _raw_source()
            source["import_plan_source"]["receiving_gate_source"]["receiving_review_request"][
                "review"
            ]["reviewed_integrity_classification"] = "integrity_review_required"

            run = run_handoff_durable_import(
                source,
                package_dir=package_dir,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_handoff_durable_import")
        self.assertIsNone(run.durable_import_request)

    def test_summarizes_blocked_plan_without_authorizing_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            source = _raw_source()
            source["import_plan_source"]["receiving_gate_source"]["receiving_review_request"][
                "review"
            ]["reviewed_integrity_classification"] = "integrity_review_required"

            run = run_handoff_durable_import(
                source,
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = summarize_handoff_durable_import_receipt(run.to_dict()).to_dict()

        self.assertEqual(summary["final_state"], "blocked_before_handoff_durable_import")
        self.assertEqual(summary["next_action"], "resolve_import_plan_before_durable_import")
        self.assertFalse(summary["durable_import_performed"])
        self.assertIsNone(summary["durable_import_classification"])

    def test_retry_review_allows_fresh_ready_plan_after_blocked_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            blocked_root = temp_root / "blocked"
            fresh_root = temp_root / "fresh"
            blocked_root.mkdir()
            fresh_root.mkdir()
            blocked_package_dir = _copy_package(blocked_root)
            fresh_package_dir = _copy_package(fresh_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            (blocked_package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            source = _raw_source()
            source["import_plan_source"]["receiving_gate_source"]["receiving_review_request"][
                "review"
            ]["reviewed_integrity_classification"] = "integrity_review_required"
            blocked_run = run_handoff_durable_import(
                source,
                package_dir=blocked_package_dir,
                storage_root=storage_root,
            )
            previous_summary = summarize_handoff_durable_import_receipt(blocked_run.to_dict())

            retry_review = review_handoff_durable_import_retry(
                previous_summary,
                fresh_import_plan=_import_plan_run(fresh_package_dir),
            )
            retry_summary = retry_review.to_dict()

        self.assertEqual(retry_review.classification, "fresh_import_plan_ready_for_retry")
        self.assertTrue(retry_review.retry_allowed)
        self.assertEqual(retry_summary["measurement_record_id"], "legacy-rabi-001")
        self.assertEqual(
            retry_summary["retry_review_policy"]["prior_receipt_reuse"],
            "not_allowed",
        )
        self.assertIn("durable_import_request_creation", retry_summary["does_not_claim"])

    def test_retry_review_is_not_applicable_after_successful_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            previous_summary = summarize_handoff_durable_import_receipt(run.to_dict())

            retry_review = review_handoff_durable_import_retry(
                previous_summary,
                fresh_import_plan=_import_plan_run(package_dir),
            )

        self.assertEqual(retry_review.classification, "retry_not_applicable_after_import")
        self.assertFalse(retry_review.retry_allowed)

    def test_retry_review_blocks_after_partial_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            previous_summary = HandoffDurableImportReceiptSummary(
                package_id="handoff-package-legacy-rabi-001",
                measurement_record_id="legacy-rabi-001",
                destination_record_id="imported-legacy-rabi-001",
                final_state="blocked_before_handoff_durable_import",
                next_action="inspect_partial_commit_before_retry",
                durable_import_performed=False,
                durable_import_classification="import_failed_after_partial_commit",
                rollback_performed=False,
                partial_commit=True,
                import_error="simulated partial commit",
            )

            retry_review = review_handoff_durable_import_retry(
                previous_summary,
                fresh_import_plan=_import_plan_run(package_dir),
            )

        self.assertEqual(
            retry_review.classification,
            "retry_blocked_until_partial_commit_reviewed",
        )
        self.assertFalse(retry_review.retry_allowed)

    def test_retry_review_reports_ready_multi_measurement_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            previous_summary = HandoffDurableImportReceiptSummary(
                package_id="handoff-package-legacy-rabi-001",
                measurement_record_id="legacy-rabi-001",
                destination_record_id="imported-legacy-rabi-001",
                final_state="blocked_before_handoff_durable_import",
                next_action="review_durable_import_block_before_retry",
                durable_import_performed=False,
                durable_import_classification="blocked_before_import",
                rollback_performed=False,
                partial_commit=False,
                import_error="simulated block",
            )
            fresh_plan = _import_plan_run(package_dir)
            multi_measurement_plan = replace(
                fresh_plan,
                measurement_plans=(
                    fresh_plan.measurement_plans[0],
                    fresh_plan.measurement_plans[0],
                ),
            )

            retry_review = review_handoff_durable_import_retry(
                previous_summary,
                fresh_import_plan=multi_measurement_plan,
            )

        self.assertEqual(
            retry_review.classification,
            "retry_blocked_by_fresh_import_plan_measurement_scope",
        )
        self.assertFalse(retry_review.retry_allowed)

    def test_retry_review_rejects_measurement_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            previous_summary = HandoffDurableImportReceiptSummary(
                package_id="handoff-package-legacy-rabi-001",
                measurement_record_id="other-measurement",
                destination_record_id="imported-legacy-rabi-001",
                final_state="blocked_before_handoff_durable_import",
                next_action="review_durable_import_block_before_retry",
                durable_import_performed=False,
                durable_import_classification="blocked_before_import",
                rollback_performed=False,
                partial_commit=False,
                import_error="simulated block",
            )

            with self.assertRaisesRegex(ValueError, "measurement id"):
                review_handoff_durable_import_retry(
                    previous_summary,
                    fresh_import_plan=_import_plan_run(package_dir),
                )

    def test_module_cli_summarizes_local_handoff_durable_import_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            receipt_path = temp_root / "handoff-durable-import-receipt.json"
            receipt_path.write_text(json.dumps(run.to_dict()), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scopecat.handoff",
                    "--receipt-summary",
                    str(receipt_path),
                ],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

        summary = json.loads(result.stdout)

        self.assertEqual(
            summary["artifact_posture"],
            "local_handoff_durable_import_receipt_summary",
        )
        self.assertEqual(summary["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["measurement_record_id"], "legacy-rabi-001")
        self.assertEqual(summary["destination_record_id"], "imported-legacy-rabi-001")
        self.assertEqual(summary["final_state"], "imported_handoff_measurement_record")
        self.assertEqual(summary["next_action"], "use_durable_measurement_record")

    def test_receipt_summary_rejects_inconsistent_imported_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            receipt = run.to_dict()
            receipt["durable_import_result"]["import_result"]["performed"] = False

        with self.assertRaisesRegex(ValueError, "performed import"):
            summarize_handoff_durable_import_receipt(receipt)

    def test_receipt_summary_rejects_durable_request_source_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            receipt = run.to_dict()
            receipt["durable_import_request"]["import_source"]["source_id"] = "other-package"

        with self.assertRaisesRegex(ValueError, "source id"):
            summarize_handoff_durable_import_receipt(receipt)

    def test_receipt_summary_rejects_non_handoff_durable_request_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            receipt = run.to_dict()
            receipt["durable_import_request"]["creation_source_kind"] = "import"

        with self.assertRaisesRegex(ValueError, "source kind"):
            summarize_handoff_durable_import_receipt(receipt)

    def test_receipt_summary_rejects_non_handoff_durable_import_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            receipt = run.to_dict()
            receipt["durable_import_request"]["import_source"]["source_kind"] = (
                "adapter_normalized_primary_data"
            )
            receipt["durable_import_result"]["request"]["import_source"]["source_kind"] = (
                "adapter_normalized_primary_data"
            )

        with self.assertRaisesRegex(ValueError, "import source kind"):
            summarize_handoff_durable_import_receipt(receipt)

    def test_receipt_summary_rejects_non_handoff_durable_result_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            receipt = run.to_dict()
            receipt["durable_import_result"]["durable_import_policy"] = {
                **receipt["durable_import_result"]["durable_import_policy"],
                "source_authority": "other_source",
            }

        with self.assertRaisesRegex(ValueError, "policy"):
            summarize_handoff_durable_import_receipt(receipt)

    def test_receipt_summary_rejects_durable_result_request_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            receipt = run.to_dict()
            receipt["durable_import_result"]["request"]["record_id"] = "other-record"

        with self.assertRaisesRegex(ValueError, "request is inconsistent|record id"):
            summarize_handoff_durable_import_receipt(receipt)

    def test_rejects_package_id_mismatch_before_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "package id"):
                build_durable_import_request_from_handoff_plan(
                    _request(requested_package_id="different-package-id"),
                    import_plan=_import_plan_run(package_dir),
                )


if __name__ == "__main__":
    unittest.main()

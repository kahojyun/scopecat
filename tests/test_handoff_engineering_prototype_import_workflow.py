from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scopecat.handoff import run_import_workflow
from scopecat.handoff.import_workflow import HandoffImportWorkflowRequest

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


def _destination() -> dict:
    return {
        "measurement_record_id": "legacy-rabi-001",
        "destination_record_id": "imported-legacy-rabi-001",
        "record_dir": "records/imported-legacy-rabi-001",
        "primary_data_path": "records/imported-legacy-rabi-001/primary.csv",
        "manifest_path": "records/imported-legacy-rabi-001/record-manifest.json",
        "storage_schema": "measurement_record_directory_candidate_v0",
    }


def _acceptance_preflight_source() -> dict:
    return {
        "acceptance_preflight_schema": "scopecat.handoff_acceptance_preflight.v0",
        "acceptance_preflight_policy": {
            "workflow_authority": "approved_acceptance_preflight_request",
            "import_plan": "required_ready_non_mutating_import_plan",
            "destination_authority": "caller_provided_storage_root_plus_declared_relative_paths",
            "destination_observation": "exact_declared_paths_only",
            "collision_policy": "no_overwrite",
            "storage_mutation": "not_performed",
            "import_acceptance": "not_performed",
            "conflict_resolution": "not_performed",
            "rollback": "not_defined",
            "final_storage_schema": "not_defined",
        },
        "import_plan_source": _import_plan_source(),
        "acceptance_preflight_request": {
            "request_id": "preflight-handoff-package-legacy-rabi-001",
            "approval_state": "approved",
            "requested_package_id": "handoff-package-legacy-rabi-001",
            "destination_policy": {
                "path_kind": "relative_storage_path_under_caller_root",
                "collision_policy": "no_overwrite",
                "storage_schema": "declared_candidate_only",
            },
            "destinations": [_destination()],
        },
    }


def _storage_acceptance_request() -> dict:
    return {
        "request_id": "accept-handoff-package-legacy-rabi-001",
        "approval_state": "approved",
        "requested_package_id": "handoff-package-legacy-rabi-001",
        "approved_destinations": [_destination()],
    }


def _import_workflow_source(
    *,
    operator_decision: str = "approved_for_storage_acceptance",
    operator_reason: str | None = None,
    storage_acceptance_request: dict | None = None,
) -> dict:
    if (
        storage_acceptance_request is None
        and operator_decision == "approved_for_storage_acceptance"
    ):
        storage_acceptance_request = _storage_acceptance_request()
    return {
        "import_workflow_schema": "scopecat.handoff_import_workflow.v0",
        "import_workflow_policy": {
            "workflow_authority": "operator_import_workflow_review",
            "acceptance_preflight": "required_before_operator_decision_receipt",
            "operator_decision": "explicit_approve_reject_or_needs_review",
            "storage_acceptance": "only_after_approved_operator_decision",
            "review_state": "local_session_receipt",
            "storage_schema": "candidate_storage_acceptance_only",
            "conflict_resolution": "not_performed",
            "final_storage_schema": "not_defined",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "linked_context_payload_import": "not_performed",
        },
        "acceptance_preflight_source": _acceptance_preflight_source(),
        "import_workflow_request": {
            "request_id": "workflow-handoff-package-legacy-rabi-001",
            "requested_package_id": "handoff-package-legacy-rabi-001",
            "operator_decision": operator_decision,
            "operator_reason": operator_reason,
            "storage_acceptance_request": storage_acceptance_request,
        },
    }


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


class HandoffEngineeringPrototypeImportWorkflowTest(unittest.TestCase):
    def test_approved_workflow_accepts_candidate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_import_workflow(
                _import_workflow_source(),
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            primary_exists = (
                storage_root / "records" / "imported-legacy-rabi-001" / "primary.csv"
            ).is_file()

        self.assertEqual(run.classification, "accepted_into_storage")
        self.assertTrue(run.accepted)
        self.assertTrue(primary_exists)
        self.assertEqual(summary["artifact_posture"], "local_import_workflow_receipt")
        self.assertEqual(
            summary["workflow"]["steps"],
            [
                "run_acceptance_preflight",
                "record_operator_decision",
                "run_storage_acceptance",
            ],
        )
        self.assertEqual(
            summary["review_state"]["next_action"],
            "use_local_storage_acceptance_receipt",
        )
        self.assertTrue(summary["storage_acceptance"]["acceptance"]["performed"])

    def test_rejected_workflow_records_review_state_without_storage_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_import_workflow(
                _import_workflow_source(
                    operator_decision="rejected_after_review",
                    operator_reason="Package contents do not match the expected run.",
                    storage_acceptance_request=None,
                ),
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(run.classification, "rejected_after_review")
        self.assertFalse(run.accepted)
        self.assertFalse(records_exist)
        self.assertEqual(summary["storage_acceptance"], None)
        self.assertEqual(
            summary["review_state"]["next_action"],
            "record_rejection_without_storage_mutation",
        )
        self.assertEqual(
            summary["review_state"]["operator_reason"],
            "Package contents do not match the expected run.",
        )

    def test_needs_review_workflow_does_not_accept_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_import_workflow(
                _import_workflow_source(
                    operator_decision="needs_review",
                    operator_reason="Ask the sender to confirm the linked context.",
                    storage_acceptance_request=None,
                ),
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()

        self.assertEqual(run.classification, "needs_operator_review")
        self.assertFalse(summary["review_state"]["mutation_approved"])
        self.assertEqual(
            summary["review_state"]["next_action"],
            "complete_operator_review_before_storage_acceptance",
        )
        self.assertEqual(
            summary["request"]["operator_reason"],
            "Ask the sender to confirm the linked context.",
        )

    def test_approved_workflow_surfaces_destination_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            (storage_root / "records" / "imported-legacy-rabi-001").mkdir(parents=True)

            run = run_import_workflow(
                _import_workflow_source(),
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            primary_exists = (
                storage_root / "records" / "imported-legacy-rabi-001" / "primary.csv"
            ).exists()

        self.assertEqual(run.classification, "blocked_by_destination_collision")
        self.assertFalse(run.accepted)
        self.assertFalse(primary_exists)
        self.assertEqual(
            summary["review_state"]["next_action"],
            "choose_available_destinations_before_storage_acceptance",
        )
        self.assertEqual(
            summary["storage_acceptance"]["workflow"]["classification"],
            "blocked_before_acceptance",
        )

    def test_approved_workflow_surfaces_storage_rollback(self) -> None:
        import scopecat.handoff.storage_acceptance as storage_acceptance

        real_write_new_file = storage_acceptance._write_new_file

        def write_then_fail(root: Path, relative_path: str, content: bytes, *, label: str):
            if relative_path.endswith("record-manifest.json"):
                raise OSError("simulated manifest write failure")
            return real_write_new_file(root, relative_path, content, label=label)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            with mock.patch.object(
                storage_acceptance,
                "_write_new_file",
                side_effect=write_then_fail,
            ):
                run = run_import_workflow(
                    _import_workflow_source(),
                    package_dir=package_dir,
                    storage_root=storage_root,
                )
            summary = run.to_dict()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(run.classification, "rolled_back_after_write_failure")
        self.assertFalse(run.accepted)
        self.assertFalse(records_exist)
        self.assertEqual(
            summary["review_state"]["next_action"],
            "review_rollback_and_retry_with_fresh_preflight",
        )
        self.assertTrue(summary["storage_acceptance"]["acceptance"]["rollback_performed"])

    def test_approved_workflow_requires_storage_acceptance_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires storage_acceptance_request"):
            HandoffImportWorkflowRequest(
                request_id="workflow-handoff-package-legacy-rabi-001",
                requested_package_id="handoff-package-legacy-rabi-001",
                operator_decision="approved_for_storage_acceptance",
            )

    def test_rejects_storage_acceptance_request_without_approval_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowed only for approved"):
            run_import_workflow(
                _import_workflow_source(
                    operator_decision="needs_review",
                    operator_reason="Review is still pending.",
                    storage_acceptance_request=_storage_acceptance_request(),
                ),
                package_dir=PACKAGE,
                storage_root=PACKAGE.parent,
            )

    def test_rejected_workflow_requires_operator_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires operator_reason"):
            run_import_workflow(
                _import_workflow_source(
                    operator_decision="rejected_after_review",
                    storage_acceptance_request=None,
                ),
                package_dir=PACKAGE,
                storage_root=PACKAGE.parent,
            )

    def test_approved_workflow_rejects_operator_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not carry operator_reason"):
            run_import_workflow(
                _import_workflow_source(operator_reason="No review note needed for approval."),
                package_dir=PACKAGE,
                storage_root=PACKAGE.parent,
            )

    def test_operator_reason_is_local_single_line_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "single-line"):
            run_import_workflow(
                _import_workflow_source(
                    operator_decision="needs_review",
                    operator_reason="first line\nsecond line",
                    storage_acceptance_request=None,
                ),
                package_dir=PACKAGE,
                storage_root=PACKAGE.parent,
            )


if __name__ == "__main__":
    unittest.main()

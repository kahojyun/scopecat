from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff.acceptance_preflight import (
    HandoffAcceptanceDestination,
    HandoffAcceptancePreflightRequest,
    build_acceptance_preflight,
    run_acceptance_preflight,
)
from scopecat.handoff.import_plan import HandoffImportPlanRequest, build_import_plan
from scopecat.handoff.receiving import (
    HandoffReceivingReviewRequest,
    run_receiving_gate_from_request,
)

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
            "destinations": [
                {
                    "measurement_record_id": "legacy-rabi-001",
                    "destination_record_id": "imported-legacy-rabi-001",
                    "record_dir": "records/imported-legacy-rabi-001",
                    "primary_data_path": "records/imported-legacy-rabi-001/primary.csv",
                    "manifest_path": "records/imported-legacy-rabi-001/record-manifest.json",
                    "storage_schema": "measurement_record_directory_candidate_v0",
                }
            ],
        },
    }


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


def _acceptance_destination() -> HandoffAcceptanceDestination:
    return HandoffAcceptanceDestination(
        measurement_record_id="legacy-rabi-001",
        destination_record_id="imported-legacy-rabi-001",
        record_dir="records/imported-legacy-rabi-001",
        primary_data_path="records/imported-legacy-rabi-001/primary.csv",
        manifest_path="records/imported-legacy-rabi-001/record-manifest.json",
        storage_schema="measurement_record_directory_candidate_v0",
    )


def _acceptance_preflight_request() -> HandoffAcceptancePreflightRequest:
    return HandoffAcceptancePreflightRequest(
        request_id="preflight-handoff-package-legacy-rabi-001",
        requested_package_id="handoff-package-legacy-rabi-001",
        destinations=(_acceptance_destination(),),
    )


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _import_plan_run(package_dir: Path):
    receiving_gate = run_receiving_gate_from_request(
        _receiving_request(),
        package_dir=package_dir,
    )
    return build_import_plan(
        _import_plan_request(),
        receiving_gate=receiving_gate,
    )


class HandoffEngineeringPrototypeAcceptancePreflightTest(unittest.TestCase):
    def test_preflight_allows_available_destinations_without_storage_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = build_acceptance_preflight(
                _acceptance_preflight_request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            summary = run.to_dict()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(run.classification, "ready_for_acceptance_mutation_request")
        self.assertTrue(run.acceptance_preflight_allowed)
        self.assertEqual(summary["artifact_posture"], "local_acceptance_preflight_receipt")
        self.assertEqual(
            summary["destination_observation"]["classification"],
            "declared_destinations_available",
        )
        self.assertEqual(
            summary["destination_observation"]["observed_paths"][0]["target_states"],
            [
                {"path": "records/imported-legacy-rabi-001", "state": "available"},
                {"path": "records/imported-legacy-rabi-001/primary.csv", "state": "available"},
                {
                    "path": "records/imported-legacy-rabi-001/record-manifest.json",
                    "state": "available",
                },
            ],
        )
        self.assertIn("storage_mutation", summary["workflow"]["does_not_claim"])
        self.assertFalse(records_exist)

    def test_preflight_blocks_declared_destination_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            (storage_root / "records" / "imported-legacy-rabi-001").mkdir(parents=True)

            run = build_acceptance_preflight(
                _acceptance_preflight_request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            summary = run.to_dict()

        self.assertEqual(run.classification, "blocked_by_destination_collision")
        self.assertFalse(run.acceptance_preflight_allowed)
        self.assertEqual(
            summary["destination_observation"]["classification"],
            "destination_collision",
        )
        self.assertEqual(
            summary["destination_observation"]["observed_paths"][0]["classification"],
            "destination_collision",
        )

    def test_preflight_treats_broken_symlink_destination_as_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            (storage_root / "records").mkdir(parents=True)
            (storage_root / "records" / "imported-legacy-rabi-001").symlink_to("missing-record")

            run = build_acceptance_preflight(
                _acceptance_preflight_request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            target_states = run.destination_observations[0].target_states

        self.assertEqual(run.classification, "blocked_by_destination_collision")
        self.assertEqual(target_states[0]["state"], "exists")

    def test_preflight_blocks_symlink_destination_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            (temp_root / "external-records").mkdir()
            (storage_root / "records").symlink_to(temp_root / "external-records")

            run = build_acceptance_preflight(
                _acceptance_preflight_request(),
                import_plan=_import_plan_run(package_dir),
                storage_root=storage_root,
            )
            target_states = run.destination_observations[0].target_states

        self.assertEqual(run.classification, "blocked_by_destination_guardrail")
        self.assertEqual(target_states[0]["state"], "blocked_by_symlink_parent")

    def test_preflight_blocks_when_import_plan_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            blocked_receiving_request = HandoffReceivingReviewRequest(
                request_id="receive-handoff-package-legacy-rabi-001",
                reviewed_package_id="handoff-package-legacy-rabi-001",
                reviewed_preview_classification="needs_review_before_acceptance",
                reviewed_integrity_classification="integrity_review_required",
            )
            blocked_receiving_gate = run_receiving_gate_from_request(
                blocked_receiving_request,
                package_dir=package_dir,
            )
            blocked_import_plan = build_import_plan(
                _import_plan_request(),
                receiving_gate=blocked_receiving_gate,
            )

            run = build_acceptance_preflight(
                _acceptance_preflight_request(),
                import_plan=blocked_import_plan,
                storage_root=storage_root,
            )
            summary = run.to_dict()

        self.assertEqual(run.classification, "blocked_before_acceptance_preflight")
        self.assertFalse(run.acceptance_preflight_allowed)
        self.assertFalse(summary["destination_observation"]["performed"])
        self.assertEqual(summary["destination_observation"]["observed_paths"], [])

    def test_rejects_conflict_resolution_policy(self) -> None:
        source = _acceptance_preflight_source()
        source["acceptance_preflight_request"]["destination_policy"]["collision_policy"] = (
            "overwrite_existing"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            with self.assertRaisesRegex(ValueError, "collision_policy"):
                run_acceptance_preflight(source, package_dir=PACKAGE, storage_root=storage_root)

    def test_rejects_overlapping_destination_record_dirs(self) -> None:
        first_destination = HandoffAcceptanceDestination(
            measurement_record_id="legacy-rabi-001",
            destination_record_id="imported-legacy-rabi-001",
            record_dir="records/imported-legacy-rabi-001",
            primary_data_path="records/imported-legacy-rabi-001/primary.csv",
            manifest_path="records/imported-legacy-rabi-001/record-manifest.json",
            storage_schema="measurement_record_directory_candidate_v0",
        )
        nested_destination = HandoffAcceptanceDestination(
            measurement_record_id="legacy-rabi-002",
            destination_record_id="imported-legacy-rabi-002",
            record_dir="records/imported-legacy-rabi-001/nested",
            primary_data_path="records/imported-legacy-rabi-001/nested/primary.csv",
            manifest_path="records/imported-legacy-rabi-001/nested/record-manifest.json",
            storage_schema="measurement_record_directory_candidate_v0",
        )

        with self.assertRaisesRegex(ValueError, "record dirs must not overlap"):
            HandoffAcceptancePreflightRequest(
                request_id="preflight-handoff-package-legacy-rabi-001",
                requested_package_id="handoff-package-legacy-rabi-001",
                destinations=(first_destination, nested_destination),
            )

    def test_rejects_destination_paths_outside_record_dir(self) -> None:
        source = _acceptance_preflight_source()
        source["acceptance_preflight_request"]["destinations"][0]["manifest_path"] = (
            "records/other-record/record-manifest.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            with self.assertRaisesRegex(ValueError, "manifest_path must stay under"):
                run_acceptance_preflight(source, package_dir=PACKAGE, storage_root=storage_root)

    def test_rejects_destination_measurement_mismatch(self) -> None:
        source = _acceptance_preflight_source()
        source["acceptance_preflight_request"]["destinations"][0]["measurement_record_id"] = (
            "different-measurement"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            with self.assertRaisesRegex(ValueError, "must match import plan measurement ids"):
                run_acceptance_preflight(source, package_dir=PACKAGE, storage_root=storage_root)


if __name__ == "__main__":
    unittest.main()

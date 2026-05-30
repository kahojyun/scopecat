from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scopecat.handoff.acceptance_preflight import (
    HandoffAcceptanceDestination,
    HandoffAcceptancePreflightRequest,
    build_acceptance_preflight,
)
from scopecat.handoff.import_plan import HandoffImportPlanRequest, build_import_plan
from scopecat.handoff.receiving import (
    HandoffReceivingReviewRequest,
    run_receiving_gate_from_request,
)
from scopecat.handoff.storage_acceptance import (
    HandoffStorageAcceptanceRequest,
    run_storage_acceptance,
    run_storage_acceptance_from_preflight,
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


def _storage_acceptance_source() -> dict:
    return {
        "storage_acceptance_schema": "scopecat.handoff_storage_acceptance.v0",
        "storage_acceptance_policy": {
            "workflow_authority": "approved_storage_acceptance_request",
            "acceptance_preflight": "required_ready_acceptance_preflight",
            "destination_authority": "preflight_declared_relative_paths_only",
            "storage_schema": "measurement_record_directory_candidate_v0",
            "primary_data_materialization": "copy_package_primary_data",
            "record_manifest": "write_candidate_manifest",
            "collision_policy": "no_overwrite",
            "rollback": "best_effort_synchronous_cleanup",
            "storage_root_concurrency": "not_supported",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "linked_context_payload_import": "not_performed",
            "final_storage_schema": "not_defined",
        },
        "acceptance_preflight_source": _acceptance_preflight_source(),
        "storage_acceptance_request": {
            "request_id": "accept-handoff-package-legacy-rabi-001",
            "approval_state": "approved",
            "requested_package_id": "handoff-package-legacy-rabi-001",
            "approved_destinations": [_destination()],
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


def _storage_acceptance_request() -> HandoffStorageAcceptanceRequest:
    return HandoffStorageAcceptanceRequest(
        request_id="accept-handoff-package-legacy-rabi-001",
        requested_package_id="handoff-package-legacy-rabi-001",
        approved_destinations=(_acceptance_destination(),),
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


def _acceptance_preflight_run(package_dir: Path, storage_root: Path):
    return build_acceptance_preflight(
        _acceptance_preflight_request(),
        import_plan=_import_plan_run(package_dir),
        storage_root=storage_root,
    )


class HandoffEngineeringPrototypeStorageAcceptanceTest(unittest.TestCase):
    def test_accepts_ready_preflight_into_candidate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            run = run_storage_acceptance_from_preflight(
                _storage_acceptance_request(),
                preflight=_acceptance_preflight_run(package_dir, storage_root),
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            primary_path = storage_root / "records" / "imported-legacy-rabi-001" / "primary.csv"
            manifest_path = (
                storage_root / "records" / "imported-legacy-rabi-001" / "record-manifest.json"
            )
            primary_exists = primary_path.is_file()
            primary_bytes = primary_path.read_bytes()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(run.classification, "accepted_into_storage")
        self.assertTrue(run.accepted)
        self.assertTrue(primary_exists)
        self.assertEqual(
            primary_bytes,
            (PACKAGE / "measurements/legacy-rabi-001/primary.csv").read_bytes(),
        )
        self.assertEqual(summary["artifact_posture"], "local_storage_acceptance_receipt")
        self.assertTrue(summary["acceptance"]["performed"])
        self.assertEqual(
            summary["storage_acceptance_policy"]["storage_root_concurrency"],
            "not_supported",
        )
        self.assertIn(
            "concurrent_storage_root_mutation",
            summary["workflow"]["does_not_claim"],
        )
        self.assertEqual(manifest["schema"], "measurement_record_directory_candidate_v0")
        self.assertEqual(manifest["source"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            manifest["primary_data"]["path"],
            "records/imported-legacy-rabi-001/primary.csv",
        )
        self.assertIn("final_storage_schema", manifest["does_not_claim"])

    def test_blocks_when_acceptance_preflight_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            (storage_root / "records" / "imported-legacy-rabi-001").mkdir(parents=True)

            run = run_storage_acceptance_from_preflight(
                _storage_acceptance_request(),
                preflight=_acceptance_preflight_run(package_dir, storage_root),
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()

        self.assertEqual(run.classification, "blocked_before_acceptance")
        self.assertFalse(run.accepted)
        self.assertFalse(summary["acceptance"]["performed"])

    def test_rejects_destination_mismatch_even_when_preflight_is_blocked(self) -> None:
        mismatched_destination = HandoffAcceptanceDestination(
            measurement_record_id="legacy-rabi-001",
            destination_record_id="imported-legacy-rabi-001",
            record_dir="records/imported-legacy-rabi-001",
            primary_data_path="records/imported-legacy-rabi-001/different.csv",
            manifest_path="records/imported-legacy-rabi-001/record-manifest.json",
            storage_schema="measurement_record_directory_candidate_v0",
        )
        request = HandoffStorageAcceptanceRequest(
            request_id="accept-handoff-package-legacy-rabi-001",
            requested_package_id="handoff-package-legacy-rabi-001",
            approved_destinations=(mismatched_destination,),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            (storage_root / "records" / "imported-legacy-rabi-001").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "destinations must match"):
                run_storage_acceptance_from_preflight(
                    request,
                    preflight=_acceptance_preflight_run(package_dir, storage_root),
                    package_dir=package_dir,
                    storage_root=storage_root,
                )

    def test_rejects_package_dir_mismatch_from_typed_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            other_package_dir = temp_root / "other-package"
            shutil.copytree(package_dir, other_package_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            preflight = _acceptance_preflight_run(package_dir, storage_root)

            with self.assertRaisesRegex(ValueError, "package_dir must match"):
                run_storage_acceptance_from_preflight(
                    _storage_acceptance_request(),
                    preflight=preflight,
                    package_dir=other_package_dir,
                    storage_root=storage_root,
                )

    def test_rejects_storage_root_mismatch_from_typed_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            other_storage_root = temp_root / "other-storage"
            storage_root.mkdir()
            other_storage_root.mkdir()
            preflight = _acceptance_preflight_run(package_dir, storage_root)

            with self.assertRaisesRegex(ValueError, "storage_root must match"):
                run_storage_acceptance_from_preflight(
                    _storage_acceptance_request(),
                    preflight=preflight,
                    package_dir=package_dir,
                    storage_root=other_storage_root,
                )

    def test_rejects_invalid_typed_acceptance_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "storage_schema is unsupported"):
            HandoffAcceptanceDestination(
                measurement_record_id="legacy-rabi-001",
                destination_record_id="imported-legacy-rabi-001",
                record_dir="records/imported-legacy-rabi-001",
                primary_data_path="records/imported-legacy-rabi-001/primary.csv",
                manifest_path="records/imported-legacy-rabi-001/record-manifest.json",
                storage_schema="final_storage_schema_not_accepted",
            )

    def test_rejects_storage_acceptance_destination_mismatch(self) -> None:
        source = _storage_acceptance_source()
        source["storage_acceptance_request"]["approved_destinations"][0]["primary_data_path"] = (
            "records/imported-legacy-rabi-001/different.csv"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            with self.assertRaisesRegex(ValueError, "destinations must match"):
                run_storage_acceptance(source, package_dir=PACKAGE, storage_root=storage_root)

    def test_rejects_unapproved_storage_acceptance_request(self) -> None:
        source = _storage_acceptance_source()
        source["storage_acceptance_request"]["approval_state"] = "pending_review"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            with self.assertRaisesRegex(ValueError, "requires approved request"):
                run_storage_acceptance(source, package_dir=PACKAGE, storage_root=storage_root)

    def test_rejects_duplicate_storage_acceptance_destination_record_ids(self) -> None:
        source = _storage_acceptance_source()
        second_destination = {
            "measurement_record_id": "legacy-rabi-002",
            "destination_record_id": "imported-legacy-rabi-001",
            "record_dir": "records/imported-legacy-rabi-002",
            "primary_data_path": "records/imported-legacy-rabi-002/primary.csv",
            "manifest_path": "records/imported-legacy-rabi-002/record-manifest.json",
            "storage_schema": "measurement_record_directory_candidate_v0",
        }
        source["storage_acceptance_request"]["approved_destinations"].append(second_destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            with self.assertRaisesRegex(ValueError, "record ids must be unique"):
                run_storage_acceptance(source, package_dir=PACKAGE, storage_root=storage_root)

    def test_rejects_overlapping_storage_acceptance_record_dirs(self) -> None:
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
            HandoffStorageAcceptanceRequest(
                request_id="accept-handoff-package-legacy-rabi-001",
                requested_package_id="handoff-package-legacy-rabi-001",
                approved_destinations=(first_destination, nested_destination),
            )

    def test_rolls_back_primary_when_manifest_write_fails(self) -> None:
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
                run = run_storage_acceptance_from_preflight(
                    _storage_acceptance_request(),
                    preflight=_acceptance_preflight_run(package_dir, storage_root),
                    package_dir=package_dir,
                    storage_root=storage_root,
                )
            summary = run.to_dict()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(run.classification, "rolled_back_after_write_failure")
        self.assertTrue(run.rollback_performed)
        self.assertFalse(summary["acceptance"]["performed"])
        self.assertIn("simulated manifest write failure", summary["acceptance"]["write_error"])
        self.assertFalse(records_exist)

    def test_rejects_package_primary_data_changed_after_preflight(self) -> None:
        import scopecat.handoff.storage_acceptance as storage_acceptance

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            with mock.patch.object(
                storage_acceptance,
                "_read_package_member",
                return_value=b"changed after integrity observation\n",
            ):
                with self.assertRaisesRegex(ValueError, "digest must match preflight"):
                    run_storage_acceptance_from_preflight(
                        _storage_acceptance_request(),
                        preflight=_acceptance_preflight_run(package_dir, storage_root),
                        package_dir=package_dir,
                        storage_root=storage_root,
                    )
            records_exist = (storage_root / "records").exists()

        self.assertFalse(records_exist)

    def test_late_target_collision_blocks_without_rollback_claim(self) -> None:
        import scopecat.handoff.storage_acceptance as storage_acceptance

        def reject_after_preflight(root: Path, relative_paths: list[str], label: str) -> None:
            raise ValueError("handoff storage acceptance target already exists")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            with mock.patch.object(
                storage_acceptance,
                "_reject_existing_paths",
                side_effect=reject_after_preflight,
            ):
                run = run_storage_acceptance_from_preflight(
                    _storage_acceptance_request(),
                    preflight=_acceptance_preflight_run(package_dir, storage_root),
                    package_dir=package_dir,
                    storage_root=storage_root,
                )
            summary = run.to_dict()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(run.classification, "blocked_before_acceptance")
        self.assertFalse(run.rollback_performed)
        self.assertFalse(summary["acceptance"]["performed"])
        self.assertIn("target already exists", summary["acceptance"]["write_error"])
        self.assertFalse(records_exist)

    def test_late_record_dir_collision_blocks_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            preflight = _acceptance_preflight_run(package_dir, storage_root)
            (storage_root / "records" / "imported-legacy-rabi-001").mkdir(parents=True)

            run = run_storage_acceptance_from_preflight(
                _storage_acceptance_request(),
                preflight=preflight,
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            primary_exists = (
                storage_root / "records" / "imported-legacy-rabi-001" / "primary.csv"
            ).exists()

        self.assertEqual(run.classification, "blocked_before_acceptance")
        self.assertFalse(run.rollback_performed)
        self.assertFalse(summary["acceptance"]["performed"])
        self.assertIn("target already exists", summary["acceptance"]["write_error"])
        self.assertFalse(primary_exists)

    def test_late_symlink_parent_collision_blocks_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            preflight = _acceptance_preflight_run(package_dir, storage_root)
            (temp_root / "external-records").mkdir()
            (storage_root / "records").symlink_to(temp_root / "external-records")

            run = run_storage_acceptance_from_preflight(
                _storage_acceptance_request(),
                preflight=preflight,
                package_dir=package_dir,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            external_primary_exists = (
                temp_root / "external-records" / "imported-legacy-rabi-001" / "primary.csv"
            ).exists()

        self.assertEqual(run.classification, "blocked_before_acceptance")
        self.assertFalse(run.rollback_performed)
        self.assertFalse(summary["acceptance"]["performed"])
        self.assertIn("parent is a symlink", summary["acceptance"]["write_error"])
        self.assertFalse(external_primary_exists)

    def test_rolls_back_when_first_file_write_fails_after_create(self) -> None:
        import scopecat.handoff.storage_acceptance as storage_acceptance

        class FailingHandle:
            def __init__(self, file_fd: int) -> None:
                self.file_fd = file_fd

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                storage_acceptance.os.close(self.file_fd)

            def write(self, content: bytes) -> None:
                raise OSError("simulated first write failure")

        def failing_fdopen(file_fd: int, mode: str):
            return FailingHandle(file_fd)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            preflight = _acceptance_preflight_run(package_dir, storage_root)
            files = [("records/imported-legacy-rabi-001/primary.csv", b"partial")]
            write_results = [{"path": files[0][0], "kind": "primary_data", "state": "written"}]

            with (
                mock.patch.object(
                    storage_acceptance,
                    "_planned_files",
                    return_value=(files, write_results),
                ),
                mock.patch.object(storage_acceptance.os, "fdopen", side_effect=failing_fdopen),
            ):
                run = run_storage_acceptance_from_preflight(
                    _storage_acceptance_request(),
                    preflight=preflight,
                    package_dir=package_dir,
                    storage_root=storage_root,
                )
            summary = run.to_dict()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(run.classification, "rolled_back_after_write_failure")
        self.assertTrue(run.rollback_performed)
        self.assertFalse(summary["acceptance"]["performed"])
        self.assertIn("simulated first write failure", summary["acceptance"]["write_error"])
        self.assertFalse(records_exist)


if __name__ == "__main__":
    unittest.main()

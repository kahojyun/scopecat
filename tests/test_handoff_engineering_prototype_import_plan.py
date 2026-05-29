from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import HANDOFF_INSPECTION_ARTIFACT_NAME, run_import_plan
from scopecat.handoff.import_plan import HandoffImportPlanRequest

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


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


class HandoffEngineeringPrototypeImportPlanTest(unittest.TestCase):
    def test_import_plan_is_ready_after_reviewed_verified_receiving_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)

            run = run_import_plan(_import_plan_source(), package_dir=package_dir)
            summary = run.to_dict()
            records_exist = (temp_root / "records").exists()

        self.assertEqual(run.classification, "ready_for_import_acceptance_decision")
        self.assertTrue(run.import_plan_allowed)
        self.assertEqual(summary["artifact_posture"], "local_import_plan_receipt")
        self.assertEqual(
            summary["workflow"]["steps"],
            ["open_package", "run_receiving_gate", "build_import_plan"],
        )
        self.assertEqual(
            summary["receiving_gate"]["classification"],
            "ready_for_acceptance_mutation",
        )
        self.assertEqual(
            summary["import_plan"]["next_required_decision"],
            "choose_storage_acceptance_conflict_and_rollback_policy",
        )
        self.assertEqual(
            summary["import_plan"]["planned_measurement_imports"][0]["source"]["package_path"],
            "measurements/legacy-rabi-001/primary.csv",
        )
        self.assertEqual(
            summary["import_plan"]["planned_measurement_imports"][0]["destination"],
            {
                "storage_schema": "not_assigned",
                "storage_path": "not_assigned",
                "conflict_resolution": "not_decided",
            },
        )
        self.assertIn("storage_mutation", summary["workflow"]["does_not_claim"])
        self.assertFalse(records_exist)

    def test_import_plan_can_write_local_inspection_artifact_outside_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            inspection_root = temp_root / "inspection"

            run = run_import_plan(
                _import_plan_source(),
                package_dir=package_dir,
                inspection_output_dir=inspection_root,
            )
            summary = run.to_dict()
            html_path = inspection_root / HANDOFF_INSPECTION_ARTIFACT_NAME
            html_exists = html_path.is_file()

        self.assertTrue(html_exists)
        self.assertEqual(
            summary["workflow"]["steps"],
            [
                "open_package",
                "run_receiving_gate",
                "write_inspection_artifact",
                "build_import_plan",
            ],
        )
        self.assertEqual(
            summary["inspection_receipt"]["html_artifact"]["portable_package_member"],
            False,
        )

    def test_import_plan_blocks_when_receiving_gate_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            source = _import_plan_source()
            source["receiving_gate_source"]["receiving_review_request"]["review"][
                "reviewed_integrity_classification"
            ] = "integrity_review_required"

            run = run_import_plan(source, package_dir=package_dir)
            summary = run.to_dict()

        self.assertEqual(run.classification, "blocked_before_import_acceptance")
        self.assertFalse(run.import_plan_allowed)
        self.assertEqual(summary["import_plan"]["planned_measurement_imports"], [])
        self.assertEqual(
            summary["import_plan"]["next_required_decision"],
            "resolve_receiving_gate_before_import_acceptance",
        )

    def test_rejects_import_plan_destination_fields(self) -> None:
        source = _import_plan_source()
        source["import_plan_request"]["destination"] = {
            "storage_root": "must-not-be-accepted-by-import-planning"
        }

        with self.assertRaisesRegex(ValueError, "fields are unsupported"):
            run_import_plan(source, package_dir=PACKAGE)

    def test_rejects_unknown_selected_measurement(self) -> None:
        source = _import_plan_source()
        source["import_plan_request"]["measurement_scope"] = {
            "selection": "selected_measurements",
            "measurement_record_ids": ["missing-measurement"],
        }

        with self.assertRaisesRegex(ValueError, "requested measurement ids"):
            run_import_plan(source, package_dir=PACKAGE)

    def test_typed_import_plan_request_rejects_unsupported_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "selection is unsupported"):
            HandoffImportPlanRequest(
                request_id="plan-import-handoff-package-legacy-rabi-001",
                requested_package_id="handoff-package-legacy-rabi-001",
                measurement_selection="unsupported_selection",
            )

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            HandoffImportPlanRequest(
                request_id="plan-import-handoff-package-legacy-rabi-001",
                requested_package_id="handoff-package-legacy-rabi-001",
                measurement_selection="selected_measurements",
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff.import_plan import HandoffImportPlanRequest, build_import_plan
from scopecat.handoff.receiving import (
    HandoffReceivingReviewRequest,
    run_receiving_gate_from_request,
)
from tests.prototypes.handoff.package_writer_helpers import write_package_from_fixture_source

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "handoff"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)
WRITER_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "handoff"
    / "handoff_engineering_prototype_writer"
    / "basic_package"
)


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _receiving_request(**overrides: str) -> HandoffReceivingReviewRequest:
    values = {
        "request_id": "receive-handoff-package-legacy-rabi-001",
        "reviewed_package_id": "handoff-package-legacy-rabi-001",
        "reviewed_preview_classification": "needs_review_before_acceptance",
        "reviewed_integrity_classification": "declared_integrity_verified",
    }
    values.update(overrides)
    return HandoffReceivingReviewRequest(**values)


def _import_plan_request(**overrides: object) -> HandoffImportPlanRequest:
    values = {
        "request_id": "plan-import-handoff-package-legacy-rabi-001",
        "requested_package_id": "handoff-package-legacy-rabi-001",
        "measurement_selection": "all_measurements",
    }
    values.update(overrides)
    return HandoffImportPlanRequest(**values)


def _import_plan_run(
    package_dir: Path,
    *,
    receiving_request: HandoffReceivingReviewRequest | None = None,
    import_plan_request: HandoffImportPlanRequest | None = None,
):
    receiving_gate = run_receiving_gate_from_request(
        _receiving_request() if receiving_request is None else receiving_request,
        package_dir=package_dir,
    )
    return build_import_plan(
        _import_plan_request() if import_plan_request is None else import_plan_request,
        receiving_gate=receiving_gate,
    )


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _multi_measurement_package(temp_root: Path) -> Path:
    source = json.loads((WRITER_FIXTURE / "package-writer-input.json").read_text(encoding="utf-8"))
    first_record = source["selected_measurements"][0]
    second_record = copy.deepcopy(first_record)
    second_content = b"drive_frequency,signal\n4.90,0.12\n4.95,0.44\n"
    second_id = "legacy-rabi-002"
    second_record["measurement_record_id"] = second_id
    second_record["legacy_data_id"] = 1002
    second_record["label"] = "Second Rabi calibration follow-up"
    second_record["primary_data"]["source_path"] = f"records/{second_id}/primary.csv"
    second_record["primary_data"]["expected_digest"] = _sha256_digest(second_content)
    second_record["primary_data"]["expected_size_bytes"] = len(second_content)
    second_record["primary_data"]["package_path"] = f"measurements/{second_id}/primary.csv"
    second_record["default_bundle"][0]["item_id"] = f"{second_id}-primary"
    second_record["default_bundle"][0]["package_path"] = f"measurements/{second_id}/primary.csv"
    source["selected_measurements"].append(second_record)
    source["linked_context"][0]["linked_measurement_record_ids"].append(second_id)

    source_root = temp_root / "source"
    first_source = source_root / "records" / "legacy-rabi-001" / "primary.csv"
    first_source.parent.mkdir(parents=True)
    first_source.write_bytes(
        (WRITER_FIXTURE / "source" / "records" / "legacy-rabi-001" / "primary.csv").read_bytes()
    )
    second_source = source_root / "records" / second_id / "primary.csv"
    second_source.parent.mkdir(parents=True)
    second_source.write_bytes(second_content)
    package_root = temp_root / "packages"
    package_root.mkdir()
    write_package_from_fixture_source(source, source_root=source_root, package_root=package_root)
    return package_root / "handoff-package-legacy-rabi-001"


class HandoffEngineeringPrototypeImportPlanTest(unittest.TestCase):
    def test_import_plan_is_ready_after_reviewed_verified_receiving_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)

            run = _import_plan_run(package_dir)
            summary = run.to_dict()
            records_exist = (temp_root / "records").exists()

        self.assertEqual(run.classification, "ready_for_import_acceptance_decision")
        self.assertTrue(run.import_plan_allowed)
        self.assertEqual(summary["artifact_posture"], "local_import_plan_receipt")
        self.assertEqual(summary["classification"], "ready_for_import_acceptance_decision")
        self.assertEqual(
            summary["receiving_gate"]["classification"],
            "ready_for_acceptance_mutation",
        )
        self.assertIsNone(summary["block_reason"])
        self.assertEqual(
            summary["import_plan"]["planned_measurement_imports"][0]["source"]["package_path"],
            "measurements/legacy-rabi-001/primary.csv",
        )
        self.assertNotIn("destination", summary["import_plan"]["planned_measurement_imports"][0])
        self.assertFalse(records_exist)

    def test_import_plan_can_list_multiple_measurements_without_batch_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _multi_measurement_package(Path(temp_dir))

            run = _import_plan_run(package_dir)
            summary = run.to_dict()

        self.assertTrue(run.import_plan_allowed)
        self.assertEqual(
            [
                item["measurement_record_id"]
                for item in summary["import_plan"]["planned_measurement_imports"]
            ],
            ["legacy-rabi-001", "legacy-rabi-002"],
        )
        self.assertEqual(
            summary["package"]["measurement_ids"],
            ["legacy-rabi-001", "legacy-rabi-002"],
        )
        self.assertEqual(run.classification, "ready_for_import_acceptance_decision")

    def test_import_plan_blocks_when_receiving_gate_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            run = _import_plan_run(
                package_dir,
                receiving_request=_receiving_request(
                    reviewed_integrity_classification="integrity_review_required",
                ),
            )
            summary = run.to_dict()

        self.assertEqual(run.classification, "blocked_before_import_acceptance")
        self.assertFalse(run.import_plan_allowed)
        self.assertEqual(summary["import_plan"]["planned_measurement_imports"], [])
        self.assertEqual(summary["block_reason"], "package_integrity_review_required")

    def test_rejects_unknown_selected_measurement(self) -> None:
        with self.assertRaisesRegex(ValueError, "requested measurement ids"):
            _import_plan_run(
                PACKAGE,
                import_plan_request=_import_plan_request(
                    measurement_selection="selected_measurements",
                    requested_measurement_ids=("missing-measurement",),
                ),
            )

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

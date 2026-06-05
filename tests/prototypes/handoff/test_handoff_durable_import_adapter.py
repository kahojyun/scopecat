from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import (
    HandoffDurableImportDestination,
    HandoffDurableImportRequest,
    HandoffImportPlanRequest,
    HandoffReceivingReviewRequest,
    run_handoff_durable_import_from_plan,
)
from scopecat.handoff.durable_import import build_durable_import_request_from_handoff_plan
from scopecat.handoff.import_plan import build_import_plan
from scopecat.handoff.receiving import run_receiving_gate_from_request
from scopecat.handoff.writer import write_package

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


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _writer_source() -> dict:
    return json.loads((WRITER_FIXTURE / "package-writer-input.json").read_text(encoding="utf-8"))


def _multi_measurement_writer_source() -> tuple[dict, bytes]:
    source = _writer_source()
    first_record = source["selected_measurements"][0]
    second_record = json.loads(json.dumps(first_record))
    second_content = b"drive_frequency,signal\n4.90,0.12\n4.95,0.44\n"
    second_id = "legacy-rabi-002"
    second_record["measurement_record_id"] = second_id
    second_record["legacy_data_id"] = 1002
    second_record["label"] = "Second Rabi calibration follow-up"
    second_record["primary_data"]["source_path"] = f"records/{second_id}/primary.csv"
    second_record["primary_data"]["expected_digest"] = (
        f"sha256:{hashlib.sha256(second_content).hexdigest()}"
    )
    second_record["primary_data"]["expected_size_bytes"] = len(second_content)
    second_record["primary_data"]["package_path"] = f"measurements/{second_id}/primary.csv"
    second_record["declared_preview_metadata"]["plot_candidates"][0]["source"] = (
        f"measurements/{second_id}/primary.csv"
    )
    second_record["default_bundle"][0]["item_id"] = f"{second_id}-primary"
    second_record["default_bundle"][0]["package_path"] = f"measurements/{second_id}/primary.csv"
    source["selected_measurements"].append(second_record)
    source["linked_context"][0]["linked_measurement_record_ids"].append(second_id)
    return source, second_content


def _receiving_request(**overrides: str) -> HandoffReceivingReviewRequest:
    values = {
        "request_id": "receive-handoff-package-legacy-rabi-001",
        "reviewed_package_id": "handoff-package-legacy-rabi-001",
        "reviewed_preview_classification": "needs_review_before_acceptance",
        "reviewed_integrity_classification": "declared_integrity_verified",
    }
    values.update(overrides)
    return HandoffReceivingReviewRequest(**values)


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


def _import_plan_run(
    package_dir: Path,
    *,
    receiving_request: HandoffReceivingReviewRequest | None = None,
):
    receiving_gate = run_receiving_gate_from_request(
        _receiving_request() if receiving_request is None else receiving_request,
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
        self.assertEqual(summary["classification"], "imported_handoff_measurement_record")

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
        self.assertIsNone(summary["block_reason"])
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
        self.assertEqual(summary["classification"], "imported_handoff_measurement_record")

    def test_batch_import_plan_is_not_durable_batch_mutation_authority(self) -> None:
        source, second_content = _multi_measurement_writer_source()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "source"
            first_source = source_root / "records" / "legacy-rabi-001" / "primary.csv"
            first_source.parent.mkdir(parents=True)
            first_source.write_bytes(
                (
                    WRITER_FIXTURE / "source" / "records" / "legacy-rabi-001" / "primary.csv"
                ).read_bytes()
            )
            second_source = source_root / "records" / "legacy-rabi-002" / "primary.csv"
            second_source.parent.mkdir(parents=True)
            second_source.write_bytes(second_content)
            package_root = temp_root / "packages"
            package_root.mkdir()
            write_package(source, source_root=source_root, package_root=package_root)
            package_dir = package_root / "handoff-package-legacy-rabi-001"
            import_plan = _import_plan_run(package_dir)

            with self.assertRaisesRegex(ValueError, "requires exactly one planned measurement"):
                run_handoff_durable_import_from_plan(
                    _request(),
                    import_plan=import_plan,
                    storage_root=temp_root / "storage",
                )

        self.assertEqual(
            import_plan.to_dict()["classification"],
            "ready_for_import_acceptance_decision",
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

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=_import_plan_run(
                    package_dir,
                    receiving_request=_receiving_request(
                        reviewed_integrity_classification="integrity_review_required",
                    ),
                ),
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_handoff_durable_import")
        self.assertIsNone(run.durable_import_request)

    def test_stale_ready_plan_revalidates_source_before_durable_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            import_plan = _import_plan_run(package_dir)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=import_plan,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(run.classification, "blocked_before_handoff_durable_import")
        self.assertIsNotNone(run.durable_import_request)
        self.assertFalse(run.imported)
        self.assertEqual(
            run.durable_import_run.classification if run.durable_import_run else None,
            "blocked_before_import",
        )
        self.assertIn(
            "digest does not match",
            run.durable_import_run.import_error if run.durable_import_run else "",
        )
        self.assertFalse(records_exist)
        self.assertEqual(summary["classification"], "blocked_before_handoff_durable_import")
        self.assertEqual(
            summary["block_reason"],
            "durable_import_blocked_before_import",
        )
        self.assertEqual(
            summary["durable_import_result"]["classification"], "blocked_before_import"
        )
        self.assertFalse(summary["durable_import_result"]["import_result"]["performed"])

    def test_existing_destination_record_blocks_handoff_durable_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            existing_record_dir = storage_root / "records" / "imported-legacy-rabi-001"
            existing_record_dir.mkdir(parents=True)
            sentinel = existing_record_dir / "existing-note.txt"
            sentinel.write_text("existing record must not be touched\n", encoding="utf-8")
            import_plan = _import_plan_run(package_dir)

            run = run_handoff_durable_import_from_plan(
                _request(),
                import_plan=import_plan,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            sentinel_content = sentinel.read_text(encoding="utf-8")
            manifest_exists = (existing_record_dir / "record-manifest.json").exists()

        self.assertEqual(run.classification, "blocked_before_handoff_durable_import")
        self.assertFalse(run.imported)
        self.assertEqual(sentinel_content, "existing record must not be touched\n")
        self.assertFalse(manifest_exists)
        self.assertEqual(
            run.durable_import_run.classification if run.durable_import_run else None,
            "blocked_before_import",
        )
        self.assertIn(
            "already exists",
            run.durable_import_run.import_error if run.durable_import_run else "",
        )
        self.assertEqual(summary["classification"], "blocked_before_handoff_durable_import")
        self.assertEqual(
            summary["durable_import_result"]["classification"], "blocked_before_import"
        )
        self.assertIn(
            "already exists",
            run.durable_import_run.import_error if run.durable_import_run else "",
        )

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

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from implementation_candidates.filesystem_mutation import filesystem as filesystem_mutation
from implementation_candidates.handoff_package_acceptance import accept_handoff_package

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


def _acceptance_source() -> dict:
    return {
        "acceptance_schema": "scopecat.handoff_package_acceptance.v0",
        "acceptance_policy": {
            "acceptance_authority": "approved_handoff_package_acceptance_request",
            "package_authority": "directory_shaped_handoff_package",
            "package_open": "read_only_declared_preview",
            "storage_mutation": "copy_package_primary_data_and_write_record_manifests",
            "copy_behavior": "copy_into_new_records",
            "linked_context_materialization": "reference_only",
            "overwrite_behavior": "no_overwrite",
            "archive_handling": "not_performed",
            "package_integrity": "not_claimed",
            "checksum_validation": "not_performed",
            "package_root_concurrency": "not_supported",
            "schema_inference": "not_performed",
            "dataframe_adapter": "not_defined",
            "gui_workflow": "not_defined",
            "stable_public_api": "not_defined",
        },
        "acceptance_request": {
            "request_id": "accept-handoff-package-legacy-rabi-001",
            "review": {
                "approval_state": "approved",
                "reviewed_package_id": "handoff-package-legacy-rabi-001",
                "reviewed_preview_classification": "needs_review_before_acceptance",
            },
            "destination": {
                "path_kind": "relative_storage_path_under_caller_root",
                "collision_policy": "no_overwrite",
            },
            "materialization": {
                "selected_measurements": "copy_primary_data_into_storage",
                "linked_context": "reference_only",
                "source_package_identity": "preserve_package_reference",
            },
            "selected_measurements": [
                {
                    "measurement_record_id": "legacy-rabi-001",
                    "record_dir": "records/legacy-rabi-001",
                    "primary_data_path": "records/legacy-rabi-001/primary.csv",
                    "manifest_path": "records/legacy-rabi-001/record-manifest.json",
                }
            ],
        },
    }


class HandoffPackageAcceptanceCandidateTest(unittest.TestCase):
    def test_accepts_reviewed_package_into_new_local_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            receipt = accept_handoff_package(
                _acceptance_source(),
                package_dir=PACKAGE,
                storage_root=storage_root,
            )

            primary_path = storage_root / "records" / "legacy-rabi-001" / "primary.csv"
            manifest_path = storage_root / "records" / "legacy-rabi-001" / "record-manifest.json"
            copied_primary_text = primary_path.read_text(encoding="utf-8")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(receipt["artifact_posture"], "local_write_receipt")
        self.assertEqual(receipt["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            receipt["package"]["preview_classification"],
            "needs_review_before_acceptance",
        )
        self.assertEqual(receipt["storage_write"]["record_count"], 1)
        self.assertEqual(
            receipt["storage_write"]["written_paths"],
            [
                "records/legacy-rabi-001/primary.csv",
                "records/legacy-rabi-001/record-manifest.json",
            ],
        )
        self.assertEqual(
            receipt["accepted_measurements"][0]["source_package_path"],
            "measurements/legacy-rabi-001/primary.csv",
        )
        self.assertEqual(
            copied_primary_text,
            (PACKAGE / "measurements" / "legacy-rabi-001" / "primary.csv").read_text(
                encoding="utf-8"
            ),
        )
        self.assertEqual(
            manifest["manifest_schema"],
            "scopecat.accepted_handoff_measurement_record.v0",
        )
        self.assertEqual(manifest["source"]["kind"], "handoff_package_acceptance")
        self.assertEqual(manifest["source"]["package_integrity_check"], "not_performed")
        self.assertEqual(
            manifest["primary_data"]["package_checksum_validation"],
            "not_performed",
        )
        self.assertEqual(manifest["declared_preview"]["primary_row_count"], 5)
        self.assertEqual(manifest["declared_preview"]["preview_row_count"], 5)
        self.assertEqual(manifest["declared_preview"]["plot_series"][0]["point_count"], 5)
        self.assertEqual(manifest["linked_context"][0]["materialization"], "reference_only")
        self.assertEqual(manifest["linked_context"][0]["authority"], "scopecat_export_manifest")
        self.assertEqual(manifest["linked_context"][0]["relation"], "run_start_context")
        self.assertIn("reason", manifest["linked_context"][0])

    def test_rejects_unapproved_request_before_writing_storage(self) -> None:
        source = _acceptance_source()
        source["acceptance_request"]["review"]["approval_state"] = "needs_review"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "requires approved review"):
                accept_handoff_package(source, package_dir=PACKAGE, storage_root=storage_root)

            self.assertFalse((storage_root / "records").exists())

    def test_rejects_review_that_does_not_match_opened_package(self) -> None:
        source = _acceptance_source()
        source["acceptance_request"]["review"]["reviewed_package_id"] = "different-package"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "reviewed package id"):
                accept_handoff_package(source, package_dir=PACKAGE, storage_root=storage_root)

            self.assertFalse((storage_root / "records").exists())

    def test_rejects_reviewed_preview_classification_mismatch(self) -> None:
        source = _acceptance_source()
        source["acceptance_request"]["review"]["reviewed_preview_classification"] = (
            "preview_ready_for_opening"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "reviewed preview classification"):
                accept_handoff_package(source, package_dir=PACKAGE, storage_root=storage_root)

            self.assertFalse((storage_root / "records").exists())

    def test_rejects_noncanonical_storage_paths(self) -> None:
        source = _acceptance_source()
        source["acceptance_request"]["selected_measurements"][0]["primary_data_path"] = (
            "records/legacy-rabi-001/nested/primary.csv"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "primary_data_path must be"):
                accept_handoff_package(source, package_dir=PACKAGE, storage_root=storage_root)

            self.assertFalse((storage_root / "records").exists())

    def test_rejects_existing_record_directory_even_without_target_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            existing = storage_root / "records" / "legacy-rabi-001"
            existing.mkdir(parents=True)
            unrelated = existing / "notes.txt"
            unrelated.write_text("sentinel\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "record directory already exists"):
                accept_handoff_package(
                    _acceptance_source(),
                    package_dir=PACKAGE,
                    storage_root=storage_root,
                )

            self.assertEqual(unrelated.read_text(encoding="utf-8"), "sentinel\n")
            self.assertFalse((existing / "primary.csv").exists())
            self.assertFalse((existing / "record-manifest.json").exists())

    def test_rejects_package_and_storage_root_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            package_inside_storage = storage_root / "package"
            package_inside_storage.mkdir()

            with self.assertRaisesRegex(ValueError, "must be separate"):
                accept_handoff_package(
                    _acceptance_source(),
                    package_dir=package_inside_storage,
                    storage_root=storage_root,
                )

    def test_rejects_linked_context_payload_materialization(self) -> None:
        source = _acceptance_source()
        source["acceptance_request"]["materialization"]["linked_context"] = "copy_payloads"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "linked context materialization"):
                accept_handoff_package(source, package_dir=PACKAGE, storage_root=storage_root)

            self.assertFalse((storage_root / "records").exists())

    def test_rolls_back_primary_data_when_manifest_write_fails(self) -> None:
        real_write_new_file = filesystem_mutation.write_new_file

        def write_then_fail(
            storage_root: Path,
            relative_path: str,
            content: bytes,
            *,
            label: str,
        ) -> list[str]:
            if relative_path.endswith("record-manifest.json"):
                raise OSError("simulated manifest write failure")
            return real_write_new_file(storage_root, relative_path, content, label=label)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with mock.patch.object(
                filesystem_mutation, "write_new_file", side_effect=write_then_fail
            ):
                with self.assertRaisesRegex(OSError, "simulated manifest write failure"):
                    accept_handoff_package(
                        _acceptance_source(),
                        package_dir=PACKAGE,
                        storage_root=storage_root,
                    )

            self.assertFalse((storage_root / "records").exists())

    def test_records_full_primary_row_count_when_preview_rows_are_limited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = temp_root / PACKAGE.name
            shutil.copytree(PACKAGE, package_dir)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n"
                "4.98,0.12\n"
                "5.00,0.44\n"
                "5.02,0.81\n"
                "5.04,0.45\n"
                "5.06,0.13\n"
                "5.08,0.09\n",
                encoding="utf-8",
            )
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            accept_handoff_package(
                _acceptance_source(),
                package_dir=package_dir,
                storage_root=storage_root,
            )
            manifest = json.loads(
                (storage_root / "records" / "legacy-rabi-001" / "record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(manifest["declared_preview"]["primary_row_count"], 6)
        self.assertEqual(manifest["declared_preview"]["preview_row_count"], 5)

    def test_rejects_changed_acceptance_policy(self) -> None:
        source = copy.deepcopy(_acceptance_source())
        source["acceptance_policy"]["package_integrity"] = "verified"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "acceptance_policy"):
                accept_handoff_package(source, package_dir=PACKAGE, storage_root=storage_root)

            self.assertFalse((storage_root / "records").exists())

    def test_rejects_unexpected_acceptance_request_fields(self) -> None:
        source = _acceptance_source()
        source["acceptance_request"]["selected_measurements"][0]["display_path"] = (
            "HANDOFF_PACKAGE:/redacted/handoff-package-legacy-rabi-001"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "fields are unsupported"):
                accept_handoff_package(source, package_dir=PACKAGE, storage_root=storage_root)

            self.assertFalse((storage_root / "records").exists())


if __name__ == "__main__":
    unittest.main()

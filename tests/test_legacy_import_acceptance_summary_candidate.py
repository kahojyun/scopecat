from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.filesystem_mutation import filesystem as filesystem_mutation
from implementation_candidates.legacy_import_acceptance import accept_legacy_import

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_import_acceptance" / "basic_acceptance"


def _load_input() -> dict:
    return json.loads((FIXTURE / "legacy-import-acceptance-input.json").read_text(encoding="utf-8"))


class LegacyImportAcceptanceSummaryCandidateTest(unittest.TestCase):
    def test_accepts_reviewed_adapter_manifest_into_new_record_storage(self) -> None:
        source = _load_input()
        expected = json.loads(
            (FIXTURE / "expected-legacy-import-acceptance-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        with tempfile.TemporaryDirectory() as storage_dir:
            summary = accept_legacy_import(
                source,
                content_root=FIXTURE,
                storage_root=Path(storage_dir),
            )

            self.assertEqual(summary, expected)
            self.assertTrue((Path(storage_dir) / "records/legacy-rabi-001/primary.csv").is_file())
            self.assertTrue(
                (Path(storage_dir) / "records/legacy-rabi-001/record-manifest.json").is_file()
            )

    def test_written_manifest_preserves_adapter_source_and_context_references(self) -> None:
        source = _load_input()

        with tempfile.TemporaryDirectory() as storage_dir:
            accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))
            manifest = json.loads(
                (Path(storage_dir) / "records/legacy-rabi-001/record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(manifest["source_kind"], "adapter_authored_legacy_import")
        self.assertEqual(manifest["adapter"]["parsing_authority"], "external_adapter")
        self.assertEqual(manifest["source_identity"]["external_record_id"], "legacy-record-001")
        self.assertEqual(manifest["linked_context"][0]["link_id"], "legacy-001-parameter-snapshot")

    def test_source_data_is_copied_without_parsing_schema(self) -> None:
        source = _load_input()
        expected_bytes = (FIXTURE / "source-data/measurement.csv").read_bytes()

        with tempfile.TemporaryDirectory() as storage_dir:
            summary = accept_legacy_import(
                source, content_root=FIXTURE, storage_root=Path(storage_dir)
            )
            copied = (Path(storage_dir) / "records/legacy-rabi-001/primary.csv").read_bytes()

        self.assertEqual(copied, expected_bytes)
        attention = {item["code"]: item for item in summary["attention"]}
        self.assertEqual(
            attention["source_file_preflighted"]["does_not_claim"],
            "schema_or_scientific_validity",
        )

    def test_rejects_unapproved_acceptance_request(self) -> None:
        source = _load_input()
        source["acceptance_request"]["review"]["approval_state"] = "pending_review"

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "must be approved"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

    def test_rejects_adapter_manifest_that_is_not_ready(self) -> None:
        source = _load_input()
        source["adapter_manifest"]["primary_data"]["reference_state"] = "unavailable"
        source["adapter_manifest"]["primary_data"]["reason"] = "Adapter could not expose data."
        source["acceptance_request"]["review"]["reviewed_manifest_classification"] = (
            "blocked_pending_source_review"
        )

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "ready adapter manifest"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

    def test_rejects_source_digest_mismatch_before_writing(self) -> None:
        source = _load_input()
        source["acceptance_request"]["source_primary_data"]["declared_digest"] = (
            "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        )

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "digest does not match"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))
            self.assertFalse((Path(storage_dir) / "records").exists())

    def test_rejects_source_size_mismatch_before_writing(self) -> None:
        source = _load_input()
        source["acceptance_request"]["source_primary_data"]["size_bytes"] = 999

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "size does not match"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))
            self.assertFalse((Path(storage_dir) / "records").exists())

    def test_source_primary_data_facts_use_shared_primitive_shapes(self) -> None:
        source = _load_input()
        source["acceptance_request"]["source_primary_data"]["declared_digest"] = "8b335"

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "sha256-prefixed"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

        source = _load_input()
        source["acceptance_request"]["source_primary_data"]["size_bytes"] = True

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "size_bytes"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

    def test_rejects_symlink_content_parent(self) -> None:
        source = _load_input()

        with (
            tempfile.TemporaryDirectory() as content_dir,
            tempfile.TemporaryDirectory() as storage_dir,
        ):
            content_root = Path(content_dir)
            (content_root / "real-source").mkdir()
            os.symlink("real-source", content_root / "source-data")

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                accept_legacy_import(
                    source,
                    content_root=content_root,
                    storage_root=Path(storage_dir),
                )

    def test_rejects_existing_targets(self) -> None:
        source = _load_input()

        with tempfile.TemporaryDirectory() as storage_dir:
            target = Path(storage_dir) / "records/legacy-rabi-001"
            target.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "target already exists"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

    def test_destination_paths_must_stay_relative_under_record_dir(self) -> None:
        source = _load_input()
        source["acceptance_request"]["primary_data_path"] = "/tmp/primary.csv"

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "primary_data_path path"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

        source = _load_input()
        source["acceptance_request"]["manifest_path"] = "outside/record-manifest.json"

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "manifest_path must stay under record_dir"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

        source = _load_input()
        source["acceptance_request"]["manifest_path"] = (
            "records/legacy-rabi-001/primary.csv/manifest.json"
        )

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "output paths must not overlap"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

    def test_rejects_package_acceptance_claims(self) -> None:
        source = _load_input()
        source["acceptance_policy"]["package_acceptance"] = "performed"

        with tempfile.TemporaryDirectory() as storage_dir:
            with self.assertRaisesRegex(ValueError, "package_acceptance"):
                accept_legacy_import(source, content_root=FIXTURE, storage_root=Path(storage_dir))

    def test_rolls_back_primary_data_when_manifest_write_fails(self) -> None:
        source = _load_input()
        original_write = filesystem_mutation.write_new_file
        calls = 0

        def fail_on_manifest(
            storage_root: Path,
            relative_path: str,
            content: bytes,
            *,
            label: str,
        ) -> list[str]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated manifest write failure")
            return original_write(storage_root, relative_path, content, label=label)

        with tempfile.TemporaryDirectory() as storage_dir:
            filesystem_mutation.write_new_file = fail_on_manifest
            try:
                with self.assertRaisesRegex(OSError, "simulated manifest write failure"):
                    accept_legacy_import(
                        source, content_root=FIXTURE, storage_root=Path(storage_dir)
                    )
            finally:
                filesystem_mutation.write_new_file = original_write

            self.assertFalse((Path(storage_dir) / "records").exists())


if __name__ == "__main__":
    unittest.main()

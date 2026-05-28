from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from implementation_candidates.existing_record_update import append_existing_record_update
from implementation_candidates.existing_record_update import summary as update_summary

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "existing_record_update" / "basic_append_update"
CONTENT_ROOT = FIXTURE


def _load_input() -> dict:
    return json.loads((FIXTURE / "existing-record-update-input.json").read_text(encoding="utf-8"))


def _prepare_storage(temp_dir: str) -> Path:
    storage_root = Path(temp_dir) / "storage"
    shutil.copytree(FIXTURE / "existing-storage", storage_root)
    return storage_root


class ExistingRecordUpdateSummaryCandidateTest(unittest.TestCase):
    def test_writes_expected_append_update_without_replacing_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            original_primary = (
                storage_root / "records" / "run-4101-rabi" / "primary.csv"
            ).read_text(encoding="utf-8")
            original_manifest = (
                storage_root / "records" / "run-4101-rabi" / "record-manifest.json"
            ).read_text(encoding="utf-8")

            summary = append_existing_record_update(
                _load_input(),
                content_root=CONTENT_ROOT,
                storage_root=storage_root,
            )
            expected = json.loads(
                (FIXTURE / "expected-existing-record-update-summary.json").read_text(
                    encoding="utf-8"
                )
            )["candidate_summary"]

            self.assertEqual(summary, expected)
            self.assertEqual(
                (storage_root / "records" / "run-4101-rabi" / "primary.csv").read_text(
                    encoding="utf-8"
                ),
                original_primary,
            )
            self.assertEqual(
                (storage_root / "records" / "run-4101-rabi" / "record-manifest.json").read_text(
                    encoding="utf-8"
                ),
                original_manifest,
            )
            self.assertEqual(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").read_text(
                    encoding="utf-8"
                ),
                (FIXTURE / "chunks" / "chunk-2.csv").read_text(encoding="utf-8"),
            )
            receipt = json.loads(
                (
                    storage_root / "records" / "run-4101-rabi" / "updates" / "update-4101-2.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["measurement_record_id"], "run-4101-rabi")
            self.assertEqual(receipt["update_id"], "update-4101-2")
            self.assertEqual(
                receipt["append_segment"]["digest"],
                "sha256:d218b42c29bec955e1fd82b819f315610602254ca144a42fdf587ad4cf8678a7",
            )
            self.assertEqual(receipt["append_segment"]["size_bytes"], 20)
            self.assertEqual(receipt["append_chunk"]["previous_total_rows_recorded"], 3)
            self.assertEqual(receipt["append_chunk"]["total_rows_recorded"], 5)
            self.assertEqual(receipt["manifest_update"], "not_performed_append_receipt_only")
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_attention_records_all_boundary_deferrals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = append_existing_record_update(
                _load_input(),
                content_root=CONTENT_ROOT,
                storage_root=_prepare_storage(temp_dir),
            )

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            _load_input()["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["update_policy"]["crash_recovery"] = "defined"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "crash_recovery"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["update_policy"]["schema_migration"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected existing record update"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_update_requires_approval(self) -> None:
        source = _load_input()
        source["update_request"]["approval"]["approval_state"] = "proposed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must be approved"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_current_record_mismatch_is_refused_without_writing_update_files(self) -> None:
        source = _load_input()
        source["current_record"]["expected_primary_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)

            with self.assertRaisesRegex(ValueError, "manifest digest"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (
                    storage_root / "records" / "run-4101-rabi" / "updates" / "update-4101-2.json"
                ).exists()
            )
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_manifest_identity_mismatches_are_refused_under_lock(self) -> None:
        cases = [
            ("label", "Different label", "manifest label"),
            ("experiment_type", "ramsey", "manifest experiment_type"),
            ("target", "q1", "manifest target"),
            ("expected_points", 999, "manifest expected_points"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["measurement_record"][field] = value

                with tempfile.TemporaryDirectory() as temp_dir:
                    storage_root = _prepare_storage(temp_dir)

                    with self.assertRaisesRegex(ValueError, message):
                        append_existing_record_update(
                            source,
                            content_root=CONTENT_ROOT,
                            storage_root=storage_root,
                        )

                    self.assertFalse(
                        (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
                    )

    def test_manifest_current_record_mismatches_are_refused_under_lock(self) -> None:
        cases = [
            ("record_dir", "records/other-run", "manifest record_dir"),
            ("primary_data_format", "other_format", "manifest primary format"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()

                with tempfile.TemporaryDirectory() as temp_dir:
                    storage_root = _prepare_storage(temp_dir)
                    manifest_path = (
                        storage_root / "records" / "run-4101-rabi" / "record-manifest.json"
                    )
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if field == "record_dir":
                        manifest[field] = value
                    else:
                        manifest["primary_data"]["format"] = value
                    manifest_path.write_text(
                        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, message):
                        append_existing_record_update(
                            source,
                            content_root=CONTENT_ROOT,
                            storage_root=storage_root,
                        )

                    self.assertFalse(
                        (storage_root / "records" / "run-4101-rabi" / "segments").exists()
                    )

    def test_declared_chunk_digest_must_match_before_any_write(self) -> None:
        source = _load_input()
        source["append_chunk"]["declared_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)

            with self.assertRaisesRegex(ValueError, "digest does not match"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_missing_record_dir_is_refused_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "record directory is unavailable"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse((storage_root / "records").exists())

    def test_missing_manifest_is_refused_without_leaving_lock_or_update_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            manifest = storage_root / "records" / "run-4101-rabi" / "record-manifest.json"
            manifest.unlink()

            with self.assertRaisesRegex(ValueError, "manifest file is unavailable"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (
                    storage_root / "records" / "run-4101-rabi" / "updates" / "update-4101-2.json"
                ).exists()
            )

    def test_existing_lock_is_refused_without_writing_update_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            lock = storage_root / "records" / "run-4101-rabi" / "record-update.lock"
            lock.write_text("other-update\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "target already exists"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(lock.exists())
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )

    def test_existing_update_files_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            segment = storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv"
            segment.parent.mkdir()
            segment.write_text("already written\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "append segment already exists"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_existing_receipt_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            receipt = storage_root / "records" / "run-4101-rabi" / "updates" / "update-4101-2.json"
            receipt.parent.mkdir()
            receipt.write_text('{"already": "written"}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "receipt already exists"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_paths_must_stay_relative_and_under_record_dir(self) -> None:
        cases = [
            ("append_segment_path", "../chunk-2.csv", "path must be relative"),
            ("update_receipt_path", "updates/update-4101-2.json", "must stay under"),
            ("lock_path", "/tmp/record-update.lock", "path must be relative"),
            (
                "lock_path",
                "records/run-4101-rabi/locks/record-update.lock",
                "lock_path must be directly under record_dir",
            ),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["update_request"][field] = value

                with tempfile.TemporaryDirectory() as temp_dir:
                    with self.assertRaisesRegex(ValueError, message):
                        append_existing_record_update(
                            source,
                            content_root=CONTENT_ROOT,
                            storage_root=_prepare_storage(temp_dir),
                        )

    def test_counts_must_be_strict_positive_integers(self) -> None:
        cases = [
            ("sequence", True, "sequence"),
            ("size_bytes", 20.0, "size_bytes"),
            ("rows_recorded", 0, "rows_recorded"),
            ("previous_total_rows_recorded", -1, "previous_total_rows_recorded"),
            ("total_rows_recorded", True, "total_rows_recorded"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["append_chunk"][field] = value

                with tempfile.TemporaryDirectory() as temp_dir:
                    with self.assertRaisesRegex(ValueError, message):
                        append_existing_record_update(
                            source,
                            content_root=CONTENT_ROOT,
                            storage_root=_prepare_storage(temp_dir),
                        )

    def test_chunk_totals_must_match_current_progress_and_expected_points(self) -> None:
        source = _load_input()
        source["append_chunk"]["previous_total_rows_recorded"] = 2

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "previous total"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=_prepare_storage(temp_dir),
                )

        source = _load_input()
        source["append_chunk"]["total_rows_recorded"] = 6
        source["append_chunk"]["rows_recorded"] = 3

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected point count"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_existing_primary_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            primary = storage_root / "records" / "run-4101-rabi" / "primary.csv"
            primary.unlink()
            primary.symlink_to("redirected.csv")

            with self.assertRaisesRegex(ValueError, "primary data target is a symlink"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(primary.is_symlink())
            self.assertFalse((primary.parent / "redirected.csv").exists())

    def test_manifest_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            manifest = storage_root / "records" / "run-4101-rabi" / "record-manifest.json"
            manifest.unlink()
            manifest.symlink_to("redirected.json")

            with self.assertRaisesRegex(ValueError, "manifest target is a symlink"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(manifest.is_symlink())
            self.assertFalse((manifest.parent / "redirected.json").exists())
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_record_directory_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            record_dir = storage_root / "records" / "run-4101-rabi"
            shutil.rmtree(record_dir)
            outside = storage_root / "outside-record"
            outside.mkdir()
            record_dir.symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "record directory is a symlink"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(record_dir.is_symlink())

    def test_content_chunk_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            content_root = Path(temp_dir) / "content"
            shutil.copytree(FIXTURE, content_root)
            chunk = content_root / "chunks" / "chunk-2.csv"
            chunk.unlink()
            chunk.symlink_to("redirected.csv")

            with self.assertRaisesRegex(ValueError, "content file is a symlink"):
                append_existing_record_update(
                    _load_input(),
                    content_root=content_root,
                    storage_root=storage_root,
                )

            self.assertTrue(chunk.is_symlink())
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_output_parent_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            outside = storage_root / "outside-segments"
            outside.mkdir()
            segments = storage_root / "records" / "run-4101-rabi" / "segments"
            segments.symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(segments.is_symlink())
            self.assertFalse((outside / "chunk-2.csv").exists())
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_lock_target_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            lock = storage_root / "records" / "run-4101-rabi" / "record-update.lock"
            lock.symlink_to("redirected.lock")

            with self.assertRaisesRegex(ValueError, "target already exists"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(lock.is_symlink())
            self.assertFalse((lock.parent / "redirected.lock").exists())

    def test_storage_root_symlink_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            real_storage = _prepare_storage(temp_dir)
            storage_link = Path(temp_dir) / "storage-link"
            storage_link.symlink_to(real_storage, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "root must not be a symlink"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_link,
                )

    def test_receipt_target_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            receipt = storage_root / "records" / "run-4101-rabi" / "updates" / "update-4101-2.json"
            receipt.parent.mkdir()
            receipt.symlink_to("redirected.json")

            with self.assertRaisesRegex(ValueError, "receipt already exists"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(receipt.is_symlink())
            self.assertFalse((receipt.parent / "redirected.json").exists())
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )

    def test_receipt_parent_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            outside = storage_root / "outside-updates"
            outside.mkdir()
            updates = storage_root / "records" / "run-4101-rabi" / "updates"
            updates.symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                append_existing_record_update(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertTrue(updates.is_symlink())
            self.assertFalse((outside / "update-4101-2.json").exists())
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_duplicate_source_is_rejected_before_mutation(self) -> None:
        source = _load_input()
        source["update_request"]["update_receipt_path"] = source["update_request"][
            "append_segment_path"
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "output paths must differ"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_output_paths_must_not_overlap(self) -> None:
        source = _load_input()
        source["update_request"]["append_segment_path"] = (
            "records/run-4101-rabi/updates/update-4101-2.json/child.csv"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "output paths must not overlap"):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_receipt_write_failure_rolls_back_segment_and_releases_lock(self) -> None:
        source = _load_input()
        source["update_request"]["update_receipt_path"] = (
            "records/run-4101-rabi/updates/" + ("x" * 300) + ".json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)

            with self.assertRaises(OSError):
                append_existing_record_update(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (storage_root / "records" / "run-4101-rabi" / "record-update.lock").exists()
            )

    def test_lock_release_does_not_delete_replaced_lock(self) -> None:
        def replace_lock_and_fail(source: dict, storage_root: Path, segment_content: bytes):
            lock = storage_root / "records" / "run-4101-rabi" / "record-update.lock"
            lock.write_text("replacement-update\n", encoding="utf-8")
            raise RuntimeError("simulated write failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            lock = storage_root / "records" / "run-4101-rabi" / "record-update.lock"

            with patch.object(update_summary, "_write_update_files", replace_lock_and_fail):
                with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
                    append_existing_record_update(
                        _load_input(),
                        content_root=CONTENT_ROOT,
                        storage_root=storage_root,
                    )

            self.assertEqual(lock.read_text(encoding="utf-8"), "replacement-update\n")


if __name__ == "__main__":
    unittest.main()

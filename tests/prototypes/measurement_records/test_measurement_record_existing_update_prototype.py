from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records.existing_record_update import (
    MeasurementRecordExistingAppendChunk,
    MeasurementRecordExistingUpdateRequest,
    append_existing_measurement_record_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "existing_record_update"
    / "basic_append_update"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source(**overrides: object) -> dict:
    source = _read_json(FIXTURE / "existing-record-update-input.json")
    for key, value in overrides.items():
        source[key] = value
    return source


def _request(source: dict) -> MeasurementRecordExistingUpdateRequest:
    return MeasurementRecordExistingUpdateRequest.from_dict(source["update_request"])


def _append_chunk(source: dict) -> MeasurementRecordExistingAppendChunk:
    return MeasurementRecordExistingAppendChunk.from_dict(source["append_chunk"])


def _append_existing(source: dict, *, content_root: Path, storage_root: Path):
    return append_existing_measurement_record_from_request(
        _request(source),
        append_chunk=_append_chunk(source),
        content_root=content_root,
        current_record=source["current_record"],
        measurement_record=source["measurement_record"],
        storage_root=storage_root,
    )


class MeasurementRecordExistingUpdatePrototypeTest(unittest.TestCase):
    def test_approved_append_update_records_append_without_replacing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            shutil.copytree(FIXTURE / "existing-storage", storage_root)
            shutil.copytree(FIXTURE / "chunks", content_root / "chunks")

            manifest_before = (
                storage_root / "records" / "run-4101-rabi" / "record-manifest.json"
            ).read_bytes()
            primary_before = (
                storage_root / "records" / "run-4101-rabi" / "primary.csv"
            ).read_bytes()

            run = _append_existing(
                _source(),
                content_root=content_root,
                storage_root=storage_root,
            )

            record_dir = storage_root / "records" / "run-4101-rabi"
            segment = record_dir / "segments" / "chunk-2.csv"
            receipt = record_dir / "updates" / "update-4101-2.json"

            self.assertTrue(segment.is_file())
            self.assertTrue(receipt.is_file())
            self.assertFalse((record_dir / "record-update.lock").exists())
            self.assertEqual((record_dir / "record-manifest.json").read_bytes(), manifest_before)
            self.assertEqual((record_dir / "primary.csv").read_bytes(), primary_before)

        summary = run.to_dict()
        self.assertEqual(
            set(summary),
            {
                "measurement_record",
                "current_record",
                "update_request",
                "append_chunk",
                "write_results",
            },
        )
        self.assertEqual(run.classification, "existing_record_append_recorded")
        self.assertEqual(run.write_results[0]["kind"], "append_segment")
        self.assertEqual(summary["measurement_record"]["measurement_record_id"], "run-4101-rabi")
        self.assertEqual(summary["update_request"]["update_id"], "update-4101-2")
        self.assertEqual(summary["append_chunk"]["chunk_id"], "chunk-4101-2")
        self.assertEqual(summary["append_chunk"]["rows_recorded"], 2)
        self.assertEqual(summary["append_chunk"]["total_rows_recorded"], 5)
        self.assertEqual(summary["write_results"][0]["kind"], "append_segment")
        self.assertEqual(summary["write_results"][1]["kind"], "update_receipt")
        self.assertEqual(
            set(summary["write_results"][0]),
            {"path", "kind", "result", "bytes_written", "digest"},
        )

    def test_typed_request_and_chunk_validate_boundary(self) -> None:
        source = _source()
        request = _request(source)
        chunk = _append_chunk(source)

        self.assertEqual(request.update_id, "update-4101-2")
        self.assertEqual(chunk.total_rows_recorded, 5)

    def test_unapproved_request_blocks_before_mutation(self) -> None:
        source = _source()
        source["update_request"]["approval"]["approval_state"] = "needs_review"
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            shutil.copytree(FIXTURE / "existing-storage", storage_root)
            shutil.copytree(FIXTURE / "chunks", content_root / "chunks")

            with self.assertRaisesRegex(ValueError, "must be approved"):
                _append_existing(
                    source,
                    content_root=content_root,
                    storage_root=storage_root,
                )

            self.assertFalse((storage_root / "records" / "run-4101-rabi" / "segments").exists())

    def test_preexisting_lock_or_update_target_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            shutil.copytree(FIXTURE / "existing-storage", storage_root)
            shutil.copytree(FIXTURE / "chunks", content_root / "chunks")
            lock = storage_root / "records" / "run-4101-rabi" / "record-update.lock"
            lock.write_text("other-writer\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "lock target already exists"):
                _append_existing(
                    _source(),
                    content_root=content_root,
                    storage_root=storage_root,
                )

            self.assertEqual(lock.read_text(encoding="utf-8"), "other-writer\n")

    def test_digest_mismatch_releases_lock_and_does_not_write_update_files(self) -> None:
        source = _source()
        source["append_chunk"]["declared_digest"] = "sha256:" + "0" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            shutil.copytree(FIXTURE / "existing-storage", storage_root)
            shutil.copytree(FIXTURE / "chunks", content_root / "chunks")
            record_dir = storage_root / "records" / "run-4101-rabi"

            with self.assertRaisesRegex(ValueError, "digest does not match"):
                _append_existing(
                    source,
                    content_root=content_root,
                    storage_root=storage_root,
                )

            self.assertFalse((record_dir / "record-update.lock").exists())
            self.assertFalse((record_dir / "segments" / "chunk-2.csv").exists())
            self.assertFalse((record_dir / "updates" / "update-4101-2.json").exists())

    def test_rejects_manifest_replacement_or_path_escape_boundary(self) -> None:
        source = _source()
        source["update_request"]["update_receipt_path"] = "records/run-4101-rabi"

        with self.assertRaisesRegex(ValueError, "must stay under record_dir|must not overlap"):
            _append_existing(
                source,
                content_root=FIXTURE,
                storage_root=FIXTURE / "existing-storage",
            )

    def test_outputs_do_not_alias_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            shutil.copytree(FIXTURE / "existing-storage", storage_root)
            shutil.copytree(FIXTURE / "chunks", content_root / "chunks")
            source = _source()
            original = copy.deepcopy(source)

            run = _append_existing(
                source,
                content_root=content_root,
                storage_root=storage_root,
            )
            summary = run.to_dict()
            summary["measurement_record"]["label"] = "mutated"
            source["measurement_record"]["label"] = "mutated"

        self.assertEqual(run.to_dict()["measurement_record"]["label"], "Partial Rabi run 4101")
        self.assertNotEqual(source, original)


if __name__ == "__main__":
    unittest.main()

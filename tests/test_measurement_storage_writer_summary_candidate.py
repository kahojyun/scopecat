from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.measurement_storage_writer import write_measurement_storage

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurement_storage_writer" / "basic_append"
CONTENT_ROOT = FIXTURE


def _load_input() -> dict:
    return json.loads((FIXTURE / "storage-writer-input.json").read_text(encoding="utf-8"))


class MeasurementStorageWriterSummaryCandidateTest(unittest.TestCase):
    def test_writes_expected_record_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            summary = write_measurement_storage(
                _load_input(),
                content_root=CONTENT_ROOT,
                storage_root=storage_root,
            )
            expected = json.loads(
                (FIXTURE / "expected-storage-writer-summary.json").read_text(encoding="utf-8")
            )["candidate_summary"]

            self.assertEqual(summary, expected)
            self.assertEqual(
                (storage_root / "records" / "run-3101-rabi" / "primary.csv").read_text(
                    encoding="utf-8"
                ),
                (
                    (FIXTURE / "chunks" / "chunk-1.csv").read_text(encoding="utf-8")
                    + (FIXTURE / "chunks" / "chunk-2.csv").read_text(encoding="utf-8")
                ),
            )
            manifest = json.loads(
                (storage_root / "records" / "run-3101-rabi" / "record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["measurement_record_id"], "run-3101-rabi")
            self.assertEqual(manifest["primary_data"]["rows_recorded"], 5)

    def test_attention_records_all_boundary_deferrals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = write_measurement_storage(
                _load_input(),
                content_root=CONTENT_ROOT,
                storage_root=Path(temp_dir),
            )

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            _load_input()["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["storage_policy"]["hardware_control"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "hardware_control"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["storage_policy"]["import_acceptance"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected measurement storage writer"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_write_requires_approval(self) -> None:
        source = _load_input()
        source["storage_request"]["approval"]["approval_state"] = "proposed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must be approved"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_existing_record_dir_is_refused_without_writing_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            record_dir = storage_root / "records" / "run-3101-rabi"
            record_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "target already exists"):
                write_measurement_storage(
                    _load_input(),
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse((record_dir / "primary.csv").exists())
            self.assertFalse((record_dir / "record-manifest.json").exists())

    def test_declared_digest_must_match_chunk_before_any_write(self) -> None:
        source = _load_input()
        source["append_chunks"][1]["declared_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "digest does not match"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=storage_root,
                )

            self.assertFalse((storage_root / "records" / "run-3101-rabi" / "primary.csv").exists())
            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "record-manifest.json").exists()
            )

    def test_duplicate_chunk_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["append_chunks"][1])
        duplicate["sequence"] = 3
        duplicate["rows_recorded"] = 1
        duplicate["total_rows_recorded"] = 6
        source["append_chunks"].append(duplicate)

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "duplicate chunk_id"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_chunk_totals_must_match_append_progress(self) -> None:
        source = _load_input()
        source["append_chunks"][1]["total_rows_recorded"] = 4

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "previous total plus rows_recorded"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_storage_paths_must_stay_relative_and_under_record_dir(self) -> None:
        source = _load_input()
        source["storage_request"]["primary_data_path"] = "../primary.csv"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "primary_data_path path"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

        source = _load_input()
        source["storage_request"]["manifest_path"] = "outside/manifest.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "manifest_path must stay under record_dir"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_storage_outputs_must_be_files_strictly_under_record_dir(self) -> None:
        source = _load_input()
        source["storage_request"]["primary_data_path"] = "records/run-3101-rabi"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "primary_data_path must stay under record_dir"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_storage_output_paths_must_not_overlap(self) -> None:
        source = _load_input()
        source["storage_request"]["primary_data_path"] = "records/run-3101-rabi/primary.csv"
        source["storage_request"]["manifest_path"] = "records/run-3101-rabi/primary.csv/meta.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "output paths must not overlap"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )

    def test_append_counts_must_be_strict_integers(self) -> None:
        cases = [
            ("measurement_record", "expected_points", True, "expected_points"),
            ("append_chunks", "sequence", 1.0, "sequence"),
            ("append_chunks", "size_bytes", True, "size_bytes"),
            ("append_chunks", "rows_recorded", 3.0, "rows_recorded"),
            ("append_chunks", "total_rows_recorded", True, "total_rows_recorded"),
        ]

        for owner, field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                if owner == "measurement_record":
                    source[owner][field] = value
                else:
                    source[owner][0][field] = value

                with tempfile.TemporaryDirectory() as temp_dir:
                    with self.assertRaisesRegex(ValueError, message):
                        write_measurement_storage(
                            source,
                            content_root=CONTENT_ROOT,
                            storage_root=Path(temp_dir),
                        )

    def test_preview_plot_candidate_must_reference_stored_primary_data(self) -> None:
        source = _load_input()
        source["declared_preview_metadata"]["plot_candidates"][0]["source"] = (
            "records/run-3101-rabi/wrong.csv"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "plot candidate source"):
                write_measurement_storage(
                    source,
                    content_root=CONTENT_ROOT,
                    storage_root=Path(temp_dir),
                )


if __name__ == "__main__":
    unittest.main()

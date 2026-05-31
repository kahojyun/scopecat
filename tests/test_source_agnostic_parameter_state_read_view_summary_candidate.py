from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.calibration_parameter_state_storage import (
    write_calibration_parameter_state_storage,
)
from implementation_candidates.source_agnostic_parameter_state_read_view import (
    read_source_agnostic_parameter_state_view,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "source_agnostic_parameter_state_read_view" / "basic_read"
ADAPTER_STORAGE = ROOT / "tests" / "fixtures" / "parameter_state_storage_read_view" / "basic_read"
CALIBRATION_STORAGE_INPUT = (
    ROOT / "tests" / "fixtures" / "calibration_parameter_state_storage" / "basic_write"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "read-view-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-read-view-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _storage_root(temp_dir: str) -> Path:
    storage = Path(temp_dir) / "storage"
    shutil.copytree(ADAPTER_STORAGE / "storage", storage)
    calibration_input = json.loads(
        (CALIBRATION_STORAGE_INPUT / "storage-input.json").read_text(encoding="utf-8")
    )
    write_calibration_parameter_state_storage(calibration_input, storage_root=storage)
    return storage


class SourceAgnosticParameterStateReadViewSummaryCandidateTest(unittest.TestCase):
    def test_reads_expected_adapter_and_calibration_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_root(temp_dir)
            source = _load_input()
            before_files = {
                request["request_id"]: (storage_root / request["manifest_path"]).read_bytes()
                + (storage_root / request["receipt_path"]).read_bytes()
                for request in source["read_requests"]
            }

            summary = read_source_agnostic_parameter_state_view(source, storage_root=storage_root)

            after_files = {
                request["request_id"]: (storage_root / request["manifest_path"]).read_bytes()
                + (storage_root / request["receipt_path"]).read_bytes()
                for request in source["read_requests"]
            }

        self.assertEqual(summary, _expected_candidate())
        self.assertEqual(before_files, after_files)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = _load_input()
            summary = read_source_agnostic_parameter_state_view(
                source, storage_root=_storage_root(temp_dir)
            )

        source["read_view_policy"]["catalog_discovery"] = "performed"
        source["read_requests"][0]["state_id"] = "mutated"

        self.assertEqual(summary["read_view_policy"]["catalog_discovery"], "not_performed")
        self.assertEqual(
            summary["stored_states"][0]["read_request"]["state_id"],
            "param-state-imported-0001",
        )

    def test_policy_must_match_expected_shape(self) -> None:
        source = _load_input()
        source["read_view_policy"]["catalog_discovery"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "catalog_discovery"):
                read_source_agnostic_parameter_state_view(
                    source, storage_root=_storage_root(temp_dir)
                )

    def test_paths_must_be_relative_distinct_and_non_overlapping(self) -> None:
        source = _load_input()
        source["read_requests"][0]["manifest_path"] = "../parameter-state.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "manifest_path path must be relative"):
                read_source_agnostic_parameter_state_view(
                    source, storage_root=_storage_root(temp_dir)
                )

        source = _load_input()
        source["read_requests"][0]["receipt_path"] = source["read_requests"][0]["manifest_path"]

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must differ"):
                read_source_agnostic_parameter_state_view(
                    source, storage_root=_storage_root(temp_dir)
                )

    def test_declared_manifest_digest_mismatch_is_review_finding(self) -> None:
        source = _load_input()
        source["read_requests"][1]["expected_manifest_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            summary = read_source_agnostic_parameter_state_view(
                source, storage_root=_storage_root(temp_dir)
            )

        self.assertEqual(
            summary["classification"],
            "one_or_more_parameter_states_observed_with_mismatch",
        )
        self.assertIn(
            "source-agnostic-read-calibration-0001_manifest_digest_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_missing_manifest_returns_unavailable_state_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_root(temp_dir)
            source = _load_input()
            (storage_root / source["read_requests"][1]["manifest_path"]).unlink()

            summary = read_source_agnostic_parameter_state_view(source, storage_root=storage_root)

        self.assertEqual(
            summary["classification"],
            "one_or_more_parameter_states_unavailable_for_review",
        )
        self.assertIsNone(summary["stored_states"][1]["parameter_state"])
        self.assertEqual(summary["stored_states"][1]["trusted_entries"], [])

    def test_receipt_manifest_continuity_mismatch_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_root(temp_dir)
            source = _load_input()
            receipt_path = storage_root / source["read_requests"][1]["receipt_path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["manifest"]["digest"] = (
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            )
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            source["read_requests"][1]["expected_receipt_digest"] = _digest(receipt_path)
            source["read_requests"][1]["expected_receipt_size_bytes"] = receipt_path.stat().st_size

            summary = read_source_agnostic_parameter_state_view(source, storage_root=storage_root)

        self.assertIn(
            "source-agnostic-read-calibration-0001_receipt_manifest_digest_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_manifest_source_kind_must_match_request(self) -> None:
        source = _load_input()
        source["read_requests"][0]["source_kind"] = "calibration_handoff"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "source_kind"):
                read_source_agnostic_parameter_state_view(
                    source, storage_root=_storage_root(temp_dir)
                )

    def test_calibration_entry_sources_must_reference_typed_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_root(temp_dir)
            source = _load_input()
            manifest_path = storage_root / source["read_requests"][1]["manifest_path"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state"]["entries"][0]["source_ids"] = ["missing-source"]
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "missing provenance source"):
                read_source_agnostic_parameter_state_view(source, storage_root=storage_root)

    def test_symlink_targets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_root(temp_dir)
            source = _load_input()
            manifest_path = storage_root / source["read_requests"][0]["manifest_path"]
            manifest_copy = manifest_path.with_name("parameter-state-copy.json")
            shutil.copyfile(manifest_path, manifest_copy)
            manifest_path.unlink()
            manifest_path.symlink_to(manifest_copy)

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                read_source_agnostic_parameter_state_view(source, storage_root=storage_root)


if __name__ == "__main__":
    unittest.main()

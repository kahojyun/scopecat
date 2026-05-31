from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.parameter_state_storage_read_view import (
    read_parameter_state_storage_view,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_state_storage_read_view" / "basic_read"


def _load_input() -> dict:
    return json.loads((FIXTURE / "read-view-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-read-view-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


def _storage_copy(temp_dir: str) -> Path:
    target = Path(temp_dir) / "storage"
    shutil.copytree(FIXTURE / "storage", target)
    return target


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


class ParameterStateStorageReadViewSummaryCandidateTest(unittest.TestCase):
    def test_reads_expected_summary_without_mutating_storage(self) -> None:
        source = _load_input()
        manifest_path = FIXTURE / "storage" / source["read_request"]["manifest_path"]
        receipt_path = FIXTURE / "storage" / source["read_request"]["receipt_path"]
        before = {
            "manifest": manifest_path.read_bytes(),
            "receipt": receipt_path.read_bytes(),
        }

        summary = read_parameter_state_storage_view(source, storage_root=FIXTURE / "storage")

        self.assertEqual(summary, _expected_candidate())
        self.assertEqual(manifest_path.read_bytes(), before["manifest"])
        self.assertEqual(receipt_path.read_bytes(), before["receipt"])

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = read_parameter_state_storage_view(source, storage_root=FIXTURE / "storage")

        source["read_view_policy"]["catalog_discovery"] = "performed"
        source["read_request"]["state_id"] = "mutated"

        self.assertEqual(summary["read_view_policy"]["catalog_discovery"], "not_performed")
        self.assertEqual(summary["read_request"]["state_id"], "param-state-imported-0001")

    def test_policy_must_match_expected_shape(self) -> None:
        source = _load_input()
        source["read_view_policy"]["catalog_discovery"] = "performed"

        with self.assertRaisesRegex(ValueError, "catalog_discovery"):
            read_parameter_state_storage_view(source, storage_root=FIXTURE / "storage")

    def test_paths_must_be_relative_distinct_and_non_overlapping(self) -> None:
        source = _load_input()
        source["read_request"]["manifest_path"] = "../parameter-state.json"

        with self.assertRaisesRegex(ValueError, "manifest_path path must be relative"):
            read_parameter_state_storage_view(source, storage_root=FIXTURE / "storage")

        source = _load_input()
        source["read_request"]["receipt_path"] = source["read_request"]["manifest_path"]

        with self.assertRaisesRegex(ValueError, "must differ"):
            read_parameter_state_storage_view(source, storage_root=FIXTURE / "storage")

        source = _load_input()
        source["read_request"]["receipt_path"] = (
            "parameter-states/param-state-imported-0001/parameter-state.json/receipt.json"
        )

        with self.assertRaisesRegex(ValueError, "must not overlap"):
            read_parameter_state_storage_view(source, storage_root=FIXTURE / "storage")

    def test_declared_manifest_digest_mismatch_is_review_finding(self) -> None:
        source = _load_input()
        source["read_request"]["expected_manifest_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        summary = read_parameter_state_storage_view(source, storage_root=FIXTURE / "storage")

        self.assertEqual(summary["classification"], "stored_parameter_state_observed_with_mismatch")
        self.assertIn(
            "manifest_digest_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )
        self.assertIn(
            "receipt_manifest_declared_digest_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_missing_manifest_returns_unavailable_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_copy(temp_dir)
            source = _load_input()
            (storage_root / source["read_request"]["manifest_path"]).unlink()

            summary = read_parameter_state_storage_view(source, storage_root=storage_root)

        self.assertEqual(summary["classification"], "stored_parameter_state_unavailable_for_review")
        self.assertIsNone(summary["parameter_state"])
        self.assertEqual(summary["trusted_entries"], [])
        self.assertIn(
            "manifest_unavailable",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_receipt_manifest_continuity_mismatch_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_copy(temp_dir)
            source = _load_input()
            receipt_path = storage_root / source["read_request"]["receipt_path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["manifest"]["digest"] = (
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            )
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            source["read_request"]["expected_receipt_digest"] = _digest(receipt_path)
            source["read_request"]["expected_receipt_size_bytes"] = receipt_path.stat().st_size

            summary = read_parameter_state_storage_view(source, storage_root=storage_root)

        self.assertEqual(summary["classification"], "stored_parameter_state_observed_with_mismatch")
        self.assertIn(
            "receipt_manifest_digest_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_manifest_entry_sources_must_reference_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_copy(temp_dir)
            source = _load_input()
            manifest_path = storage_root / source["read_request"]["manifest_path"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state"]["entries"][0]["source_ids"] = ["missing-source"]
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "missing provenance source"):
                read_parameter_state_storage_view(source, storage_root=storage_root)

    def test_symlink_targets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _storage_copy(temp_dir)
            source = _load_input()
            manifest_path = storage_root / source["read_request"]["manifest_path"]
            manifest_copy = manifest_path.with_name("parameter-state-copy.json")
            shutil.copyfile(manifest_path, manifest_copy)
            manifest_path.unlink()
            manifest_path.symlink_to(manifest_copy)

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                read_parameter_state_storage_view(source, storage_root=storage_root)


if __name__ == "__main__":
    unittest.main()

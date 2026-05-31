from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.parameter_state_storage_writer import write_parameter_state_storage

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "parameter_state_storage_writer" / "basic_write"


def _load_input() -> dict:
    return json.loads((FIXTURE / "storage-writer-input.json").read_text(encoding="utf-8"))


class ParameterStateStorageWriterSummaryCandidateTest(unittest.TestCase):
    def test_writes_expected_files_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            summary = write_parameter_state_storage(_load_input(), storage_root=storage_root)
            expected = json.loads(
                (FIXTURE / "expected-storage-writer-summary.json").read_text(encoding="utf-8")
            )["candidate_summary"]

            self.assertEqual(summary, expected)
            manifest_path = (
                storage_root
                / "parameter-states"
                / "param-state-imported-0001"
                / "parameter-state.json"
            )
            receipt_path = (
                storage_root
                / "parameter-states"
                / "param-state-imported-0001"
                / "write-receipt.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["state"]["state_id"], "param-state-imported-0001")
        self.assertEqual(manifest["storage_non_claims"]["hardware_write_back"], "not_performed")
        self.assertEqual(receipt["state_id"], "param-state-imported-0001")
        self.assertEqual(receipt["storage_mutation"], "performed")

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = write_parameter_state_storage(source, storage_root=Path(temp_dir))

        source["reviewed_managed_parameter_state"]["entries"][0]["value"] = {"mutated": ["value"]}
        source["provenance"]["legacy_sources"][0]["display_path"] = "mutated"

        self.assertEqual(summary["parameter_state"]["entry_count"], 2)
        self.assertEqual(
            summary["provenance"]["legacy_sources"][0]["display_path"],
            "LEGACY_PARAMETER_SOURCE:/redacted/settings/parameters.json",
        )

    def test_policy_must_match_expected_shape(self) -> None:
        source = _load_input()
        source["storage_policy"]["legacy_parser"] = "available"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected parameter state storage writer"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_write_requires_approval(self) -> None:
        source = _load_input()
        source["storage_request"]["approval"]["approval_state"] = "proposed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must be approved"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_existing_state_dir_is_refused_without_writing_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state_dir = storage_root / "parameter-states" / "param-state-imported-0001"
            state_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "target already exists"):
                write_parameter_state_storage(_load_input(), storage_root=storage_root)

            self.assertFalse((state_dir / "parameter-state.json").exists())
            self.assertFalse((state_dir / "write-receipt.json").exists())

    def test_storage_paths_must_be_relative_and_under_state_dir(self) -> None:
        source = _load_input()
        source["storage_request"]["manifest_path"] = "../parameter-state.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "manifest_path path"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

        source = _load_input()
        source["storage_request"]["receipt_path"] = "outside/write-receipt.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "receipt_path must stay under state_dir"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_storage_output_paths_must_not_overlap(self) -> None:
        source = _load_input()
        source["storage_request"]["receipt_path"] = (
            "parameter-states/param-state-imported-0001/parameter-state.json/receipt.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "output paths must not overlap"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_managed_state_entries_and_trusted_paths_must_match(self) -> None:
        source = _load_input()
        source["reviewed_managed_parameter_state"]["trusted_entry_paths"] = [
            "qubits.qA.drive_frequency_hz"
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "trusted paths must match entries"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_entry_sources_must_reference_provenance_sources(self) -> None:
        source = _load_input()
        source["reviewed_managed_parameter_state"]["entries"][0]["source_ids"] = ["missing-source"]

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "missing provenance source"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_side_effect_claims_must_match_storage_boundary(self) -> None:
        source = _load_input()
        source["side_effect_claims"]["hardware_write_back"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "hardware_write_back"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

        source = _load_input()
        source["side_effect_claims"]["storage_mutation"] = "not_performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "storage_mutation"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_expected_digest_mismatch_blocks_before_write(self) -> None:
        source = _load_input()
        source["expected_write_results"][0]["digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "expected manifest digest"):
                write_parameter_state_storage(source, storage_root=storage_root)

            self.assertFalse(
                (
                    storage_root
                    / "parameter-states"
                    / "param-state-imported-0001"
                    / "parameter-state.json"
                ).exists()
            )

    def test_duplicate_provenance_sources_are_rejected(self) -> None:
        source = _load_input()
        source["provenance"]["legacy_sources"].append(
            copy.deepcopy(source["provenance"]["legacy_sources"][0])
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "duplicate source_id"):
                write_parameter_state_storage(source, storage_root=Path(temp_dir))


if __name__ == "__main__":
    unittest.main()

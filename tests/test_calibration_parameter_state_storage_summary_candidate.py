from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.calibration_parameter_state_storage import (
    write_calibration_parameter_state_storage,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_parameter_state_storage" / "basic_write"


def _load_input() -> dict:
    return json.loads((FIXTURE / "storage-input.json").read_text(encoding="utf-8"))


class CalibrationParameterStateStorageSummaryCandidateTest(unittest.TestCase):
    def test_writes_expected_files_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            summary = write_calibration_parameter_state_storage(
                _load_input(), storage_root=storage_root
            )
            expected = json.loads(
                (FIXTURE / "expected-storage-summary.json").read_text(encoding="utf-8")
            )["candidate_summary"]

            self.assertEqual(summary, expected)
            manifest_path = (
                storage_root / "parameter-states" / "param-state-0008" / "parameter-state.json"
            )
            receipt_path = (
                storage_root / "parameter-states" / "param-state-0008" / "write-receipt.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["state"]["state_id"], "param-state-0008")
        self.assertEqual(
            manifest["provenance"]["source_kind"],
            "calibration_accepted_write_handoff",
        )
        self.assertEqual(receipt["state_id"], "param-state-0008")
        self.assertEqual(receipt["storage_mutation"], "performed")

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

        source["calibration_parameter_state_intake_input"]["managed_parameter_state"]["entries"][0][
            "value"
        ] = {"mutated": ["value"]}
        source["storage_policy"]["hardware_write_back"] = "performed"

        self.assertEqual(summary["parameter_state"]["state_id"], "param-state-0008")
        self.assertEqual(summary["provenance"]["source_handoff_id"], "handoff-rabi-qA-pi-amp-0001")
        self.assertEqual(summary["storage_policy"]["hardware_write_back"], "not_performed")

    def test_policy_must_match_expected_shape(self) -> None:
        source = _load_input()
        source["storage_policy"]["legacy_source_parsing"] = "not_performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected calibration parameter-state"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_write_requires_approval(self) -> None:
        source = _load_input()
        source["storage_request"]["approval"]["approval_state"] = "proposed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must be approved"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_existing_state_dir_is_refused_without_writing_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state_dir = storage_root / "parameter-states" / "param-state-0008"
            state_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "target already exists"):
                write_calibration_parameter_state_storage(_load_input(), storage_root=storage_root)

            self.assertFalse((state_dir / "parameter-state.json").exists())
            self.assertFalse((state_dir / "write-receipt.json").exists())

    def test_storage_paths_must_be_relative_and_under_state_dir(self) -> None:
        source = _load_input()
        source["storage_request"]["manifest_path"] = "../parameter-state.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "manifest_path path"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

        source = _load_input()
        source["storage_request"]["receipt_path"] = "outside/write-receipt.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "receipt_path must stay under state_dir"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_storage_request_must_match_intake_identity(self) -> None:
        source = _load_input()
        source["storage_request"]["source_handoff_id"] = "handoff-other"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "source_handoff_id"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

        source = _load_input()
        source["storage_request"]["state_id"] = "param-state-other"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "state_id"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_side_effect_claims_must_match_storage_boundary(self) -> None:
        source = _load_input()
        source["side_effect_claims"]["hardware_write_back"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "hardware_write_back"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

        source = _load_input()
        source["side_effect_claims"]["storage_mutation"] = "not_performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "storage_mutation"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))

    def test_expected_digest_mismatch_blocks_before_write(self) -> None:
        source = _load_input()
        source["expected_write_results"][0]["digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "expected manifest digest"):
                write_calibration_parameter_state_storage(source, storage_root=storage_root)

            self.assertFalse(
                (
                    storage_root / "parameter-states" / "param-state-0008" / "parameter-state.json"
                ).exists()
            )

    def test_nested_intake_is_validated_before_storage(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(
            source["calibration_parameter_state_intake_input"]["managed_parameter_state"][
                "entries"
            ][0]
        )
        source["calibration_parameter_state_intake_input"]["managed_parameter_state"]["entries"][
            1
        ] = duplicate

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "duplicate path"):
                write_calibration_parameter_state_storage(source, storage_root=Path(temp_dir))


if __name__ == "__main__":
    unittest.main()

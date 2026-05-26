from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_round_trip import (
    build_handoff_package_round_trip_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "handoff_package_writer" / "basic_package"
STORAGE_ROOT = FIXTURE / "storage"


def _load_input() -> dict:
    return json.loads((FIXTURE / "package-writer-input.json").read_text(encoding="utf-8"))


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


class HandoffPackageRoundTripCandidateTest(unittest.TestCase):
    def test_writer_output_opens_through_read_view_for_reader_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = build_handoff_package_round_trip_summary(
                _load_input(),
                storage_root=STORAGE_ROOT,
                package_root=Path(temp_dir),
            )

        self.assertEqual(summary["artifact_posture"], "review_summary")
        self.assertEqual(summary["round_trip_policy"]["package_write"], "performed")
        self.assertEqual(summary["round_trip_policy"]["read_view_open"], "performed")
        self.assertEqual(summary["round_trip_policy"]["package_acceptance"], "not_performed")
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            summary["package"]["preview_classification"],
            "needs_review_before_acceptance",
        )
        self.assertEqual(
            summary["generated_artifact"]["package_directory_name"],
            summary["package"]["package_id"],
        )
        self.assertTrue(summary["generated_artifact"]["package_directory_created"])
        self.assertTrue(summary["generated_artifact"]["manifest_created"])
        self.assertEqual(summary["local_write_receipt"]["artifact_posture"], "local_write_receipt")
        self.assertEqual(
            summary["local_write_receipt"]["retained_in_round_trip_summary"],
            True,
        )

        measurement = summary["read_view"]["measurements"][0]
        self.assertEqual(measurement["measurement_record_id"], "legacy-rabi-001")
        self.assertEqual(measurement["primary_table"]["columns"], ["drive_frequency", "signal"])
        self.assertEqual(measurement["primary_table"]["row_count"], 5)
        self.assertEqual(measurement["preview_table"]["columns"], ["drive_frequency", "signal"])
        self.assertEqual(measurement["preview_table"]["row_count"], 5)
        self.assertEqual(
            measurement["plot_series"],
            [{"x": "drive_frequency", "y": "signal", "point_count": 5}],
        )
        self.assertEqual(measurement["integrity_check"], "not_performed")
        self.assertEqual(
            measurement["linked_context_ids"],
            ["package-legacy-001-parameter-snapshot"],
        )
        self.assertEqual(
            measurement["finding_codes"],
            ["linked_context_not_packaged_visible_reference"],
        )
        self.assertEqual(
            summary["read_view"]["finding_codes"],
            ["linked_context_not_packaged_visible_reference"],
        )

    def test_round_trip_uses_generated_package_not_handwritten_preview_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            summary = build_handoff_package_round_trip_summary(
                _load_input(),
                storage_root=STORAGE_ROOT,
                package_root=package_root,
            )
            manifest = json.loads(
                (
                    package_root / "handoff-package-legacy-rabi-001" / "package-manifest.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(
            manifest["selected_measurements"][0]["primary_data"]["digest"],
            _sha256_digest(
                (STORAGE_ROOT / "records" / "legacy-rabi-001" / "primary.csv").read_bytes()
            ),
        )
        self.assertEqual(
            summary["manifest_preview"]["finding_codes"],
            ["linked_context_not_packaged_visible_reference"],
        )
        self.assertEqual(summary["manifest_preview"]["selected_measurement_count"], 1)
        self.assertEqual(summary["manifest_preview"]["linked_context_count"], 1)

    def test_round_trip_preserves_multiple_selected_measurements(self) -> None:
        source = _load_input()
        first_record = source["selected_measurements"][0]
        second_record = copy.deepcopy(first_record)
        second_content = b"drive_frequency,signal\n4.90,0.12\n4.95,0.44\n"
        second_id = "legacy-rabi-002"
        second_record["measurement_record_id"] = second_id
        second_record["legacy_data_id"] = 1002
        second_record["label"] = "Second Rabi calibration follow-up"
        second_record["primary_data"]["source_path"] = f"records/{second_id}/primary.csv"
        second_record["primary_data"]["expected_digest"] = _sha256_digest(second_content)
        second_record["primary_data"]["expected_size_bytes"] = len(second_content)
        second_record["primary_data"]["package_path"] = f"measurements/{second_id}/primary.csv"
        second_record["declared_preview_metadata"]["plot_candidates"][0]["source"] = (
            f"measurements/{second_id}/primary.csv"
        )
        second_record["default_bundle"][0]["item_id"] = f"{second_id}-primary"
        second_record["default_bundle"][0]["package_path"] = f"measurements/{second_id}/primary.csv"
        source["selected_measurements"].append(second_record)
        source["linked_context"][0]["linked_measurement_record_ids"].append(second_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            first_source = storage_root / "records" / "legacy-rabi-001" / "primary.csv"
            first_source.parent.mkdir(parents=True)
            first_source.write_bytes(
                (STORAGE_ROOT / "records" / "legacy-rabi-001" / "primary.csv").read_bytes()
            )
            second_source = storage_root / "records" / second_id / "primary.csv"
            second_source.parent.mkdir(parents=True)
            second_source.write_bytes(second_content)
            package_root = temp_root / "packages"
            package_root.mkdir()

            summary = build_handoff_package_round_trip_summary(
                source,
                storage_root=storage_root,
                package_root=package_root,
            )

        self.assertEqual(
            summary["read_view"]["measurement_ids"],
            ["legacy-rabi-001", "legacy-rabi-002"],
        )
        self.assertEqual(summary["manifest_preview"]["selected_measurement_count"], 2)
        second_summary = summary["read_view"]["measurements"][1]
        self.assertEqual(second_summary["measurement_record_id"], second_id)
        self.assertEqual(second_summary["primary_table"]["row_count"], 2)
        self.assertEqual(second_summary["preview_table"]["row_count"], 2)
        self.assertEqual(second_summary["plot_series"][0]["point_count"], 2)
        self.assertEqual(
            second_summary["finding_codes"],
            ["linked_context_not_packaged_visible_reference"],
        )

    def test_writer_rejection_stops_before_reader_path(self) -> None:
        source = _load_input()
        source["package_write_request"]["approval_state"] = "proposed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must be approved"):
                build_handoff_package_round_trip_summary(
                    source,
                    storage_root=STORAGE_ROOT,
                    package_root=Path(temp_dir),
                )


if __name__ == "__main__":
    unittest.main()

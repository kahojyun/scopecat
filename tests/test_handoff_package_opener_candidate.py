from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_opener import open_handoff_package

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "handoff_package_opener" / "basic_package"
PACKAGE = FIXTURE / "package" / "handoff-package-legacy-rabi-001"


def _copy_package(temp_dir: str) -> Path:
    destination = Path(temp_dir) / PACKAGE.name
    shutil.copytree(PACKAGE, destination)
    return destination


def _load_manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict) -> None:
    (package_dir / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class HandoffPackageOpenerCandidateTest(unittest.TestCase):
    def test_opens_expected_package_for_declared_preview_use(self) -> None:
        summary = open_handoff_package(PACKAGE)
        expected = json.loads(
            (FIXTURE / "expected-package-open-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        measurement = summary["selected_measurements"][0]
        self.assertEqual(measurement["primary_data"]["open_state"], "opened")
        self.assertEqual(measurement["preview_data"]["row_count"], 5)
        self.assertEqual(
            measurement["preview_data"]["plot_series"][0]["points"][2],
            {"x": "5.02", "y": "0.81"},
        )

    def test_open_does_not_accept_import_or_claim_package_integrity(self) -> None:
        summary = open_handoff_package(PACKAGE)
        policy = summary["package_open_policy"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(policy["storage_mutation"], "not_performed")
        self.assertEqual(policy["import_acceptance"], "not_performed")
        self.assertEqual(policy["checksum_validation"], "not_performed")
        self.assertEqual(policy["package_integrity"], "not_claimed")
        self.assertEqual(
            attention["package_integrity_not_claimed"]["does_not_claim"],
            "package_integrity_verified",
        )
        self.assertEqual(summary["linked_context"][0]["materialization"], "reference_only")

    def test_declared_digest_mismatch_does_not_block_read_only_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            manifest["selected_measurements"][0]["primary_data"]["digest"] = "sha256:" + "0" * 64
            _write_manifest(package_dir, manifest)

            summary = open_handoff_package(package_dir)

        primary = summary["selected_measurements"][0]["primary_data"]
        self.assertEqual(primary["declared_digest"], "sha256:" + "0" * 64)
        self.assertEqual(primary["observed_size_bytes"], 73)
        self.assertEqual(primary["integrity_check"], "not_performed")

    def test_declared_size_mismatch_does_not_block_read_only_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            manifest["selected_measurements"][0]["primary_data"]["size_bytes"] = 999
            _write_manifest(package_dir, manifest)

            summary = open_handoff_package(package_dir)

        primary = summary["selected_measurements"][0]["primary_data"]
        self.assertEqual(primary["declared_size_bytes"], 999)
        self.assertEqual(primary["observed_size_bytes"], 73)
        self.assertEqual(primary["integrity_check"], "not_performed")

    def test_declared_digest_and_size_are_optional_for_read_only_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            primary = manifest["selected_measurements"][0]["primary_data"]
            del primary["digest"]
            del primary["size_bytes"]
            _write_manifest(package_dir, manifest)

            summary = open_handoff_package(package_dir)

        primary = summary["selected_measurements"][0]["primary_data"]
        self.assertNotIn("declared_digest", primary)
        self.assertNotIn("declared_size_bytes", primary)
        self.assertEqual(primary["observed_size_bytes"], 73)
        self.assertEqual(primary["integrity_check"], "not_performed")

    def test_degraded_preview_metadata_is_rejected_for_declared_preview_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            preview = manifest["selected_measurements"][0]["declared_preview_metadata"]
            preview["status"] = "degraded_preview"
            preview["data_shape"] = None
            preview["declared_columns"] = []
            preview["plot_candidates"] = []
            preview["warning_code"] = "preview_metadata_missing"
            preview["message"] = "Declared preview metadata is not available."
            _write_manifest(package_dir, manifest)

            with self.assertRaisesRegex(ValueError, "requires preview_ready metadata"):
                open_handoff_package(package_dir)

    def test_degraded_preview_is_rejected_before_primary_file_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            preview = manifest["selected_measurements"][0]["declared_preview_metadata"]
            preview["status"] = "degraded_preview"
            preview["data_shape"] = None
            preview["declared_columns"] = []
            preview["plot_candidates"] = []
            preview["warning_code"] = "preview_metadata_missing"
            preview["message"] = "Declared preview metadata is not available."
            _write_manifest(package_dir, manifest)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").unlink()

            with self.assertRaisesRegex(ValueError, "requires preview_ready metadata"):
                open_handoff_package(package_dir)

    def test_empty_selected_measurements_package_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            manifest["selected_measurements"] = []
            manifest["linked_context"] = []
            _write_manifest(package_dir, manifest)

            with self.assertRaisesRegex(ValueError, "requires selected_measurements"):
                open_handoff_package(package_dir)

    def test_missing_package_primary_data_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").unlink()

            with self.assertRaisesRegex(ValueError, "primary data is unavailable"):
                open_handoff_package(package_dir)

    def test_package_root_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            symlink = package_dir.parent / "package-link"
            symlink.symlink_to(package_dir, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "package directory must not be a symlink"):
                open_handoff_package(symlink)

    def test_package_primary_data_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            primary = package_dir / "measurements" / "legacy-rabi-001" / "primary.csv"
            outside = package_dir.parent / "outside.csv"
            outside.write_text("drive_frequency,signal\n5.00,0.44\n", encoding="utf-8")
            primary.unlink()
            primary.symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "primary data must not be a symlink"):
                open_handoff_package(package_dir)

    def test_package_primary_data_symlink_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            measurement_dir = package_dir / "measurements" / "legacy-rabi-001"
            shutil.rmtree(measurement_dir)
            outside_dir = package_dir.parent / "outside-record"
            outside_dir.mkdir()
            (outside_dir / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.44\n",
                encoding="utf-8",
            )
            measurement_dir.symlink_to(outside_dir, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "primary data parent must not be a symlink"):
                open_handoff_package(package_dir)

    def test_missing_declared_preview_column_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,other\n5.00,0.44\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "missing declared preview columns"):
                open_handoff_package(package_dir)

    def test_package_member_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            manifest["selected_measurements"][0]["primary_data"]["package_path"] = "../primary.csv"
            manifest["selected_measurements"][0]["default_bundle"][0]["package_path"] = (
                "../primary.csv"
            )
            manifest["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][0][
                "source"
            ] = "../primary.csv"
            _write_manifest(package_dir, manifest)

            with self.assertRaisesRegex(ValueError, "path must be relative"):
                open_handoff_package(package_dir)

    def test_package_directory_must_match_manifest_package_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            renamed = package_dir.parent / "renamed-package"
            package_dir.rename(renamed)

            with self.assertRaisesRegex(ValueError, "directory name must match package_id"):
                open_handoff_package(renamed)

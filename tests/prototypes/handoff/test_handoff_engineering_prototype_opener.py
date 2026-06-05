from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff.opener import open_handoff_package

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "handoff"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


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


class HandoffEngineeringPrototypeOpenerTest(unittest.TestCase):
    def test_opens_package_without_import_or_integrity_claims(self) -> None:
        package = open_handoff_package(PACKAGE)

        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(package.preview_classification, "needs_review_before_acceptance")
        self.assertEqual(package.measurements[0].primary_table.row_count, 5)
        self.assertEqual(package.linked_context[0].materialization, "reference_only")

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

    def test_package_root_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            symlink = package_dir.parent / "package-link"
            symlink.symlink_to(package_dir, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "package directory must not be a symlink"):
                open_handoff_package(symlink)

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

    def test_declared_digest_mismatch_does_not_block_read_only_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            manifest["selected_measurements"][0]["primary_data"]["digest"] = "sha256:" + "0" * 64
            _write_manifest(package_dir, manifest)

            package = open_handoff_package(package_dir)

        measurement = package.measurements[0]
        self.assertEqual(measurement.declared_digest, "sha256:" + "0" * 64)
        self.assertEqual(measurement.primary_table.row_count, 5)

    def test_csv_table_checks_reject_duplicate_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal,signal\n5.00,0.44,0.45\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "requires unique CSV headers"):
                open_handoff_package(package_dir)


if __name__ == "__main__":
    unittest.main()

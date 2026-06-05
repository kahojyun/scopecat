from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from scopecat.handoff import (
    HandoffArchiveCreationRequest,
    HandoffArchiveMaterializationRequest,
    create_handoff_archive_package_from_request,
    materialize_handoff_archive_package_from_request,
    open_package,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_FIXTURE = (
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


def _request(**overrides: object) -> HandoffArchiveMaterializationRequest:
    values = {
        "request_id": "materialize-archive-001",
        "approval_state": "approved",
        "archive_path": "handoff-package-legacy-rabi-001.zip",
        "package_dir": "handoff-package-legacy-rabi-001",
    }
    values.update(overrides)
    return HandoffArchiveMaterializationRequest(**values)


def _creation_request(**overrides: object) -> HandoffArchiveCreationRequest:
    values = {
        "request_id": "create-archive-001",
        "approval_state": "approved",
        "package_dir": "handoff-package-legacy-rabi-001",
        "archive_path": "handoff-package-legacy-rabi-001.zip",
    }
    values.update(overrides)
    return HandoffArchiveCreationRequest(**values)


def _write_package_zip(archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in sorted(PACKAGE_FIXTURE.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    arcname=f"{PACKAGE_FIXTURE.name}/{path.relative_to(PACKAGE_FIXTURE)}",
                )


def _write_zip(archive_path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


class HandoffArchiveMaterializationTest(unittest.TestCase):
    def test_creates_zip_transport_archive_and_round_trips_to_materialized_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            package_root.mkdir()
            archive_root.mkdir()
            materialization_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )
            materialized = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )
            package = open_package(materialization_root / "handoff-package-legacy-rabi-001")

        creation_payload = creation.to_dict()
        self.assertTrue(creation.created)
        self.assertTrue(materialized.materialized)
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        self.assertIn(
            "handoff-package-legacy-rabi-001/package-manifest.json",
            creation_payload["archive"]["archived_files"],
        )
        self.assertEqual(creation_payload["creation_review"]["block_reason"], None)

    def test_archive_creation_blocks_existing_archive_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            package_root.mkdir()
            archive_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)
            (archive_root / "handoff-package-legacy-rabi-001.zip").write_text(
                "existing",
                encoding="utf-8",
            )

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )

        self.assertFalse(creation.created)
        self.assertEqual(
            creation.to_dict()["creation_review"]["block_reason"],
            "archive_destination_collision",
        )

    def test_archive_creation_blocks_symlink_archive_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            package_root.mkdir()
            archive_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)
            (archive_root / "existing.zip").write_text("existing", encoding="utf-8")
            (archive_root / "handoff-package-legacy-rabi-001.zip").symlink_to(
                "existing.zip",
            )

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )

        self.assertFalse(creation.created)
        self.assertEqual(
            creation.to_dict()["creation_review"]["block_reason"],
            "archive_destination_collision",
        )

    def test_archive_creation_blocks_symlink_package_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            package_root.mkdir()
            archive_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)
            (
                package_root
                / PACKAGE_FIXTURE.name
                / "measurements"
                / "legacy-rabi-001"
                / "linked-primary.csv"
            ).symlink_to("primary.csv")

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )

        self.assertFalse(creation.created)
        self.assertEqual(
            creation.to_dict()["creation_review"]["block_reason"],
            "archive_creation_symlink_blocked",
        )

    def test_materializes_zip_transport_into_openable_directory_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_package_zip(archive_root / "handoff-package-legacy-rabi-001.zip")

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )
            package = open_package(materialization_root / "handoff-package-legacy-rabi-001")

        payload = run.to_dict()
        self.assertTrue(run.materialized)
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        self.assertIn(
            "handoff-package-legacy-rabi-001/package-manifest.json",
            payload["materialization"]["materialized_files"],
        )
        self.assertEqual(payload["materialization_review"]["block_reason"], None)

    def test_materialization_blocks_parent_traversal_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_zip(
                archive_root / "handoff-package-legacy-rabi-001.zip",
                {
                    "../outside.txt": "outside",
                    "handoff-package-legacy-rabi-001/package-manifest.json": "{}",
                },
            )

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

        payload = run.to_dict()
        self.assertFalse(run.materialized)
        self.assertIn(
            "parent_traversal_archive_member_path",
            payload["materialization"]["materialization_error"],
        )
        self.assertFalse((materialization_root / "handoff-package-legacy-rabi-001").exists())

    def test_materialization_blocks_symlink_member_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            archive_path = archive_root / "handoff-package-legacy-rabi-001.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                info = zipfile.ZipInfo("handoff-package-legacy-rabi-001/link")
                info.external_attr = 0o120777 << 16
                archive.writestr(info, "package-manifest.json")
                archive.writestr("handoff-package-legacy-rabi-001/package-manifest.json", "{}")

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

        self.assertFalse(run.materialized)
        self.assertIn(
            "symlink_archive_member_not_allowed",
            run.to_dict()["materialization"]["materialization_error"],
        )

    def test_materialization_blocks_existing_package_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_package_zip(archive_root / "handoff-package-legacy-rabi-001.zip")
            shutil.copytree(
                PACKAGE_FIXTURE,
                materialization_root / "handoff-package-legacy-rabi-001",
            )

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

        self.assertFalse(run.materialized)
        self.assertIn("target already exists", run.materialization_error or "")

    def test_materialization_cleans_partial_package_when_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_zip(
                archive_root / "handoff-package-legacy-rabi-001.zip",
                {"handoff-package-legacy-rabi-001/package-manifest.json": "{}"},
            )

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

            self.assertFalse((materialization_root / "handoff-package-legacy-rabi-001").exists())

        self.assertFalse(run.materialized)
        self.assertTrue(run.cleanup_performed)
        self.assertIn("package_identity", run.materialization_error or "")


if __name__ == "__main__":
    unittest.main()

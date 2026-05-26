from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from implementation_candidates.filesystem_mutation import filesystem


class FilesystemMutationCandidateTest(unittest.TestCase):
    def test_writes_new_files_transaction_and_returns_written_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            written_paths, created_dirs = filesystem.write_new_files_transaction(
                root,
                [
                    ("records/measurement-001/primary.csv", b"x,y\n1,2\n"),
                    ("records/measurement-001/record-manifest.json", b"{}\n"),
                ],
                label="storage target",
            )

            self.assertEqual(
                written_paths,
                [
                    "records/measurement-001/primary.csv",
                    "records/measurement-001/record-manifest.json",
                ],
            )
            self.assertIn("records", created_dirs)
            self.assertEqual(
                (root / "records" / "measurement-001" / "primary.csv").read_bytes(),
                b"x,y\n1,2\n",
            )

    def test_rejects_existing_targets_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "records" / "measurement-001" / "primary.csv"
            target.parent.mkdir(parents=True)
            target.write_text("sentinel\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "target already exists"):
                filesystem.write_new_files_transaction(
                    root,
                    [("records/measurement-001/primary.csv", b"new\n")],
                    label="storage target",
                )

            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel\n")

    def test_existing_later_target_prevents_earlier_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "records" / "measurement-001" / "record-manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("sentinel\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "target already exists"):
                filesystem.write_new_files_transaction(
                    root,
                    [
                        ("records/measurement-001/primary.csv", b"x,y\n"),
                        ("records/measurement-001/record-manifest.json", b"{}\n"),
                    ],
                    label="storage target",
                )

            self.assertFalse((root / "records" / "measurement-001" / "primary.csv").exists())
            self.assertEqual(manifest.read_text(encoding="utf-8"), "sentinel\n")

    def test_rejects_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "root"
            outside = Path(temp_dir) / "outside"
            root.mkdir()
            outside.mkdir()
            os.symlink(outside, root / "records")

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                filesystem.write_new_files_transaction(
                    root,
                    [("records/measurement-001/primary.csv", b"x,y\n")],
                    label="storage target",
                )

            self.assertFalse((outside / "measurement-001").exists())

    def test_transaction_rolls_back_earlier_file_on_later_write_failure(self) -> None:
        real_write_new_file = filesystem.write_new_file

        def write_then_fail(root: Path, relative_path: str, content: bytes, *, label: str):
            if relative_path.endswith("record-manifest.json"):
                raise OSError("simulated later write failure")
            return real_write_new_file(root, relative_path, content, label=label)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with mock.patch.object(filesystem, "write_new_file", side_effect=write_then_fail):
                with self.assertRaisesRegex(OSError, "simulated later write failure"):
                    filesystem.write_new_files_transaction(
                        root,
                        [
                            ("records/measurement-001/primary.csv", b"x,y\n"),
                            ("records/measurement-001/record-manifest.json", b"{}\n"),
                        ],
                        label="storage target",
                    )

            self.assertFalse((root / "records").exists())

    def test_transaction_rollback_preserves_preexisting_parent_directory(self) -> None:
        real_write_new_file = filesystem.write_new_file

        def write_then_fail(root: Path, relative_path: str, content: bytes, *, label: str):
            if relative_path.endswith("record-manifest.json"):
                raise OSError("simulated later write failure")
            return real_write_new_file(root, relative_path, content, label=label)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records_dir = root / "records"
            records_dir.mkdir()

            with mock.patch.object(filesystem, "write_new_file", side_effect=write_then_fail):
                with self.assertRaisesRegex(OSError, "simulated later write failure"):
                    filesystem.write_new_files_transaction(
                        root,
                        [
                            ("records/measurement-001/primary.csv", b"x,y\n"),
                            ("records/measurement-001/record-manifest.json", b"{}\n"),
                        ],
                        label="storage target",
                    )

            self.assertTrue(records_dir.is_dir())
            self.assertFalse((records_dir / "measurement-001").exists())

    def test_write_new_file_removes_partial_file_on_write_failure(self) -> None:
        class FailingFile:
            def __init__(self, handle):
                self._handle = handle

            def __enter__(self):
                self._handle.__enter__()
                return self

            def __exit__(self, exc_type, exc, traceback):
                return self._handle.__exit__(exc_type, exc, traceback)

            def write(self, content: bytes) -> None:
                self._handle.write(content[:4])
                raise OSError("simulated partial write failure")

        real_fdopen = filesystem.os.fdopen

        def failing_fdopen(*args, **kwargs):
            return FailingFile(real_fdopen(*args, **kwargs))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with mock.patch.object(filesystem.os, "fdopen", failing_fdopen):
                with self.assertRaisesRegex(OSError, "simulated partial write failure"):
                    filesystem.write_new_file(
                        root,
                        "records/measurement-001/primary.csv",
                        b"partial content",
                        label="storage target",
                    )

            self.assertFalse((root / "records").exists())


if __name__ == "__main__":
    unittest.main()

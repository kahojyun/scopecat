"""Shared low-level filesystem mutation helpers for implementation candidates."""

from .filesystem import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
    reject_existing_paths,
    rollback_written_files,
    target_exists,
    write_new_file,
    write_new_files_transaction,
)

__all__ = [
    "existing_directory_root",
    "ensure_no_symlink_parents",
    "path_under",
    "reject_existing_paths",
    "rollback_written_files",
    "target_exists",
    "write_new_file",
    "write_new_files_transaction",
]

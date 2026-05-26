"""Low-level no-overwrite filesystem mutation helpers.

These helpers are intentionally below the domain layer. They validate and
write relative paths under caller-provided roots without defining storage,
package, import, or measurement-record semantics.
"""

from __future__ import annotations

import os
from pathlib import Path

from implementation_candidates.contract_primitives import relative_path_parts

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def path_under(root: Path, relative_path: str) -> Path:
    """Return a path under root after syntax validation of the relative path."""

    return root.joinpath(*relative_path_parts(relative_path))


def existing_directory_root(root: Path, label: str) -> Path:
    """Return a resolved existing directory root, rejecting symlink roots."""

    if root.is_symlink():
        raise ValueError(f"{label} root must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"{label} root must be an existing directory")
    return root.resolve()


def target_exists(root: Path, relative_path: str) -> bool:
    """Return true for existing files, directories, or symlinks."""

    return os.path.lexists(path_under(root, relative_path))


def ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    """Reject symlink or non-directory parents for a relative target path."""

    current = root
    for part in relative_path_parts(relative_path, label)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{label} parent is not a directory")


def reject_existing_paths(root: Path, relative_paths: list[str], label: str) -> None:
    """Reject any existing path and symlink parents before writing."""

    for relative_path in relative_paths:
        if target_exists(root, relative_path):
            raise ValueError(f"{label} target already exists")
        ensure_no_symlink_parents(root, relative_path, label)


def _open_dir_fd(path: Path | str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW
    if dir_fd is None:
        return os.open(path, flags)
    return os.open(path, flags, dir_fd=dir_fd)


def _remove_created_dirs(root: Path, created_dirs: list[str]) -> None:
    for relative_path in reversed(created_dirs):
        try:
            path_under(root, relative_path).rmdir()
        except OSError:
            pass


def _open_parent_dir_fd(root: Path, relative_path: str, *, create: bool) -> tuple[int, list[str]]:
    root_fd = _open_dir_fd(root)
    current_fd = root_fd
    current_parts: list[str] = []
    created_dirs: list[str] = []
    try:
        for part in relative_path_parts(relative_path)[:-1]:
            current_parts.append(part)
            if create:
                try:
                    os.mkdir(part, dir_fd=current_fd)
                    created_dirs.append("/".join(current_parts))
                except FileExistsError:
                    pass
            next_fd = _open_dir_fd(part, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        if current_fd == root_fd:
            return root_fd, created_dirs
        os.close(root_fd)
        return current_fd, created_dirs
    except Exception:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)
        if create:
            _remove_created_dirs(root, created_dirs)
        raise


def write_new_file(root: Path, relative_path: str, content: bytes, *, label: str) -> list[str]:
    """Write one new file with no-overwrite and partial-write cleanup."""

    ensure_no_symlink_parents(root, relative_path, label)
    parent_fd: int | None = None
    created_dirs: list[str] = []
    created_file = False
    try:
        parent_fd, created_dirs = _open_parent_dir_fd(root, relative_path, create=True)
        file_fd = os.open(
            relative_path_parts(relative_path)[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            0o666,
            dir_fd=parent_fd,
        )
        created_file = True
        with os.fdopen(file_fd, "wb") as handle:
            handle.write(content)
    except Exception:
        if created_file:
            try:
                path_under(root, relative_path).unlink()
            except FileNotFoundError:
                pass
        _remove_created_dirs(root, created_dirs)
        raise
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    return created_dirs


def rollback_written_files(root: Path, written_paths: list[str], created_dirs: list[str]) -> None:
    """Best-effort rollback for files and directories created by write_new_file."""

    for relative_path in reversed(written_paths):
        try:
            path_under(root, relative_path).unlink()
        except FileNotFoundError:
            pass
    _remove_created_dirs(root, created_dirs)


def write_new_files_transaction(
    root: Path,
    files: list[tuple[str, bytes]],
    *,
    label: str,
) -> tuple[list[str], list[str]]:
    """Write a sequence of new files, rolling back if any write fails."""

    reject_existing_paths(root, [relative_path for relative_path, _content in files], label)
    written_paths: list[str] = []
    created_dirs: list[str] = []
    try:
        for relative_path, content in files:
            created_dirs.extend(write_new_file(root, relative_path, content, label=label))
            written_paths.append(relative_path)
    except Exception:
        rollback_written_files(root, written_paths, created_dirs)
        raise
    return written_paths, created_dirs

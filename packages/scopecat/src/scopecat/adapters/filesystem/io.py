"""Internal local storage I/O helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel


def read_model[TModel: BaseModel](path: Path, model_type: type[TModel]) -> TModel:
    return model_type.model_validate_json(path.read_text())


def encode_model_json(model: BaseModel, *, indent: int | None = None) -> str:
    """Encode the durable extended-JSON wire, preserving IEEE non-finite values.

    The wire intentionally uses the constants ``NaN``, ``Infinity``, and
    ``-Infinity``. Pydantic's JSON parser restores those constants as floats.
    """

    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=True,
        indent=indent,
        separators=(",", ":") if indent is None else None,
    )


def ensure_durable_directory(path: Path) -> None:
    """Create a directory tree and durably publish every new directory link."""

    if path.is_dir():
        return
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    if not current.is_dir():
        raise NotADirectoryError(current)
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            if not directory.is_dir():
                raise
        fsync_directory(directory)
        fsync_directory(directory.parent)


def write_model(path: Path, model: BaseModel) -> None:
    _write_atomic(
        path,
        lambda temporary_path: _write_model_contents(temporary_path, model),
    )


def write_model_if_absent(path: Path, model: BaseModel) -> bool:
    """Atomically publish a complete model without replacing existing content."""

    ensure_durable_directory(path.parent)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        _write_model_contents(temporary_path, model)
        _fsync_file(temporary_path)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary_path.unlink(missing_ok=True)
        fsync_directory(path.parent)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as persisted_file:
        os.fsync(persisted_file.fileno())


def fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def read_jsonl[TModel: BaseModel](path: Path, model_type: type[TModel]) -> list[TModel]:
    return [
        model_type.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    _write_atomic(
        path,
        lambda temporary_path: _write_jsonl_contents(temporary_path, records),
    )


def read_text(path: Path) -> str:
    return path.read_text()


def write_text(path: Path, content: str) -> None:
    if content and not content.endswith("\n"):
        content = f"{content}\n"
    _write_atomic(path, lambda temporary_path: temporary_path.write_text(content))


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """Durably replace one file with exact byte content."""

    _write_atomic(path, lambda temporary_path: temporary_path.write_bytes(content))


def _write_atomic(path: Path, write_temporary: Callable[[Path], object]) -> None:
    """Durably replace ``path`` with content staged beside the target."""

    ensure_durable_directory(path.parent)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        write_temporary(temporary_path)
        _fsync_file(temporary_path)
        temporary_path.replace(path)
        fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_model_contents(path: Path, model: BaseModel) -> None:
    path.write_text(encode_model_json(model, indent=2) + "\n")


def _write_jsonl_contents(path: Path, records: Iterable[BaseModel]) -> None:
    with path.open("w") as data_file:
        for record in records:
            data_file.write(encode_model_json(record) + "\n")

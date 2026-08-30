"""Append-only durable packs for segment-owned measurement payloads."""

from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import cast

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_FRAME_MAGIC = b"SCMPACK1"
_FRAME_HEADER = struct.Struct("<8sQ32s")


class MeasurementPackError(OSError):
    """Base measurement-pack I/O failure."""


class MeasurementPackNotFoundError(MeasurementPackError):
    """An indexed measurement pack is absent."""


class MeasurementPackCorruptError(MeasurementPackError):
    """An indexed measurement frame is incomplete or corrupt."""


@dataclass(frozen=True, slots=True)
class PackedMeasurementPayload:
    """Exact frame coordinates published by the relational index."""

    pack_id: str
    offset: int
    length: int
    digest: str

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.pack_id) is None:
            raise ValueError("measurement pack id must be a SHA-256 digest")
        if _DIGEST.fullmatch(self.digest) is None:
            raise ValueError("measurement payload digest must be SHA-256")
        if self.offset < 0 or self.length < 1:
            raise ValueError("measurement pack coordinates must be non-negative")

    @property
    def end_offset(self) -> int:
        """Return the first byte after this framed payload."""

        return self.offset + _FRAME_HEADER.size + self.length


class MeasurementPackStore:
    """Append frames to one physical file per execution segment.

    Payload bytes and their frame header are flushed before callers publish the
    returned coordinates in SQLite. A crash before that metadata transaction
    can leave an unreferenced tail, which readers never scan or expose.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._append_lock = Lock()

    def bootstrap(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, pack_id: str, content: bytes) -> PackedMeasurementPayload:
        path = self.path_for(pack_id)
        digest_bytes = hashlib.sha256(content).digest()
        digest = f"sha256:{digest_bytes.hex()}"
        frame = _FRAME_HEADER.pack(_FRAME_MAGIC, len(content), digest_bytes)
        try:
            with self._append_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                created = not path.exists()
                with path.open("ab") as output:
                    offset = output.tell()
                    output.write(frame)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                if created:
                    _fsync_directory(path.parent)
        except OSError as error:
            raise MeasurementPackError(path) from error
        return PackedMeasurementPayload(
            pack_id=pack_id,
            offset=offset,
            length=len(content),
            digest=digest,
        )

    def read(self, payload: PackedMeasurementPayload) -> bytes:
        path = self.path_for(payload.pack_id)
        try:
            with path.open("rb") as source:
                source.seek(payload.offset)
                header = source.read(_FRAME_HEADER.size)
                if len(header) != _FRAME_HEADER.size:
                    raise MeasurementPackCorruptError(path)
                magic, length, digest_bytes = cast(
                    "tuple[bytes, int, bytes]",
                    _FRAME_HEADER.unpack(header),
                )
                if (
                    magic != _FRAME_MAGIC
                    or length != payload.length
                    or f"sha256:{digest_bytes.hex()}" != payload.digest
                ):
                    raise MeasurementPackCorruptError(path)
                content = source.read(length)
        except FileNotFoundError as error:
            raise MeasurementPackNotFoundError(path) from error
        except MeasurementPackCorruptError:
            raise
        except OSError as error:
            raise MeasurementPackError(path) from error
        if len(content) != payload.length or (
            f"sha256:{hashlib.sha256(content).hexdigest()}" != payload.digest
        ):
            raise MeasurementPackCorruptError(path)
        return content

    def trim_unindexed_tail(self, pack_id: str, *, indexed_end: int) -> int:
        """Discard bytes after the last SQLite-published frame boundary."""

        if indexed_end < 0:
            raise ValueError("indexed measurement pack end cannot be negative")
        path = self.path_for(pack_id)
        try:
            with self._append_lock:
                try:
                    size = path.stat().st_size
                except FileNotFoundError:
                    if indexed_end:
                        raise MeasurementPackNotFoundError(path) from None
                    return 0
                if size < indexed_end:
                    raise MeasurementPackCorruptError(path)
                reclaimed = size - indexed_end
                if not reclaimed:
                    return 0
                if indexed_end == 0:
                    path.unlink()
                    _fsync_directory(path.parent)
                    return reclaimed
                with path.open("r+b") as output:
                    output.truncate(indexed_end)
                    output.flush()
                    os.fsync(output.fileno())
                return reclaimed
        except MeasurementPackError:
            raise
        except OSError as error:
            raise MeasurementPackError(path) from error

    def path_for(self, pack_id: str) -> Path:
        match = _DIGEST.fullmatch(pack_id)
        if match is None:
            raise MeasurementPackCorruptError(f"invalid measurement pack id: {pack_id}")
        hexdigest = match.group(1)
        return self.root / hexdigest[:2] / f"{hexdigest[2:]}.pack"


def measurement_segment_pack_id(*, run_id: str, segment_id: str) -> str:
    """Return a filesystem-safe identity without constraining logical ids."""

    digest = hashlib.sha256()
    digest.update(b"scopecat.measurement_segment_pack.v1\0")
    digest.update(run_id.encode())
    digest.update(b"\0")
    digest.update(segment_id.encode())
    return f"sha256:{digest.hexdigest()}"


def measurement_pack_root(objects_root: str | Path) -> Path:
    return Path(objects_root).parent / "measurement-packs"


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "MeasurementPackCorruptError",
    "MeasurementPackError",
    "MeasurementPackNotFoundError",
    "MeasurementPackStore",
    "PackedMeasurementPayload",
    "measurement_pack_root",
    "measurement_segment_pack_id",
]

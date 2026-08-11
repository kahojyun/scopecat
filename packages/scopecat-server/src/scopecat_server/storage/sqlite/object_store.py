"""Immutable content-addressed objects used by the SQLite run index."""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


class ObjectStoreError(OSError):
    """Base object-store I/O failure."""


class ObjectNotFoundError(ObjectStoreError):
    """An indexed object is absent."""


class ObjectCorruptError(ObjectStoreError):
    """An object's bytes do not match its digest."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    digest: str


class ImmutableObjectStore:
    """SHA-256 objects published once and never changed in place."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def bootstrap(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes) -> StoredObject:
        hexdigest = hashlib.sha256(content).hexdigest()
        digest = f"sha256:{hexdigest}"
        path = self.root / hexdigest[:2] / hexdigest[2:]
        if path.is_file():
            return StoredObject(digest=digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{hexdigest}.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            with suppress(FileExistsError):
                os.link(temporary, path)
            _fsync_directory(path.parent)
        except OSError as error:
            raise ObjectStoreError(path) from error
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        return StoredObject(digest=digest)

    def read(self, digest: str) -> bytes:
        path = self.path_for(digest)
        try:
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise ObjectNotFoundError(path) from error
        except OSError as error:
            raise ObjectStoreError(path) from error
        if f"sha256:{hashlib.sha256(content).hexdigest()}" != digest:
            raise ObjectCorruptError(path)
        return content

    def path_for(self, digest: str) -> Path:
        match = _DIGEST.fullmatch(digest)
        if match is None:
            raise ObjectCorruptError(f"invalid object digest: {digest}")
        hexdigest = match.group(1)
        return self.root / hexdigest[:2] / hexdigest[2:]


def _fsync_directory(path: Path) -> None:
    # Windows does not allow directories to be opened through ``os.open``.
    # The object itself is flushed above; directory fsync is an additional
    # POSIX durability barrier for publishing the hard link.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import override

import pytest

from scopecat_server.storage.sqlite.object_store import (
    ImmutableObjectStore,
    ObjectCorruptError,
    ObjectNotFoundError,
)


class CountingStore(ImmutableObjectStore):
    def __init__(self, root: Path, *, budget: int = 8) -> None:
        super().__init__(root, read_cache_bytes=budget)
        self.reads: list[str] = []

    @override
    def read(self, digest: str) -> bytes:
        self.reads.append(digest)
        return super().read(digest)


def test_verified_reuse_lru_and_oversized_bypass(tmp_path: Path) -> None:
    store = CountingStore(tmp_path)
    a, b, c, large = [
        store.put(value).digest for value in (b"aaaa", b"bbbb", b"cccc", b"012345678")
    ]
    assert store.read_cached(a) == b"aaaa"
    store.read_cached(b)
    store.read_cached(a)
    store.read_cached(c)  # b is least recently used.
    store.read_cached(a)
    store.read_cached(b)
    assert store.reads == [a, b, c, b]
    store.read_cached(large)
    store.read_cached(large)
    assert store.reads[-2:] == [large, large]
    store.read_cached(a)  # Oversized reads do not evict retained entries.
    assert store.reads[-1] == large


def test_changed_or_deleted_objects_do_not_reuse_verified_old_bytes(
    tmp_path: Path,
) -> None:
    store = CountingStore(tmp_path)
    digest = store.put(b"verified").digest
    store.read_cached(digest)
    path = store.path_for(digest)
    before = path.stat()
    path.write_bytes(b"tampered")  # Same length: timestamp validation is required.
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    with pytest.raises(ObjectCorruptError):
        store.read_cached(digest)
    store.path_for(digest).write_bytes(b"verified")
    assert store.read_cached(digest) == b"verified"
    store.path_for(digest).unlink()
    with pytest.raises(ObjectNotFoundError):
        store.read_cached(digest)


def test_concurrent_pages_share_one_verified_read(tmp_path: Path) -> None:
    store = CountingStore(tmp_path)
    digest = store.put(b"verified").digest
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert (
            list(executor.map(store.read_cached, [digest] * 32)) == [b"verified"] * 32
        )
    assert store.reads == [digest]


def test_zero_budget_and_entry_limit(tmp_path: Path) -> None:
    disabled = CountingStore(tmp_path, budget=0)
    digest = disabled.put(b"x").digest
    disabled.read_cached(digest)
    disabled.read_cached(digest)
    assert disabled.reads == [digest, digest]
    store = CountingStore(tmp_path, budget=1024)
    digests = [store.put(bytes([i])).digest for i in range(33)]
    for key in digests:
        store.read_cached(key)
    store.read_cached(digests[0])
    assert len(store.reads) == 34

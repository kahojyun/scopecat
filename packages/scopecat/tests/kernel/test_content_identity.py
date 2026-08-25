from __future__ import annotations

import hashlib

import numpy as np

from scopecat.kernel.content_identity import (
    canonical_json,
    content_fingerprint,
    stable_content_hash,
)


class _NoToBytesArray(np.ndarray):
    def tobytes(  # pyright: ignore[reportImplicitOverride]
        self, *args: object, **kwargs: object
    ) -> bytes:
        del args, kwargs
        raise AssertionError("contiguous arrays should be hashed through their buffer")


def test_stable_content_hash_matches_canonical_json_bytes() -> None:
    value = {
        "unicode": "并行波形",
        "nested": [{"value": index, "enabled": index % 2 == 0} for index in range(100)],
    }

    assert (
        stable_content_hash(value)
        == hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    )


def test_contiguous_array_fingerprint_hashes_the_existing_buffer() -> None:
    value = np.arange(128, dtype=np.float64).view(_NoToBytesArray)

    fingerprint = content_fingerprint(value)

    assert isinstance(fingerprint, dict)
    assert fingerprint["sha256"] == hashlib.sha256(memoryview(value)).hexdigest()


def test_noncontiguous_array_fingerprint_retains_c_order_identity() -> None:
    value = np.arange(24, dtype=np.int64).reshape(4, 6)[:, ::2]

    fingerprint = content_fingerprint(value)

    assert isinstance(fingerprint, dict)
    assert fingerprint["sha256"] == hashlib.sha256(value.tobytes()).hexdigest()

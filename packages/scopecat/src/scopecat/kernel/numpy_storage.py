"""Ownership helpers for immutable NumPy-backed domain values."""

from __future__ import annotations

from typing import cast

import numpy as np
from numpy.typing import NDArray


def freeze_ndarray(value: NDArray[np.generic]) -> NDArray[np.generic]:
    """Return a C-contiguous array backed by immutable bytes.

    Existing views over immutable ``bytes`` storage are reused. Other arrays are
    copied directly into their final byte owner without first making a redundant
    writable C-order copy.
    """

    if value.flags.c_contiguous and _has_immutable_bytes_owner(value):
        return value
    content = value.tobytes(order="C")
    return np.frombuffer(content, dtype=value.dtype).reshape(value.shape)


def _has_immutable_bytes_owner(value: NDArray[np.generic]) -> bool:
    owner: object = value
    while True:
        if isinstance(owner, np.ndarray):
            owner = cast("object", owner.base)
            continue
        if isinstance(owner, memoryview):
            if not owner.readonly:
                return False
            owner = cast("object", owner.obj)
            continue
        return isinstance(owner, bytes)


__all__ = ["freeze_ndarray"]

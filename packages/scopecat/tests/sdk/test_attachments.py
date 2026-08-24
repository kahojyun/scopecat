from __future__ import annotations

from hashlib import sha256

import pytest

from scopecat.sdk.attachments import (
    AttachmentBundle,
    AttachmentBundleError,
    AttachmentBundleLimits,
)


def test_attachment_bundle_round_trips_ordered_immutable_parts() -> None:
    mutable = bytearray(b"second")
    bundle = AttachmentBundle(
        header=b'{"format":"test.v1"}',
        attachments=(memoryview(b"first"), memoryview(mutable)),
    )
    mutable[:] = b"mutated"

    content = bundle.to_bytes()
    restored = AttachmentBundle.from_bytes(content)

    assert restored.header == bundle.header
    assert tuple(map(bytes, restored.attachments)) == (b"first", b"second")
    assert all(
        isinstance(attachment, bytes) or attachment.readonly
        for attachment in restored.attachments
    )
    assert restored.to_bytes() == content
    assert restored.content_hash() == f"sha256:{sha256(content).hexdigest()}"


def test_attachment_bundle_rejects_truncation_trailing_bytes_and_limits() -> None:
    content = AttachmentBundle(header=b"{}", attachments=(b"payload",)).to_bytes()

    with pytest.raises(AttachmentBundleError, match="truncated"):
        AttachmentBundle.from_bytes(content[:-1])
    with pytest.raises(AttachmentBundleError, match="trailing"):
        AttachmentBundle.from_bytes(content + b"extra")
    with pytest.raises(AttachmentBundleError, match="attachment exceeds"):
        AttachmentBundle.from_bytes(
            content,
            AttachmentBundleLimits(max_attachment_bytes=1),
        )

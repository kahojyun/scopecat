"""Cross-cutting storage and materialization for opaque command payload bytes."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterable, Iterable, Mapping
from dataclasses import dataclass
from tempfile import TemporaryFile
from threading import RLock
from typing import BinaryIO, Literal

from scopecat.daemon.wire import (
    PayloadObjectReceipt,
    RunHardwareBatchCommand,
)
from scopecat.kernel.content_identity import sha256_content_hash
from scopecat.records.content import (
    BlobPayloadBody,
    CommandPayload,
)
from scopecat.sdk.attachments import AttachmentBundleError
from scopecat.sdk.instruments.backend import BackendPayload
from scopecat.sdk.instruments.commands import InvokeCommand
from scopecat.sdk.instruments.execution import RunHardwareInvoke
from scopecat.sdk.payloads import EncodedPayloadContent

DEFAULT_MAX_PAYLOAD_OBJECT_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_INLINE_PAYLOAD_BYTES = 1024 * 1024

type CommandPayloadScope = tuple[Literal["run", "session"], str, str]


@dataclass(slots=True)
class _StoredPayloadObject:
    size_bytes: int
    content: bytes | BinaryIO

    def read(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        self.content.seek(0)
        return self.content.read()

    def close(self) -> None:
        if not isinstance(self.content, bytes):
            self.content.close()


def run_payload_scope(run_id: str, operation_id: str) -> CommandPayloadScope:
    return ("run", run_id, operation_id)


def session_payload_scope(session_id: str, command_id: str) -> CommandPayloadScope:
    return ("session", session_id, command_id)


class CommandPayloadError(ValueError):
    """A payload object cannot be accepted or materialized."""


class CommandPayloadTooLarge(CommandPayloadError):
    """A payload exceeds the executable daemon boundary."""


class CommandPayloadService:
    """Spool opaque command bytes only for the operation that consumes them."""

    def __init__(
        self,
        *,
        max_object_bytes: int = DEFAULT_MAX_PAYLOAD_OBJECT_BYTES,
        max_inline_bytes: int = DEFAULT_MAX_INLINE_PAYLOAD_BYTES,
    ) -> None:
        if max_object_bytes < 1 or max_inline_bytes < 1:
            raise ValueError("payload byte limits must be positive")
        if max_inline_bytes > max_object_bytes:
            raise ValueError("inline payload limit cannot exceed object limit")
        self._max_object_bytes = max_object_bytes
        self._max_inline_bytes = max_inline_bytes
        self._lock = RLock()
        self._objects_by_scope: dict[
            CommandPayloadScope,
            dict[str, _StoredPayloadObject],
        ] = {}
        self._peak_spooled_size_bytes = 0

    def put_object(
        self,
        content: bytes,
        *,
        scope: CommandPayloadScope,
        expected_content_hash: str,
    ) -> PayloadObjectReceipt:
        self._require_size(
            len(content),
            limit=self._max_object_bytes,
            boundary="payload object upload",
        )
        actual_hash = sha256_content_hash(content)
        if actual_hash != expected_content_hash:
            raise CommandPayloadError(
                "payload object content hash mismatch: "
                f"expected {expected_content_hash}, got {actual_hash}"
            )
        self._store_object(
            scope,
            actual_hash,
            _StoredPayloadObject(size_bytes=len(content), content=content),
        )
        return PayloadObjectReceipt(
            ref=actual_hash,
            content_hash=actual_hash,
            size_bytes=len(content),
        )

    async def put_object_stream(
        self,
        chunks: AsyncIterable[bytes],
        *,
        scope: CommandPayloadScope,
        expected_content_hash: str,
        declared_size_bytes: int | None = None,
    ) -> PayloadObjectReceipt:
        """Read an untrusted upload incrementally under the hard object limit."""

        if declared_size_bytes is not None:
            self._require_size(
                declared_size_bytes,
                limit=self._max_object_bytes,
                boundary="payload object upload",
            )
        # Ownership transfers to the scoped object store after verification.
        spool = TemporaryFile(mode="w+b")  # noqa: SIM115
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            async for chunk in chunks:
                size_bytes += len(chunk)
                self._require_size(
                    size_bytes,
                    limit=self._max_object_bytes,
                    boundary="payload object upload",
                )
                digest.update(chunk)
                spool.write(chunk)
            actual_hash = f"sha256:{digest.hexdigest()}"
            if actual_hash != expected_content_hash:
                raise CommandPayloadError(
                    "payload object content hash mismatch: "
                    f"expected {expected_content_hash}, got {actual_hash}"
                )
            spool.seek(0)
            self._store_object(
                scope,
                actual_hash,
                _StoredPayloadObject(size_bytes=size_bytes, content=spool),
            )
        except BaseException:
            spool.close()
            raise
        return PayloadObjectReceipt(
            ref=actual_hash,
            content_hash=actual_hash,
            size_bytes=size_bytes,
        )

    def canonicalize_invoke_command(
        self,
        command: InvokeCommand,
        *,
        scope: CommandPayloadScope,
    ) -> InvokeCommand:
        """Spool inline bodies and return the canonical blob descriptor."""

        return command.model_copy(
            update={
                "payloads": self._canonicalize_payloads(
                    command.payloads,
                    scope=scope,
                    refs_by_hash={},
                )
            }
        )

    def canonicalize_hardware_command(
        self,
        command: RunHardwareBatchCommand,
        *,
        scope: CommandPayloadScope,
    ) -> RunHardwareBatchCommand:
        """Canonicalize every invoke payload before idempotency comparison."""

        refs_by_hash: dict[str, str] = {}
        actions = tuple(
            action.model_copy(
                update={
                    "payloads": self._canonicalize_payloads(
                        action.payloads,
                        scope=scope,
                        refs_by_hash=refs_by_hash,
                    )
                }
            )
            if isinstance(action, RunHardwareInvoke)
            else action
            for action in command.batch.actions
        )
        return command.model_copy(
            update={"batch": command.batch.model_copy(update={"actions": actions})}
        )

    def materialize_payloads(
        self,
        payloads: Mapping[str, CommandPayload],
        *,
        scope: CommandPayloadScope,
    ) -> dict[str, BackendPayload]:
        """Resolve one payload set to verified backend bytes."""

        return self._materialize_payloads(
            payloads,
            scope=scope,
            content_by_ref={},
        )

    def materialize_payload_sets(
        self,
        payload_sets: Iterable[Mapping[str, CommandPayload]],
        *,
        scope: CommandPayloadScope,
    ) -> tuple[dict[str, BackendPayload], ...]:
        """Resolve an ordered batch atomically before any hardware action."""

        content_by_ref: dict[str, bytes] = {}
        return tuple(
            self._materialize_payloads(
                payloads,
                scope=scope,
                content_by_ref=content_by_ref,
            )
            for payloads in payload_sets
        )

    def _materialize_payloads(
        self,
        payloads: Mapping[str, CommandPayload],
        *,
        scope: CommandPayloadScope,
        content_by_ref: dict[str, bytes],
    ) -> dict[str, BackendPayload]:
        return {
            payload_id: self._materialize_payload(
                payload,
                scope=scope,
                content_by_ref=content_by_ref,
            )
            for payload_id, payload in payloads.items()
        }

    def _canonicalize_payloads(
        self,
        payloads: dict[str, CommandPayload],
        *,
        scope: CommandPayloadScope,
        refs_by_hash: dict[str, str],
    ) -> dict[str, CommandPayload]:
        return {
            payload_id: self._canonicalize_payload(
                payload,
                scope=scope,
                refs_by_hash=refs_by_hash,
            )
            for payload_id, payload in payloads.items()
        }

    def _canonicalize_payload(
        self,
        payload: CommandPayload,
        *,
        scope: CommandPayloadScope,
        refs_by_hash: dict[str, str],
    ) -> CommandPayload:
        self._require_size(
            payload.size_bytes,
            limit=self._max_object_bytes,
            boundary="command payload object",
        )
        if isinstance(payload.body, BlobPayloadBody):
            return payload
        self._require_size(
            payload.size_bytes,
            limit=self._max_inline_bytes,
            boundary="inline command payload",
        )
        ref = refs_by_hash.get(payload.content_hash)
        if ref is None:
            content = payload.inline_bytes()
            receipt = self.put_object(
                content,
                scope=scope,
                expected_content_hash=payload.content_hash,
            )
            ref = receipt.ref
            refs_by_hash[payload.content_hash] = ref
        return payload.model_copy(update={"body": BlobPayloadBody(ref=ref)})

    def _materialize_payload(
        self,
        payload: CommandPayload,
        *,
        scope: CommandPayloadScope,
        content_by_ref: dict[str, bytes],
    ) -> BackendPayload:
        self._require_size(
            payload.size_bytes,
            limit=self._max_object_bytes,
            boundary="command payload object",
        )
        body = payload.body
        if not isinstance(body, BlobPayloadBody):
            content = payload.inline_bytes()
        else:
            content = content_by_ref.get(body.ref)
            if content is None:
                with self._lock:
                    stored = self._objects_by_scope.get(scope, {}).get(body.ref)
                    content = None if stored is None else stored.read()
                if stored is None or content is None:
                    raise CommandPayloadError(
                        f"payload object was not found in command scope: {body.ref}"
                    )
                content_by_ref[body.ref] = content
        _verify_payload(payload, content)
        try:
            encoded_content = EncodedPayloadContent.from_flat_bytes(
                content,
                payload.content_format,
            )
        except AttachmentBundleError as error:
            raise CommandPayloadError(
                f"payload {payload.id} has invalid attachment framing"
            ) from error
        return BackendPayload(
            id=payload.id,
            schema_id=payload.schema_id,
            codec_id=payload.codec_id,
            codec_version=payload.codec_version,
            media_type=payload.media_type,
            content_format=payload.content_format,
            content=encoded_content,
        )

    def release(self, scope: CommandPayloadScope) -> None:
        """Release every transient object for one completed operation."""

        with self._lock:
            self._close_objects(self._objects_by_scope.pop(scope, {}).values())

    def release_owner(
        self,
        owner_kind: Literal["run", "session"],
        owner_id: str,
    ) -> None:
        """Release uploads orphaned when their run or session terminates."""

        with self._lock:
            stale = [
                scope
                for scope in self._objects_by_scope
                if scope[:2] == (owner_kind, owner_id)
            ]
            for scope in stale:
                self._close_objects(self._objects_by_scope.pop(scope).values())

    def close(self) -> None:
        """Drop all process-local payload bytes during daemon shutdown."""

        with self._lock:
            for objects in self._objects_by_scope.values():
                self._close_objects(objects.values())
            self._objects_by_scope.clear()

    def spooled_size_bytes(self) -> int:
        """Return current transient bytes for diagnostics and benchmarks."""

        with self._lock:
            return self._spooled_size_bytes_locked()

    def peak_spooled_size_bytes(self) -> int:
        """Return the largest simultaneous transient working set."""

        with self._lock:
            return self._peak_spooled_size_bytes

    def _spooled_size_bytes_locked(self) -> int:
        return sum(
            content.size_bytes
            for objects in self._objects_by_scope.values()
            for content in objects.values()
        )

    def _store_object(
        self,
        scope: CommandPayloadScope,
        content_hash: str,
        content: _StoredPayloadObject,
    ) -> None:
        with self._lock:
            objects = self._objects_by_scope.setdefault(scope, {})
            retained = objects.setdefault(content_hash, content)
            if retained is not content:
                content.close()
            self._peak_spooled_size_bytes = max(
                self._peak_spooled_size_bytes,
                self._spooled_size_bytes_locked(),
            )

    @staticmethod
    def _close_objects(objects: Iterable[_StoredPayloadObject]) -> None:
        for content in objects:
            content.close()

    @staticmethod
    def _require_size(
        size_bytes: int,
        *,
        limit: int,
        boundary: str,
    ) -> None:
        if size_bytes > limit:
            raise CommandPayloadTooLarge(f"{boundary} exceeds {limit} byte limit")


def _verify_payload(payload: CommandPayload, content: bytes) -> None:
    try:
        payload.verify_content(content)
    except ValueError as error:
        raise CommandPayloadError(
            f"payload {payload.id} failed integrity verification: {error}"
        ) from error


__all__ = [
    "DEFAULT_MAX_INLINE_PAYLOAD_BYTES",
    "DEFAULT_MAX_PAYLOAD_OBJECT_BYTES",
    "CommandPayloadError",
    "CommandPayloadService",
    "CommandPayloadTooLarge",
    "run_payload_scope",
    "session_payload_scope",
]

"""Daemon-local payload working-set telemetry for the deployed benchmark."""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Literal, override

from scopecat.daemon.wire import PayloadObjectReceipt
from scopecat_server.command_payloads import (  # noqa: TID251
    CommandPayloadScope,
    CommandPayloadService,
)


def telemetry_payload_service(
    project_root: Path,
) -> type[CommandPayloadService]:
    """Return the normal service with observable spool accounting."""

    telemetry_path = project_root / "benchmark-daemon-telemetry.jsonl"

    class ProjectCommandPayloadService(CommandPayloadService):
        def __init__(self) -> None:
            super().__init__()
            self._telemetry_lock = Lock()

        @override
        def put_object(
            self,
            content: bytes,
            *,
            scope: CommandPayloadScope,
            expected_content_hash: str,
        ) -> PayloadObjectReceipt:
            receipt = super().put_object(
                content,
                scope=scope,
                expected_content_hash=expected_content_hash,
            )
            self._record_spool()
            return receipt

        @override
        def release(self, scope: CommandPayloadScope) -> None:
            super().release(scope)
            self._record_spool()

        @override
        def release_owner(
            self,
            owner_kind: Literal["run", "session"],
            owner_id: str,
        ) -> None:
            super().release_owner(owner_kind, owner_id)
            self._record_spool()

        @override
        def close(self) -> None:
            super().close()
            self._record_spool()

        def _record_spool(self) -> None:
            document = {
                "kind": "payload_spool",
                "time_ns": time.perf_counter_ns(),
                "current_bytes": self.spooled_size_bytes(),
                "peak_bytes": self.peak_spooled_size_bytes(),
            }
            with (
                self._telemetry_lock,
                telemetry_path.open("a", encoding="utf-8") as stream,
            ):
                stream.write(json.dumps(document, sort_keys=True) + "\n")
                stream.flush()

    return ProjectCommandPayloadService


__all__ = ["telemetry_payload_service"]

"""Build the immutable accepted run skeleton."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.ids import new_run_id
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import RunConfigSource, RunSnapshot
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class RunSkeleton:
    """Accepted snapshot and the inputs persisted with it."""

    snapshot: RunSnapshot
    request: RunRequest
    config: ConfigProfileSnapshot


def build_run_admission(
    *,
    config: ConfigProfileSnapshot,
    request: RunRequest,
    config_source: RunConfigSource | None = None,
) -> RunSkeleton:
    """Create the complete durable state required before execution."""

    return RunSkeleton(
        snapshot=RunSnapshot(
            run_id=new_run_id(),
            config_content_hash=config_content_hash(config),
            config_source=config_source,
        ),
        request=request,
        config=config,
    )

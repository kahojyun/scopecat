"""Discovery record for the daemon currently owning one project."""

from __future__ import annotations

from datetime import datetime
from os import environ
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DAEMON_URL_ENV = "SCOPECAT_DAEMON_URL"
DAEMON_RECORD_NAME = "daemon.json"


class DaemonEndpointError(RuntimeError):
    """A project has no usable daemon endpoint record."""


class DaemonEndpointRecord(BaseModel):
    """Identity and endpoint of the process currently serving one project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.daemon_endpoint.v1"] = (
        "scopecat.daemon_endpoint.v1"
    )
    project_root: Path
    pid: int = Field(gt=0)
    process_create_time: float = Field(gt=0)
    base_url: str = Field(min_length=1)
    started_at: datetime


def daemon_record_path(project_root: str | Path) -> Path:
    """Return the single dynamic endpoint record for ``project_root``."""

    return Path(project_root).resolve() / ".scopecat" / DAEMON_RECORD_NAME


def read_daemon_endpoint_record(
    project_root: str | Path,
) -> DaemonEndpointRecord | None:
    """Read a project's endpoint record without guessing a fallback address."""

    path = daemon_record_path(project_root)
    try:
        return DaemonEndpointRecord.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return None
    except (OSError, ValidationError) as error:
        raise DaemonEndpointError(
            f"cannot read daemon record {path}: {error}"
        ) from error


def resolve_daemon_endpoint(
    project_root: str | Path,
    *,
    explicit: str | None = None,
) -> str:
    """Resolve explicit, environment, then project-record endpoint priority."""

    if explicit is not None:
        return explicit
    environment_endpoint = environ.get(DAEMON_URL_ENV)
    if environment_endpoint is not None:
        return environment_endpoint

    root = Path(project_root).resolve()
    record = read_daemon_endpoint_record(root)
    if record is None:
        raise DaemonEndpointError(
            f"no daemon endpoint for {root}; start it with 'scopecat start'"
        )
    if record.project_root.resolve() != root:
        raise DaemonEndpointError(
            f"daemon record belongs to another project: {record.project_root}"
        )
    return record.base_url


__all__ = [
    "DAEMON_RECORD_NAME",
    "DAEMON_URL_ENV",
    "DaemonEndpointError",
    "DaemonEndpointRecord",
    "daemon_record_path",
    "read_daemon_endpoint_record",
    "resolve_daemon_endpoint",
]

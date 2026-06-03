"""Legacy candidate-storage mutation for reviewed handoff import plans.

This module is retained as historical evidence for
`measurement_record_directory_candidate_v0`. New durable Measurement Records
handoff import work should use `scopecat.handoff.durable_import` instead.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    relative_path_parts,
    validate_non_overlapping_relative_paths,
    validate_public_identifier,
    validate_relative_path,
    validate_strict_child_path,
)
from scopecat.handoff.acceptance_preflight import (
    HandoffAcceptanceDestination,
    HandoffAcceptancePreflightRun,
    run_acceptance_preflight,
)
from scopecat.handoff.package import HandoffMeasurement

_EXPECTED_SCHEMA = "scopecat.handoff_storage_acceptance.v0"
_EXPECTED_POLICY = {
    "workflow_authority": "approved_storage_acceptance_request",
    "acceptance_preflight": "required_ready_acceptance_preflight",
    "destination_authority": "preflight_declared_relative_paths_only",
    "storage_schema": "measurement_record_directory_candidate_v0",
    "primary_data_materialization": "copy_package_primary_data",
    "record_manifest": "write_candidate_manifest",
    "collision_policy": "no_overwrite",
    "rollback": "best_effort_synchronous_cleanup",
    "storage_root_concurrency": "not_supported",
    "archive_handling": "not_performed",
    "external_authenticity_validation": "not_performed",
    "linked_context_payload_import": "not_performed",
    "final_storage_schema": "not_defined",
}
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class HandoffStorageAcceptanceRequest:
    """Approved request to perform the first handoff storage mutation."""

    request_id: str
    requested_package_id: str
    approved_destinations: tuple[HandoffAcceptanceDestination, ...]

    def __post_init__(self) -> None:
        validate_public_identifier(
            self.request_id,
            "storage_acceptance_request.request_id",
        )
        validate_public_identifier(
            self.requested_package_id,
            "storage_acceptance_request.requested_package_id",
        )
        _validate_destination_tuple(
            self.approved_destinations,
            "storage acceptance destinations",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": "approved",
            "requested_package_id": self.requested_package_id,
            "approved_destinations": [
                destination.to_dict() for destination in self.approved_destinations
            ],
        }


@dataclass(frozen=True)
class HandoffStorageAcceptanceRun:
    """Local receipt for handoff storage acceptance."""

    request: HandoffStorageAcceptanceRequest
    preflight: HandoffAcceptancePreflightRun
    write_results: tuple[dict[str, Any], ...] = ()
    rollback_performed: bool = False
    write_error: str | None = None

    @property
    def accepted(self) -> bool:
        return self.classification == "accepted_into_storage"

    @property
    def classification(self) -> str:
        if self.write_error is not None:
            if not self.rollback_performed:
                return "blocked_before_acceptance"
            return "rolled_back_after_write_failure"
        if not self.preflight.acceptance_preflight_allowed:
            return "blocked_before_acceptance"
        return "accepted_into_storage"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_storage_acceptance_receipt",
            "storage_acceptance_policy": copy.deepcopy(_EXPECTED_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "run_acceptance_preflight",
                    "validate_storage_acceptance_request",
                    *(
                        []
                        if not self.preflight.acceptance_preflight_allowed
                        else ["write_storage_record"]
                    ),
                ],
                "does_not_claim": [
                    "final_storage_schema",
                    "existing_record_update",
                    "conflict_resolution",
                    "crash_recovery",
                    "concurrent_storage_root_mutation",
                    "archive_extraction",
                    "external_authenticity_or_trust_validation",
                    "linked_context_payload_import",
                    "schema_inference",
                    "scientific_validity",
                ],
            },
            "request": self.request.to_dict(),
            "preflight": {
                "classification": self.preflight.classification,
                "allowed": self.preflight.acceptance_preflight_allowed,
            },
            "acceptance": {
                "performed": self.accepted,
                "rollback_performed": self.rollback_performed,
                "write_error": self.write_error,
                "write_results": [copy.deepcopy(item) for item in self.write_results],
            },
        }


def run_storage_acceptance(
    source: dict[str, Any],
    *,
    package_dir: str | Path,
    storage_root: str | Path,
) -> HandoffStorageAcceptanceRun:
    """Accept reviewed package primary data into candidate storage."""

    request, preflight_source = _parse_source(source)
    root = _existing_storage_root(Path(storage_root))
    preflight = run_acceptance_preflight(
        preflight_source,
        package_dir=package_dir,
        storage_root=root,
    )
    return run_storage_acceptance_from_preflight(
        request,
        preflight=preflight,
        package_dir=package_dir,
        storage_root=root,
    )


def run_storage_acceptance_from_preflight(
    request: HandoffStorageAcceptanceRequest,
    *,
    preflight: HandoffAcceptancePreflightRun,
    package_dir: str | Path,
    storage_root: str | Path,
) -> HandoffStorageAcceptanceRun:
    """Accept storage from an already typed acceptance preflight."""

    root = _existing_storage_root(Path(storage_root))
    package_root = _existing_package_root(Path(package_dir))
    _validate_against_preflight(request=request, preflight=preflight)
    _validate_roots_against_preflight(
        package_root=package_root,
        storage_root=root,
        preflight=preflight,
    )
    if not preflight.acceptance_preflight_allowed:
        return HandoffStorageAcceptanceRun(request=request, preflight=preflight)

    files, write_results = _planned_files(
        package_root=package_root,
        request=request,
        preflight=preflight,
    )
    guard_paths = [
        path for destination in request.approved_destinations for path in destination.target_paths
    ]
    try:
        _write_new_files_transaction(
            root,
            files,
            guard_paths=guard_paths,
            label="handoff storage acceptance",
        )
    except _StorageWriteFailure as exc:
        return HandoffStorageAcceptanceRun(
            request=request,
            preflight=preflight,
            rollback_performed=exc.rollback_performed,
            write_error=str(exc),
        )

    return HandoffStorageAcceptanceRun(
        request=request,
        preflight=preflight,
        write_results=tuple(write_results),
    )


def _existing_storage_root(storage_root: Path) -> Path:
    if storage_root.is_symlink():
        raise ValueError("handoff storage acceptance storage root must not be a symlink")
    if not storage_root.is_dir():
        raise ValueError("handoff storage acceptance requires an existing storage root")
    return storage_root.resolve()


def _existing_package_root(package_dir: Path) -> Path:
    if package_dir.is_symlink():
        raise ValueError("handoff storage acceptance package directory must not be a symlink")
    if not package_dir.is_dir():
        raise ValueError("handoff storage acceptance requires an existing package directory")
    return package_dir.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*relative_path_parts(relative_path, "handoff storage acceptance path"))


def _ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    for part in relative_path_parts(relative_path, label)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{label} parent is not a directory")


def _target_exists(root: Path, relative_path: str) -> bool:
    return os.path.lexists(_path_under(root, relative_path))


def _reject_existing_paths(root: Path, relative_paths: list[str], label: str) -> None:
    for relative_path in relative_paths:
        if _target_exists(root, relative_path):
            raise ValueError(f"{label} target already exists")
        _ensure_no_symlink_parents(root, relative_path, label)


def _open_dir_fd(path: Path | str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW
    if dir_fd is None:
        return os.open(path, flags)
    return os.open(path, flags, dir_fd=dir_fd)


def _remove_created_dirs(root: Path, created_dirs: list[str]) -> None:
    for relative_path in reversed(created_dirs):
        try:
            _path_under(root, relative_path).rmdir()
        except OSError:
            pass


def _open_parent_dir_fd(root: Path, relative_path: str, *, create: bool) -> tuple[int, list[str]]:
    root_fd = _open_dir_fd(root)
    current_fd = root_fd
    current_parts: list[str] = []
    created_dirs: list[str] = []
    try:
        for part in relative_path_parts(relative_path)[:-1]:
            current_parts.append(part)
            if create:
                try:
                    os.mkdir(part, dir_fd=current_fd)
                    created_dirs.append("/".join(current_parts))
                except FileExistsError:
                    pass
            next_fd = _open_dir_fd(part, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        if current_fd == root_fd:
            return root_fd, created_dirs
        os.close(root_fd)
        return current_fd, created_dirs
    except Exception:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)
        if create:
            _remove_created_dirs(root, created_dirs)
        raise


def _write_new_file(root: Path, relative_path: str, content: bytes, *, label: str) -> list[str]:
    _ensure_no_symlink_parents(root, relative_path, label)
    parent_fd: int | None = None
    created_dirs: list[str] = []
    created_file = False
    try:
        parent_fd, created_dirs = _open_parent_dir_fd(root, relative_path, create=True)
        file_fd = os.open(
            relative_path_parts(relative_path)[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            0o666,
            dir_fd=parent_fd,
        )
        created_file = True
        with os.fdopen(file_fd, "wb") as handle:
            handle.write(content)
    except Exception as exc:
        if created_file:
            try:
                _path_under(root, relative_path).unlink()
            except FileNotFoundError:
                pass
            _remove_created_dirs(root, created_dirs)
            raise _StorageWriteFailure(
                f"{label} target write failed after file creation: {exc}",
                rollback_performed=True,
            ) from exc
        _remove_created_dirs(root, created_dirs)
        raise
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    return created_dirs


def _rollback_written_files(root: Path, written_paths: list[str], created_dirs: list[str]) -> None:
    for relative_path in reversed(written_paths):
        try:
            _path_under(root, relative_path).unlink()
        except FileNotFoundError:
            pass
    _remove_created_dirs(root, created_dirs)


class _StorageWriteFailure(RuntimeError):
    def __init__(self, message: str, *, rollback_performed: bool) -> None:
        super().__init__(message)
        self.rollback_performed = rollback_performed


def _write_new_files_transaction(
    root: Path,
    files: list[tuple[str, bytes]],
    *,
    guard_paths: list[str] | None = None,
    label: str,
) -> None:
    try:
        _reject_existing_paths(
            root,
            guard_paths or [relative_path for relative_path, _content in files],
            label,
        )
    except Exception as exc:
        raise _StorageWriteFailure(str(exc), rollback_performed=False) from exc
    written_paths: list[str] = []
    created_dirs: list[str] = []
    try:
        for relative_path, content in files:
            created_dirs.extend(_write_new_file(root, relative_path, content, label=label))
            written_paths.append(relative_path)
    except _StorageWriteFailure as exc:
        _rollback_written_files(root, written_paths, created_dirs)
        raise _StorageWriteFailure(
            str(exc),
            rollback_performed=exc.rollback_performed or bool(written_paths),
        ) from exc
    except Exception as exc:
        _rollback_written_files(root, written_paths, created_dirs)
        raise _StorageWriteFailure(str(exc), rollback_performed=bool(written_paths)) from exc


def _read_package_member(package_root: Path, relative_path: str) -> bytes:
    _ensure_no_symlink_parents(package_root, relative_path, "handoff package primary data")
    target = _path_under(package_root, relative_path)
    if target.is_symlink():
        raise ValueError("handoff package primary data must not be a symlink")
    try:
        file_fd = os.open(target, os.O_RDONLY | _NOFOLLOW)
    except FileNotFoundError as exc:
        raise ValueError("handoff package primary data is unavailable") from exc
    file_stat = os.fstat(file_fd)
    if not stat.S_ISREG(file_stat.st_mode):
        os.close(file_fd)
        raise ValueError("handoff package primary data must be a regular file")
    with os.fdopen(file_fd, "rb") as handle:
        return handle.read()


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _integrity_fact(
    *,
    preflight: HandoffAcceptancePreflightRun,
    package_path: str,
) -> dict[str, Any]:
    for observation in preflight.import_plan.receiving_gate.integrity_report.member_observations:
        if observation.package_path == package_path:
            return observation.to_dict()
    raise ValueError("accepted package primary data integrity observation is missing")


def _validate_copied_content_against_integrity(
    *,
    integrity_fact: dict[str, Any],
    digest: str,
    size_bytes: int,
) -> None:
    if integrity_fact.get("comparison") != "verified":
        raise ValueError("accepted package primary data integrity must match declared facts")
    if integrity_fact.get("observed_digest") != digest:
        raise ValueError("accepted package primary data digest must match preflight integrity")
    if integrity_fact.get("observed_size_bytes") != size_bytes:
        raise ValueError("accepted package primary data size must match preflight integrity")


def _manifest_bytes(
    *,
    preflight: HandoffAcceptancePreflightRun,
    destination: HandoffAcceptanceDestination,
    measurement: HandoffMeasurement,
    primary_digest: str,
    primary_size_bytes: int,
    integrity_fact: dict[str, Any],
) -> bytes:
    manifest = {
        "schema": destination.storage_schema,
        "record": {
            "destination_record_id": destination.destination_record_id,
            "measurement_record_id": destination.measurement_record_id,
            "label": measurement.label,
            "experiment_type": measurement.experiment_type,
            "target": measurement.target,
        },
        "source": {
            "package_id": preflight.import_plan.package.package_id,
            "package_measurement_record_id": measurement.measurement_record_id,
            "package_primary_data_path": measurement.primary_package_path,
            "package_preview_classification": preflight.import_plan.package.preview_classification,
            "integrity_classification": preflight.import_plan.receiving_gate.integrity_report.classification,
        },
        "primary_data": {
            "path": destination.primary_data_path,
            "format": measurement.primary_format,
            "digest": primary_digest,
            "size_bytes": primary_size_bytes,
        },
        "declared_preview": {
            "status": "preview_ready",
            "metadata_authority": measurement.declared_preview_metadata_authority,
            "data_shape": copy.deepcopy(measurement.declared_preview_shape),
            "declared_columns": [
                copy.deepcopy(column) for column in measurement.declared_preview_columns
            ],
            "plot_candidates": [
                copy.deepcopy(candidate)
                for candidate in measurement.declared_preview_plot_candidates
            ],
        },
        "source_integrity": copy.deepcopy(integrity_fact),
        "linked_context": [item.to_dict() for item in measurement.linked_context],
        "does_not_claim": [
            "final_storage_schema",
            "package_authenticity",
            "linked_context_payload_import",
            "schema_inference",
            "scientific_validity",
        ],
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _planned_files(
    *,
    package_root: Path,
    request: HandoffStorageAcceptanceRequest,
    preflight: HandoffAcceptancePreflightRun,
) -> tuple[list[tuple[str, bytes]], list[dict[str, Any]]]:
    files: list[tuple[str, bytes]] = []
    write_results: list[dict[str, Any]] = []
    measurement_by_id = {
        plan.measurement.measurement_record_id: plan.measurement
        for plan in preflight.import_plan.measurement_plans
    }
    for destination in request.approved_destinations:
        measurement = measurement_by_id[destination.measurement_record_id]
        primary_content = _read_package_member(package_root, measurement.primary_package_path)
        primary_digest = _sha256(primary_content)
        primary_size = len(primary_content)
        integrity_fact = _integrity_fact(
            preflight=preflight,
            package_path=measurement.primary_package_path,
        )
        _validate_copied_content_against_integrity(
            integrity_fact=integrity_fact,
            digest=primary_digest,
            size_bytes=primary_size,
        )
        manifest_content = _manifest_bytes(
            preflight=preflight,
            destination=destination,
            measurement=measurement,
            primary_digest=primary_digest,
            primary_size_bytes=primary_size,
            integrity_fact=integrity_fact,
        )
        files.extend(
            [
                (destination.primary_data_path, primary_content),
                (destination.manifest_path, manifest_content),
            ]
        )
        write_results.extend(
            [
                {
                    "path": destination.primary_data_path,
                    "kind": "primary_data",
                    "state": "written",
                    "size_bytes": primary_size,
                    "digest": primary_digest,
                },
                {
                    "path": destination.manifest_path,
                    "kind": "record_manifest",
                    "state": "written",
                    "size_bytes": len(manifest_content),
                },
            ]
        )
    return files, write_results


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _parse_source(
    source: dict[str, Any],
) -> tuple[HandoffStorageAcceptanceRequest, dict[str, Any]]:
    source = _require_mapping(source, "handoff storage acceptance source")
    _require_keys(
        source,
        {
            "storage_acceptance_schema",
            "storage_acceptance_policy",
            "acceptance_preflight_source",
            "storage_acceptance_request",
        },
        "handoff storage acceptance source",
    )
    if source["storage_acceptance_schema"] != _EXPECTED_SCHEMA:
        raise ValueError("storage_acceptance_schema is unsupported")
    if source["storage_acceptance_policy"] != _EXPECTED_POLICY:
        raise ValueError("storage_acceptance_policy is unsupported")

    preflight_source = _require_mapping(
        source["acceptance_preflight_source"],
        "acceptance_preflight_source",
    )
    request = _parse_request(source["storage_acceptance_request"])
    return request, copy.deepcopy(preflight_source)


def _parse_request(source: Any) -> HandoffStorageAcceptanceRequest:
    request = _require_mapping(source, "storage_acceptance_request")
    _require_keys(
        request,
        {
            "request_id",
            "approval_state",
            "requested_package_id",
            "approved_destinations",
        },
        "storage_acceptance_request",
    )
    if request["approval_state"] != "approved":
        raise ValueError("handoff storage acceptance requires approved request")
    return HandoffStorageAcceptanceRequest(
        request_id=validate_public_identifier(
            request["request_id"],
            "storage_acceptance_request.request_id",
        ),
        requested_package_id=validate_public_identifier(
            request["requested_package_id"],
            "storage_acceptance_request.requested_package_id",
        ),
        approved_destinations=_parse_destinations(request["approved_destinations"]),
    )


def _parse_destinations(source: Any) -> tuple[HandoffAcceptanceDestination, ...]:
    if not isinstance(source, list):
        raise ValueError("storage acceptance destinations must be a list")
    destinations = tuple(_parse_destination(item) for item in source)
    _validate_destination_tuple(destinations, "storage acceptance destinations")
    return destinations


def _validate_destination_tuple(
    destinations: tuple[HandoffAcceptanceDestination, ...],
    owner: str,
) -> None:
    if not destinations:
        raise ValueError(f"{owner} must not be empty")
    if not all(isinstance(item, HandoffAcceptanceDestination) for item in destinations):
        raise ValueError(f"{owner} must be typed acceptance destinations")
    measurement_ids = [item.measurement_record_id for item in destinations]
    if len(set(measurement_ids)) != len(measurement_ids):
        raise ValueError(f"{owner} measurement ids must be unique")
    destination_record_ids = [item.destination_record_id for item in destinations]
    if len(set(destination_record_ids)) != len(destination_record_ids):
        raise ValueError(f"{owner} record ids must be unique")
    target_paths = [path for item in destinations for path in item.target_paths]
    if len(set(target_paths)) != len(target_paths):
        raise ValueError(f"{owner} paths must be unique")
    validate_non_overlapping_relative_paths(
        [item.record_dir for item in destinations],
        f"{owner} record dirs",
    )


def _parse_destination(source: Any) -> HandoffAcceptanceDestination:
    destination = _require_mapping(source, "storage acceptance destination")
    _require_keys(
        destination,
        {
            "measurement_record_id",
            "destination_record_id",
            "record_dir",
            "primary_data_path",
            "manifest_path",
            "storage_schema",
        },
        "storage acceptance destination",
    )
    record_dir = validate_relative_path(
        destination["record_dir"],
        "storage acceptance destination record_dir",
    )
    primary_data_path = validate_strict_child_path(
        destination["primary_data_path"],
        record_dir,
        "storage acceptance destination primary_data_path",
    )
    manifest_path = validate_strict_child_path(
        destination["manifest_path"],
        record_dir,
        "storage acceptance destination manifest_path",
    )
    if primary_data_path == manifest_path:
        raise ValueError("storage acceptance destination paths must be unique")
    storage_schema = validate_public_identifier(
        destination["storage_schema"],
        "storage acceptance destination storage_schema",
    )
    if storage_schema != "measurement_record_directory_candidate_v0":
        raise ValueError("storage acceptance destination storage_schema is unsupported")

    return HandoffAcceptanceDestination(
        measurement_record_id=validate_public_identifier(
            destination["measurement_record_id"],
            "storage acceptance destination measurement_record_id",
        ),
        destination_record_id=validate_public_identifier(
            destination["destination_record_id"],
            "storage acceptance destination destination_record_id",
        ),
        record_dir=record_dir,
        primary_data_path=primary_data_path,
        manifest_path=manifest_path,
        storage_schema=storage_schema,
    )


def _validate_against_preflight(
    *,
    request: HandoffStorageAcceptanceRequest,
    preflight: HandoffAcceptancePreflightRun,
) -> None:
    if request.requested_package_id != preflight.import_plan.package.package_id:
        raise ValueError("requested package id must match acceptance preflight package")
    if request.approved_destinations != preflight.request.destinations:
        raise ValueError("storage acceptance destinations must match acceptance preflight")


def _validate_roots_against_preflight(
    *,
    package_root: Path,
    storage_root: Path,
    preflight: HandoffAcceptancePreflightRun,
) -> None:
    if str(package_root) != preflight.package_dir:
        raise ValueError("storage acceptance package_dir must match acceptance preflight")
    if str(storage_root) != preflight.storage_root:
        raise ValueError("storage acceptance storage_root must match acceptance preflight")

"""Route-local writer for directory-shaped handoff packages."""

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
    HANDOFF_PACKAGE_CREATED_BY,
    MANIFEST_AUTHORITY,
    relative_path_parts,
    validate_context_reference,
    validate_handoff_preview_ready_metadata,
    validate_non_negative_integer,
    validate_package_item_shape,
    validate_package_primary_data_path,
    validate_positive_integer,
    validate_public_identifier,
    validate_redacted_display_ref,
    validate_relative_path,
    validate_sha256_digest,
    validate_strict_child_path,
    validate_text,
    validate_unique_reference_targets,
)
from scopecat.handoff._declared_preview import (
    HandoffPackagePreviewColumn as HandoffPackagePreviewColumn,
)
from scopecat.handoff._declared_preview import (
    HandoffPackagePreviewMetadata,
)
from scopecat.handoff._manifest_preview import preview_handoff_manifest

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class HandoffPackageWriteReceipt:
    """Local receipt for one handoff package write."""

    package_id: str
    display_name: str
    source_export_summary_id: str
    display_path: str
    request_id: str
    package_dir: str
    manifest_path: str
    selected_measurements: tuple[dict[str, Any], ...]
    package_contents: tuple[dict[str, Any], ...]
    write_results: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_write_receipt",
            "package": {
                "package_id": self.package_id,
                "display_name": self.display_name,
                "created_by": "scopecat_selected_measurement_export",
                "source_export_summary_id": self.source_export_summary_id,
                "display_path": self.display_path,
                "classification": "package_written_ready_for_transfer_review",
            },
            "write_request": {
                "request_id": self.request_id,
                "approval_state": "approved",
                "package_dir": self.package_dir,
                "manifest_path": self.manifest_path,
                "collision_policy": "no_overwrite",
            },
            "selected_measurements": [copy.deepcopy(item) for item in self.selected_measurements],
            "package_contents": [copy.deepcopy(item) for item in self.package_contents],
            "write_results": [copy.deepcopy(item) for item in self.write_results],
        }


@dataclass(frozen=True)
class HandoffPackageIdentity:
    package_id: str
    display_name: str
    created_by: str
    source_export_summary_id: str
    display_path: str
    local_path_redacted: bool

    def to_manifest(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "display_name": self.display_name,
            "created_by": self.created_by,
            "source_export_summary_id": self.source_export_summary_id,
            "local_path_redacted": self.local_path_redacted,
        }


@dataclass(frozen=True)
class HandoffPackageWriteRequest:
    request_id: str
    package_dir: str
    manifest_path: str

    def actual_package_path(self, package_path: str) -> str:
        return f"{self.package_dir}/{package_path}"


@dataclass(frozen=True)
class HandoffPackagePrimaryData:
    kind: str
    label: str
    source_path: str
    expected_digest: str
    expected_size_bytes: int
    package_path: str
    include_status: str
    relation: str
    authority: str
    format: str
    package_state: str
    reason: str | None

    def to_manifest(self, *, digest: str, size: int) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "package_path": self.package_path,
            "include_status": self.include_status,
            "relation": self.relation,
            "authority": self.authority,
            "format": self.format,
            "package_state": self.package_state,
            "reason": self.reason,
            "digest": digest,
            "size_bytes": size,
        }


@dataclass(frozen=True)
class HandoffPackageBundleItem:
    item_id: str
    kind: str
    label: str
    package_path: str
    include_status: str
    relation: str
    authority: str
    package_state: str
    reason: str | None

    def to_manifest(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "label": self.label,
            "package_path": self.package_path,
            "include_status": self.include_status,
            "relation": self.relation,
            "authority": self.authority,
            "package_state": self.package_state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HandoffPackageSelectedMeasurement:
    measurement_record_id: str
    legacy_data_id: int
    label: str
    experiment_type: str
    target: str
    primary_data: HandoffPackagePrimaryData
    declared_preview_metadata: HandoffPackagePreviewMetadata
    default_bundle: tuple[HandoffPackageBundleItem, ...]

    def to_manifest(self, *, digest: str, size: int) -> dict[str, Any]:
        return {
            "measurement_record_id": self.measurement_record_id,
            "legacy_data_id": self.legacy_data_id,
            "label": self.label,
            "experiment_type": self.experiment_type,
            "target": self.target,
            "primary_data": self.primary_data.to_manifest(digest=digest, size=size),
            "declared_preview_metadata": self.declared_preview_metadata.to_manifest(),
            "default_bundle": [item.to_manifest() for item in self.default_bundle],
        }


@dataclass(frozen=True)
class HandoffPackageLinkedContext:
    link_id: str
    kind: str
    label: str
    package_path: str | None
    include_status: str
    relation: str
    authority: str
    package_state: str
    reason: str | None
    linked_measurement_record_ids: tuple[str, ...]
    source_path: str | None = None
    expected_digest: str | None = None
    expected_size_bytes: int | None = None
    context_reference: dict[str, str] | None = None

    def to_manifest(self, *, digest: str | None = None, size: int | None = None) -> dict[str, Any]:
        result = {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "package_path": self.package_path,
            "include_status": self.include_status,
            "relation": self.relation,
            "authority": self.authority,
            "package_state": self.package_state,
            "reason": self.reason,
            "linked_measurement_record_ids": list(self.linked_measurement_record_ids),
        }
        if self.package_state == "packaged":
            if digest is None or size is None:
                raise ValueError("packaged linked context requires digest and size")
            result["digest"] = digest
            result["size_bytes"] = size
        if self.context_reference is not None:
            result["context_reference"] = dict(self.context_reference)
        return result


@dataclass(frozen=True)
class HandoffPackageWriteSource:
    identity: HandoffPackageIdentity
    request: HandoffPackageWriteRequest
    selected_measurements: tuple[HandoffPackageSelectedMeasurement, ...]
    linked_context: tuple[HandoffPackageLinkedContext, ...]


@dataclass(frozen=True)
class _CopiedSource:
    record: HandoffPackageSelectedMeasurement
    content: bytes


@dataclass(frozen=True)
class _CopiedLinkedContext:
    context: HandoffPackageLinkedContext
    content: bytes


def _linked_context_package_path(context: HandoffPackageLinkedContext) -> str:
    if context.package_path is None:
        raise ValueError("packaged linked context requires package_path")
    return context.package_path


def write_package_from_source(
    source: HandoffPackageWriteSource,
    *,
    source_root: Path,
    package_root: Path,
) -> HandoffPackageWriteReceipt:
    """Write a directory-shaped handoff package from typed selected-record sources."""

    _validate_write_source(source)
    source_root_resolved = _existing_directory_root(source_root, "handoff package source")
    package_root_resolved = _existing_directory_root(package_root, "handoff package destination")
    _validate_package_root_outside_source(
        source_root_resolved,
        package_root_resolved,
        owner="handoff package writer",
    )

    copied_sources = _preflight_sources(source, source_root_resolved)
    copied_contexts = _preflight_linked_context(source, source_root_resolved)
    _ensure_new_targets(source, package_root_resolved)
    manifest_content = _manifest_bytes(source, copied_sources, copied_contexts)

    files = [
        (
            source.request.actual_package_path(copied.record.primary_data.package_path),
            copied.content,
        )
        for copied in copied_sources
    ]
    files.extend(
        (
            source.request.actual_package_path(_linked_context_package_path(copied.context)),
            copied.content,
        )
        for copied in copied_contexts
    )
    files.append((source.request.manifest_path, manifest_content))
    _write_new_files_transaction(package_root_resolved, files, label="handoff package")

    return _write_receipt(source, copied_sources, copied_contexts, manifest_content)


def _validate_write_source(source: HandoffPackageWriteSource) -> None:
    _validate_identity(source.identity)
    _validate_write_request(source.request, identity=source.identity)
    _validate_selected_measurements(source.selected_measurements)
    _validate_linked_context(source.linked_context, measurements=source.selected_measurements)
    _validate_destination_topology(source)


def _validate_identity(identity: HandoffPackageIdentity) -> None:
    validate_public_identifier(identity.package_id, "handoff package package_id")
    validate_text(identity.display_name, "handoff package display_name")
    if identity.created_by != HANDOFF_PACKAGE_CREATED_BY:
        raise ValueError(f"handoff package created_by must be {HANDOFF_PACKAGE_CREATED_BY}")
    validate_public_identifier(
        identity.source_export_summary_id,
        "handoff package source_export_summary_id",
    )
    if identity.local_path_redacted is not True:
        raise ValueError("handoff package local path must stay redacted")
    validate_redacted_display_ref(
        identity.display_path,
        "handoff package display_path",
        prefix="HANDOFF_PACKAGE:",
    )


def _validate_write_request(
    request: HandoffPackageWriteRequest,
    *,
    identity: HandoffPackageIdentity,
) -> None:
    expected_package_dir = identity.package_id
    expected_manifest_path = f"{expected_package_dir}/package-manifest.json"
    validate_relative_path(request.package_dir, "handoff package package_dir")
    validate_relative_path(request.manifest_path, "handoff package manifest_path")
    if request.package_dir != expected_package_dir:
        raise ValueError("handoff package package_dir must match package_id")
    if request.manifest_path != expected_manifest_path:
        raise ValueError("handoff package manifest_path must be package_id/package-manifest.json")
    validate_strict_child_path(
        request.manifest_path,
        request.package_dir,
        "handoff package manifest_path",
    )
    validate_public_identifier(request.request_id, "handoff package request_id")


def _validate_primary_data(record: HandoffPackageSelectedMeasurement) -> None:
    measurement_id = record.measurement_record_id
    validate_public_identifier(measurement_id, "measurement_record_id")
    validate_non_negative_integer(record.legacy_data_id, "measurement legacy_data_id")
    validate_text(record.label, "measurement label")
    validate_public_identifier(record.experiment_type, "measurement experiment_type")
    validate_public_identifier(record.target, "measurement target")
    primary = record.primary_data
    expected = {
        "kind": "primary_data",
        "include_status": "included_by_default",
        "relation": "selected_measurement_source",
        "authority": MANIFEST_AUTHORITY,
        "format": "csv_table",
        "package_state": "packaged",
        "reason": None,
    }
    for key, value in expected.items():
        if getattr(primary, key) != value:
            raise ValueError(f"handoff package primary_data {key} must be {value}")
    validate_text(primary.label, "handoff package primary_data label")
    validate_relative_path(primary.source_path, "handoff package primary_data source_path")
    validate_package_primary_data_path(
        primary.package_path,
        measurement_record_id=measurement_id,
        owner="handoff package primary_data package_path",
    )
    validate_sha256_digest(
        primary.expected_digest,
        "handoff package primary_data expected_digest",
    )
    validate_positive_integer(
        primary.expected_size_bytes,
        "handoff package primary_data expected_size_bytes",
    )


def _validate_default_bundle(record: HandoffPackageSelectedMeasurement) -> None:
    bundle = record.default_bundle
    if len(bundle) != 1:
        raise ValueError("handoff package writer currently writes one primary bundle item")
    item = bundle[0]
    primary = record.primary_data
    expected = {
        "item_id": f"{record.measurement_record_id}-primary",
        "kind": "primary_data",
        "label": primary.label,
        "package_path": primary.package_path,
        "include_status": "included_by_default",
        "relation": "selected_measurement_source",
        "authority": MANIFEST_AUTHORITY,
        "package_state": "packaged",
        "reason": None,
    }
    for key, value in expected.items():
        if getattr(item, key) != value:
            raise ValueError("handoff package default bundle must match primary data")
    validate_package_item_shape(item.to_manifest(), "handoff package default bundle")


def _validate_selected_measurements(
    measurements: tuple[HandoffPackageSelectedMeasurement, ...],
) -> None:
    if not measurements:
        raise ValueError("handoff package writer requires selected_measurements")
    seen_ids = set()
    seen_paths = set()
    for record in measurements:
        _validate_primary_data(record)
        measurement_id = record.measurement_record_id
        if measurement_id in seen_ids:
            raise ValueError(f"duplicate measurement_record_id: {measurement_id}")
        seen_ids.add(measurement_id)
        validate_handoff_preview_ready_metadata(
            record.declared_preview_metadata.to_manifest(),
            primary_path=record.primary_data.package_path,
            owner="handoff package preview",
        )
        _validate_default_bundle(record)
        package_path = record.primary_data.package_path
        if package_path in seen_paths:
            raise ValueError(f"duplicate package_path: {package_path}")
        seen_paths.add(package_path)


def _validate_linked_context(
    linked_context: tuple[HandoffPackageLinkedContext, ...],
    *,
    measurements: tuple[HandoffPackageSelectedMeasurement, ...],
) -> None:
    selected_ids = {record.measurement_record_id for record in measurements}
    seen_ids = set()
    for item in linked_context:
        link_id = item.link_id
        validate_public_identifier(link_id, "linked context link_id")
        if link_id in seen_ids:
            raise ValueError(f"duplicate linked context id: {link_id}")
        seen_ids.add(link_id)
        validate_public_identifier(item.kind, f"linked context {link_id} kind")
        validate_text(item.label, f"linked context {link_id} label")
        validate_public_identifier(item.relation, f"linked context {link_id} relation")
        validate_package_item_shape(_linked_context_to_item_dict(item), f"linked context {link_id}")
        if item.authority != MANIFEST_AUTHORITY:
            raise ValueError("handoff package linked context authority must stay manifest declared")
        if item.package_state == "packaged":
            validate_strict_child_path(
                item.package_path,
                "context",
                f"handoff package linked context {link_id} package_path",
            )
            validate_relative_path(
                item.source_path,
                f"handoff package linked context {link_id} source_path",
            )
            validate_sha256_digest(
                item.expected_digest,
                f"handoff package linked context {link_id} expected_digest",
            )
            validate_positive_integer(
                item.expected_size_bytes,
                f"handoff package linked context {link_id} expected_size_bytes",
            )
        else:
            if (
                item.source_path is not None
                or item.expected_digest is not None
                or item.expected_size_bytes is not None
            ):
                raise ValueError(
                    "handoff package non-packaged linked context must not carry source payload fields"
                )
        validate_unique_reference_targets(
            list(item.linked_measurement_record_ids),
            selected_ids=selected_ids,
            owner="handoff package linked context",
        )
        _validate_context_reference(item)


def _validate_context_reference(item: HandoffPackageLinkedContext) -> None:
    reference = item.context_reference
    if reference is None:
        return
    validate_context_reference(
        reference,
        item_kind=item.kind,
        owner="handoff package linked context",
    )


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = relative_path_parts(left)
    right_parts = relative_path_parts(right)
    return (
        left_parts[: len(right_parts)] == right_parts
        or right_parts[: len(left_parts)] == left_parts
    )


def _validate_destination_topology(source: HandoffPackageWriteSource) -> None:
    output_paths = [source.request.manifest_path]
    output_paths.extend(
        source.request.actual_package_path(record.primary_data.package_path)
        for record in source.selected_measurements
    )
    output_paths.extend(
        source.request.actual_package_path(item.package_path)
        for item in source.linked_context
        if item.package_path is not None
    )
    for index, path in enumerate(output_paths):
        for other in output_paths[index + 1 :]:
            if path == other:
                raise ValueError(f"duplicate package output path: {path}")
            if _paths_overlap(path, other):
                raise ValueError(f"overlapping package output path: {path}")


def _linked_context_to_item_dict(item: HandoffPackageLinkedContext) -> dict[str, Any]:
    return {
        "link_id": item.link_id,
        "kind": item.kind,
        "label": item.label,
        "package_path": item.package_path,
        "include_status": item.include_status,
        "relation": item.relation,
        "authority": item.authority,
        "package_state": item.package_state,
        "reason": item.reason,
        "linked_measurement_record_ids": list(item.linked_measurement_record_ids),
    }


def _existing_directory_root(root: Path, label: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"{label} root must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"{label} root must be an existing directory")
    return root.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*relative_path_parts(relative_path))


def _validate_package_root_outside_source(
    source_root: Path, package_root: Path, owner: str
) -> None:
    try:
        package_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError(f"{owner} package root must stay outside source root")
    try:
        source_root.relative_to(package_root)
    except ValueError:
        pass
    else:
        raise ValueError(f"{owner} source root must stay outside package root")


def _ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    for part in relative_path_parts(relative_path, label)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{label} parent is not a directory")


def _open_dir_fd(path: Path | str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW
    if dir_fd is None:
        return os.open(path, flags)
    return os.open(path, flags, dir_fd=dir_fd)


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


def _read_source_file(source_root: Path, record: HandoffPackageSelectedMeasurement) -> bytes:
    primary = record.primary_data
    source_path = primary.source_path
    _ensure_no_symlink_parents(source_root, source_path, "source")
    try:
        parent_fd, _created_dirs = _open_parent_dir_fd(source_root, source_path, create=False)
    except OSError as exc:
        raise ValueError("handoff package source file is unavailable") from exc
    try:
        try:
            file_fd = os.open(
                relative_path_parts(source_path)[-1],
                os.O_RDONLY | _NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise ValueError("handoff package source file is unavailable") from exc
        with os.fdopen(file_fd, "rb") as handle:
            source_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError("handoff package source file is unavailable")
            if source_stat.st_size != primary.expected_size_bytes:
                raise ValueError("handoff package source size does not match")
            content = handle.read()
    finally:
        os.close(parent_fd)
    digest = _sha256(content)
    if digest != primary.expected_digest:
        raise ValueError("handoff package source digest does not match")
    if len(content) != primary.expected_size_bytes:
        raise ValueError("handoff package source size does not match")
    return content


def _read_linked_context_file(source_root: Path, context: HandoffPackageLinkedContext) -> bytes:
    source_path = context.source_path
    if (
        context.package_state != "packaged"
        or source_path is None
        or context.expected_digest is None
        or context.expected_size_bytes is None
    ):
        raise ValueError("packaged linked context requires declared source payload facts")
    _ensure_no_symlink_parents(source_root, source_path, "linked context source")
    try:
        parent_fd, _created_dirs = _open_parent_dir_fd(source_root, source_path, create=False)
    except OSError as exc:
        raise ValueError("handoff package linked context source file is unavailable") from exc
    try:
        try:
            file_fd = os.open(
                relative_path_parts(source_path)[-1],
                os.O_RDONLY | _NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise ValueError("handoff package linked context source file is unavailable") from exc
        with os.fdopen(file_fd, "rb") as handle:
            source_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError("handoff package linked context source file is unavailable")
            if source_stat.st_size != context.expected_size_bytes:
                raise ValueError("handoff package linked context source size does not match")
            content = handle.read()
    finally:
        os.close(parent_fd)
    digest = _sha256(content)
    if digest != context.expected_digest:
        raise ValueError("handoff package linked context source digest does not match")
    if len(content) != context.expected_size_bytes:
        raise ValueError("handoff package linked context source size does not match")
    return content


def _preflight_sources(source: HandoffPackageWriteSource, source_root: Path) -> list[_CopiedSource]:
    return [
        _CopiedSource(record=record, content=_read_source_file(source_root, record))
        for record in source.selected_measurements
    ]


def _preflight_linked_context(
    source: HandoffPackageWriteSource, source_root: Path
) -> list[_CopiedLinkedContext]:
    return [
        _CopiedLinkedContext(
            context=context,
            content=_read_linked_context_file(source_root, context),
        )
        for context in source.linked_context
        if context.package_state == "packaged"
    ]


def _target_exists(root: Path, relative_path: str) -> bool:
    return os.path.lexists(_path_under(root, relative_path))


def _reject_existing_paths(root: Path, relative_paths: list[str], label: str) -> None:
    for relative_path in relative_paths:
        if _target_exists(root, relative_path):
            raise ValueError(f"{label} target already exists")
        _ensure_no_symlink_parents(root, relative_path, label)


def _ensure_new_targets(source: HandoffPackageWriteSource, package_root: Path) -> None:
    request = source.request
    if _target_exists(package_root, request.package_dir):
        raise ValueError("handoff package target already exists")
    _reject_existing_paths(
        package_root,
        [request.manifest_path]
        + [
            request.actual_package_path(record.primary_data.package_path)
            for record in source.selected_measurements
        ]
        + [
            request.actual_package_path(item.package_path)
            for item in source.linked_context
            if item.package_path is not None
        ],
        "handoff package",
    )


def _remove_created_dirs(root: Path, created_dirs: list[str]) -> None:
    for relative_path in reversed(created_dirs):
        try:
            _path_under(root, relative_path).rmdir()
        except OSError:
            pass


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
    except Exception:
        if created_file:
            try:
                _path_under(root, relative_path).unlink()
            except FileNotFoundError:
                pass
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


def _write_new_files_transaction(
    root: Path,
    files: list[tuple[str, bytes]],
    *,
    label: str,
) -> None:
    _reject_existing_paths(root, [relative_path for relative_path, _content in files], label)
    written_paths: list[str] = []
    created_dirs: list[str] = []
    try:
        for relative_path, content in files:
            created_dirs.extend(_write_new_file(root, relative_path, content, label=label))
            written_paths.append(relative_path)
    except Exception:
        _rollback_written_files(root, written_paths, created_dirs)
        raise


def _manifest_bytes(
    source: HandoffPackageWriteSource,
    copied_sources: list[_CopiedSource],
    copied_contexts: list[_CopiedLinkedContext],
) -> bytes:
    digest_by_id = {
        copied.record.measurement_record_id: _sha256(copied.content) for copied in copied_sources
    }
    size_by_id = {
        copied.record.measurement_record_id: len(copied.content) for copied in copied_sources
    }
    context_digest_by_id = {
        copied.context.link_id: _sha256(copied.content) for copied in copied_contexts
    }
    context_size_by_id = {copied.context.link_id: len(copied.content) for copied in copied_contexts}
    manifest = {
        "package_identity": source.identity.to_manifest(),
        "selected_measurements": [
            record.to_manifest(
                digest=digest_by_id[record.measurement_record_id],
                size=size_by_id[record.measurement_record_id],
            )
            for record in source.selected_measurements
        ],
        "linked_context": [
            item.to_manifest(
                digest=context_digest_by_id.get(item.link_id),
                size=context_size_by_id.get(item.link_id),
            )
            for item in source.linked_context
        ],
    }
    preview_handoff_manifest(manifest)
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _package_contents(source: HandoffPackageWriteSource) -> list[dict[str, Any]]:
    contents = []
    for record in source.selected_measurements:
        item = record.default_bundle[0]
        contents.append(
            {
                "owner_type": "selected_measurement",
                "owner_id": record.measurement_record_id,
                "item_id": item.item_id,
                "kind": item.kind,
                "label": item.label,
                "package_path": item.package_path,
                "include_status": item.include_status,
                "relation": item.relation,
                "authority": item.authority,
                "package_state": item.package_state,
                "reason": item.reason,
            }
        )
    for item in source.linked_context:
        contents.append(
            {
                "owner_type": "linked_context",
                "owner_id": item.link_id,
                "item_id": item.link_id,
                "kind": item.kind,
                "label": item.label,
                "package_path": item.package_path,
                "include_status": item.include_status,
                "relation": item.relation,
                "authority": item.authority,
                "package_state": item.package_state,
                "reason": item.reason,
            }
        )
    return contents


def _write_receipt(
    source: HandoffPackageWriteSource,
    copied_sources: list[_CopiedSource],
    copied_contexts: list[_CopiedLinkedContext],
    manifest_content: bytes,
) -> HandoffPackageWriteReceipt:
    request = source.request
    copied_by_id = {
        copied.record.measurement_record_id: copied.content for copied in copied_sources
    }
    copied_context_by_id = {copied.context.link_id: copied.content for copied in copied_contexts}
    write_results = [
        {
            "path": request.actual_package_path(record.primary_data.package_path),
            "kind": "primary_data",
            "result": "written",
            "bytes_written": len(copied_by_id[record.measurement_record_id]),
            "digest": _sha256(copied_by_id[record.measurement_record_id]),
        }
        for record in source.selected_measurements
    ]
    write_results.extend(
        {
            "path": request.actual_package_path(_linked_context_package_path(context)),
            "kind": "linked_context",
            "result": "written",
            "bytes_written": len(copied_context_by_id[context.link_id]),
            "digest": _sha256(copied_context_by_id[context.link_id]),
        }
        for context in source.linked_context
        if context.package_state == "packaged"
    )
    write_results.append(
        {
            "path": request.manifest_path,
            "kind": "package_manifest",
            "result": "written",
            "bytes_written": len(manifest_content),
            "digest": _sha256(manifest_content),
        }
    )
    selected_measurements = [
        {
            "measurement_record_id": record.measurement_record_id,
            "legacy_data_id": record.legacy_data_id,
            "label": record.label,
            "experiment_type": record.experiment_type,
            "target": record.target,
            "source_path": record.primary_data.source_path,
            "primary_data": {
                "package_path": record.primary_data.package_path,
                "digest": _sha256(copied_by_id[record.measurement_record_id]),
                "size_bytes": len(copied_by_id[record.measurement_record_id]),
                "format": record.primary_data.format,
            },
            "classification": "primary_data_packaged",
        }
        for record in source.selected_measurements
    ]
    return HandoffPackageWriteReceipt(
        package_id=source.identity.package_id,
        display_name=source.identity.display_name,
        source_export_summary_id=source.identity.source_export_summary_id,
        display_path=source.identity.display_path,
        request_id=request.request_id,
        package_dir=request.package_dir,
        manifest_path=request.manifest_path,
        selected_measurements=tuple(selected_measurements),
        package_contents=tuple(_package_contents(source)),
        write_results=tuple(write_results),
    )


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"

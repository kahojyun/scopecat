"""Future archive materialization contract review for handoff packages."""

from __future__ import annotations

import copy
import posixpath
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier, validate_relative_path
from scopecat.handoff.errors import promote_handoff_contract_error
from scopecat.handoff.read_only import open_package

HANDOFF_ARCHIVE_MATERIALIZATION_REVIEW_SCHEMA = "scopecat.handoff_archive_materialization_review.v0"
HANDOFF_ARCHIVE_MATERIALIZATION_POLICY = {
    "archive_implementation": "not_performed",
    "archive_creation": "not_performed",
    "archive_extraction": "not_performed",
    "archive_input_opening": "not_performed",
    "archive_backed_durable_import": "not_performed",
    "archive_bytes_authority": "transport_container_only",
    "package_artifact_of_record": "dec010_directory_manifest_package",
    "canonical_inner_format": "dec010_directory_manifest_package",
    "materialization_authority": "future_safe_staging_review_required",
    "signature_validation": "not_performed",
}
HANDOFF_ARCHIVE_MATERIALIZATION_SCHEMA = "scopecat.handoff_archive_materialization.v0"
HANDOFF_ARCHIVE_PACKAGE_MATERIALIZATION_POLICY = {
    "archive_implementation": "zip_materialization_candidate",
    "archive_creation": "not_performed",
    "archive_extraction": "performed_into_staging_directory",
    "archive_input_opening": "zipfile_read_only",
    "archive_backed_durable_import": "not_performed",
    "archive_bytes_authority": "transport_container_only",
    "package_artifact_of_record": "dec010_directory_manifest_package",
    "canonical_inner_format": "dec010_directory_manifest_package",
    "materialization_authority": "approved_archive_materialization_request",
    "signature_validation": "not_performed",
    "collision_policy": "no_overwrite",
    "failure_cleanup": "remove_partial_materialization",
}
HANDOFF_ARCHIVE_CREATION_SCHEMA = "scopecat.handoff_archive_creation.v0"
HANDOFF_ARCHIVE_PACKAGE_CREATION_POLICY = {
    "archive_implementation": "zip_creation_candidate",
    "archive_creation": "performed_from_dec010_directory_manifest_package",
    "archive_output": "zip_transport_container",
    "archive_extraction": "not_performed",
    "archive_input_opening": "not_performed",
    "archive_backed_durable_import": "not_performed",
    "archive_bytes_authority": "transport_container_only",
    "package_artifact_of_record": "dec010_directory_manifest_package",
    "canonical_inner_format": "dec010_directory_manifest_package",
    "creation_authority": "approved_archive_creation_request",
    "signature_validation": "not_performed",
    "collision_policy": "no_overwrite",
}
REQUIRED_RESOURCE_LIMITS = [
    "archive_size_bytes",
    "extracted_size_bytes",
    "member_count",
    "compression_ratio",
    "extraction_time",
]
DOES_NOT_CLAIM = [
    "archive_creation",
    "archive_extraction",
    "archive_input_opening",
    "archive_backed_durable_import",
    "archive_bytes_as_package_artifact_of_record",
    "signature_or_authenticity_validation",
    "safe_to_extract_archive",
    "package_acceptance",
    "storage_mutation",
]


@dataclass(frozen=True)
class ArchiveMaterializationMemberReview:
    """Review-only classification for one declared archive member candidate."""

    path: str
    member_type: str
    normalized_path: str | None
    blocked_reasons: tuple[str, ...]

    @property
    def classification(self) -> str:
        if self.blocked_reasons:
            return "blocked_archive_member"
        return "review_clean_archive_member"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "member_type": self.member_type,
            "normalized_path": self.normalized_path,
            "classification": self.classification,
            "blocked_reasons": list(self.blocked_reasons),
        }


@dataclass(frozen=True)
class ArchiveMaterializationContractReview:
    """Review-only archive materialization contract candidate."""

    review_id: str
    archive_format: str
    staging_policy: dict[str, str]
    resource_limits: dict[str, str]
    member_reviews: tuple[ArchiveMaterializationMemberReview, ...]

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        reasons.extend(_staging_policy_blockers(self.staging_policy))
        reasons.extend(_resource_limit_blockers(self.resource_limits))
        for member in self.member_reviews:
            reasons.extend(member.blocked_reasons)
        normalized_paths = [
            member.normalized_path
            for member in self.member_reviews
            if member.normalized_path is not None
        ]
        if len(set(normalized_paths)) != len(normalized_paths):
            reasons.append("duplicate_archive_member_path")
        return tuple(dict.fromkeys(reasons))

    @property
    def classification(self) -> str:
        if self.blocked_reasons:
            return "blocked_before_archive_materialization_contract"
        return "review_clean_archive_materialization_contract"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_archive_materialization_contract_review",
            "archive_materialization_policy": copy.deepcopy(HANDOFF_ARCHIVE_MATERIALIZATION_POLICY),
            "review_id": self.review_id,
            "archive_format": self.archive_format,
            "classification": self.classification,
            "staging_policy": copy.deepcopy(self.staging_policy),
            "resource_limits": copy.deepcopy(self.resource_limits),
            "member_reviews": [member.to_dict() for member in self.member_reviews],
            "blocked_reasons": list(self.blocked_reasons),
            "review_state": _review_state(self.blocked_reasons),
            "artifact_authority": {
                "archive_bytes": "transport_container_only",
                "package_of_record": "dec010_directory_manifest_package",
                "opened_package_authority": "materialized_directory_after_future_safe_extraction",
            },
            "does_not_claim": list(DOES_NOT_CLAIM),
        }


@dataclass(frozen=True)
class HandoffArchiveMaterializationRequest:
    """Approved request to materialize a zip archive into a DEC-010 package directory."""

    request_id: str
    approval_state: str
    archive_path: str
    package_dir: str
    collision_policy: str = "no_overwrite"

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "archive materialization request_id")
        if self.approval_state not in {"approved", "rejected", "needs_review"}:
            raise ValueError("archive materialization approval_state is unsupported")
        validate_relative_path(self.archive_path, "archive materialization archive_path")
        validate_public_identifier(self.package_dir, "archive materialization package_dir")
        if self.collision_policy != "no_overwrite":
            raise ValueError("archive materialization collision_policy must be no_overwrite")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    def to_dict(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "archive_path": self.archive_path,
            "package_dir": self.package_dir,
            "collision_policy": self.collision_policy,
        }


@dataclass(frozen=True)
class HandoffArchiveCreationRequest:
    """Approved request to create a zip archive transport from a DEC-010 package."""

    request_id: str
    approval_state: str
    package_dir: str
    archive_path: str
    collision_policy: str = "no_overwrite"

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "archive creation request_id")
        if self.approval_state not in {"approved", "rejected", "needs_review"}:
            raise ValueError("archive creation approval_state is unsupported")
        validate_public_identifier(self.package_dir, "archive creation package_dir")
        validate_relative_path(self.archive_path, "archive creation archive_path")
        if not self.archive_path.endswith(".zip"):
            raise ValueError("archive creation archive_path must end with .zip")
        if self.collision_policy != "no_overwrite":
            raise ValueError("archive creation collision_policy must be no_overwrite")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    def to_dict(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "package_dir": self.package_dir,
            "archive_path": self.archive_path,
            "collision_policy": self.collision_policy,
        }


@dataclass(frozen=True)
class HandoffArchiveCreationRun:
    """Local receipt for creating an archive transport from a package directory."""

    request: HandoffArchiveCreationRequest
    package_root: Path
    archive_root: Path
    archive_path: Path | None = None
    archived_files: tuple[str, ...] = ()
    creation_error: str | None = None

    @property
    def created(self) -> bool:
        return self.classification == "created_zip_transport_archive"

    @property
    def classification(self) -> str:
        if self.creation_error is not None:
            return "blocked_before_archive_creation"
        if not self.request.approved:
            return "blocked_before_archive_creation"
        return "created_zip_transport_archive"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_archive_creation_receipt",
            "archive_creation_schema": HANDOFF_ARCHIVE_CREATION_SCHEMA,
            "archive_creation_policy": copy.deepcopy(HANDOFF_ARCHIVE_PACKAGE_CREATION_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_archive_creation_request",
                    *([] if not self.request.approved else ["open_dec010_package"]),
                    *(
                        []
                        if not self.created
                        else ["review_package_members", "create_zip_transport_archive"]
                    ),
                ],
                "does_not_claim": [
                    "archive_bytes_as_package_artifact_of_record",
                    "archive_extraction",
                    "archive_backed_durable_import",
                    "signature_or_authenticity_validation",
                    "package_acceptance",
                    "storage_mutation",
                ],
            },
            "request": self.request.to_dict(),
            "package": {
                "package_root": str(self.package_root),
                "package_dir": self.request.package_dir,
            },
            "archive": {
                "created": self.created,
                "archive_root": str(self.archive_root),
                "archive_path": None if self.archive_path is None else str(self.archive_path),
                "archived_files": list(self.archived_files),
                "creation_error": self.creation_error,
            },
            "creation_review": {
                "block_reason": _creation_block_reason(self),
                "next_action": _creation_next_action(self),
                "retry_requires": _creation_retry_requirement(self),
            },
            "artifact_authority": {
                "archive_bytes": "transport_container_only",
                "package_of_record": "dec010_directory_manifest_package",
            },
        }


@dataclass(frozen=True)
class HandoffArchiveMaterializationRun:
    """Local receipt for materializing archive transport into a package directory."""

    request: HandoffArchiveMaterializationRequest
    archive_root: Path
    materialization_root: Path
    member_reviews: tuple[ArchiveMaterializationMemberReview, ...] = ()
    package_path: Path | None = None
    materialized_files: tuple[str, ...] = ()
    cleanup_performed: bool = False
    materialization_error: str | None = None

    @property
    def materialized(self) -> bool:
        return self.classification == "materialized_dec010_package_from_archive"

    @property
    def classification(self) -> str:
        if self.materialization_error is not None:
            return "blocked_before_archive_materialization"
        if not self.request.approved:
            return "blocked_before_archive_materialization"
        return "materialized_dec010_package_from_archive"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_archive_materialization_receipt",
            "archive_materialization_schema": HANDOFF_ARCHIVE_MATERIALIZATION_SCHEMA,
            "archive_materialization_policy": copy.deepcopy(
                HANDOFF_ARCHIVE_PACKAGE_MATERIALIZATION_POLICY
            ),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_archive_materialization_request",
                    *([] if not self.request.approved else ["open_zip_archive"]),
                    *([] if not self.member_reviews else ["review_archive_members"]),
                    *(
                        []
                        if not self.materialized
                        else ["materialize_archive_members", "open_materialized_package"]
                    ),
                ],
                "does_not_claim": [
                    "archive_creation",
                    "archive_bytes_as_package_artifact_of_record",
                    "signature_or_authenticity_validation",
                    "package_acceptance",
                    "durable_import",
                    "storage_mutation",
                ],
            },
            "request": self.request.to_dict(),
            "archive": {
                "archive_root": str(self.archive_root),
                "archive_path": self.request.archive_path,
            },
            "materialization": {
                "performed": self.materialized,
                "materialization_root": str(self.materialization_root),
                "package_path": None if self.package_path is None else str(self.package_path),
                "materialized_files": list(self.materialized_files),
                "cleanup_performed": self.cleanup_performed,
                "materialization_error": self.materialization_error,
            },
            "member_reviews": [member.to_dict() for member in self.member_reviews],
            "materialization_review": {
                "block_reason": _materialization_block_reason(self),
                "next_action": _materialization_next_action(self),
                "retry_requires": _materialization_retry_requirement(self),
            },
            "artifact_authority": {
                "archive_bytes": "transport_container_only",
                "package_of_record": "materialized_dec010_directory_manifest_package",
            },
        }


def current_handoff_archive_materialization_contract() -> dict[str, Any]:
    """Return the current DEC-020 archive materialization contract posture."""

    return {
        "artifact_posture": "local_archive_materialization_contract",
        "contract_version": HANDOFF_ARCHIVE_MATERIALIZATION_REVIEW_SCHEMA,
        "archive_materialization_policy": copy.deepcopy(HANDOFF_ARCHIVE_MATERIALIZATION_POLICY),
        "artifact_authority": {
            "current_package_of_record": "dec010_directory_manifest_package",
            "future_archive_bytes": "transport_container_only",
            "future_opened_package": "materialized_dec010_directory_manifest_package",
        },
        "future_materialization_requirements": {
            "staging_directory": "required_unique_empty_scopecat_owned_directory",
            "cleanup": "required_explicit_success_and_failure_policy",
            "overwrite": "no_overwrite_without_new_decision",
            "path_safety": [
                "reject_absolute_member_paths",
                "reject_parent_traversal",
                "reject_duplicate_normalized_member_paths",
                "reject_symlink_members",
                "reject_hidden_metadata_members",
            ],
            "resource_limits": list(REQUIRED_RESOURCE_LIMITS),
            "integrity_timing": [
                "observe_archive_member_contract_before_materialization",
                "open_dec010_manifest_after_materialization",
                "observe_package_integrity_after_package_open",
            ],
            "review_states": [
                "archive_received_for_local_review",
                "blocked_before_archive_materialization_contract",
                "review_clean_archive_materialization_contract",
                "materialized_for_package_open_after_future_safe_extraction",
            ],
        },
        "does_not_claim": list(DOES_NOT_CLAIM),
    }


def review_handoff_archive_materialization_contract(
    source: dict[str, Any],
) -> ArchiveMaterializationContractReview:
    """Review a future archive materialization contract candidate without extraction."""

    try:
        return _review_handoff_archive_materialization_contract(source)
    except ValueError as exc:
        raise promote_handoff_contract_error(
            exc,
            operation="review_handoff_archive_materialization_contract",
        ) from exc


def materialize_handoff_archive_package_from_request(
    request: HandoffArchiveMaterializationRequest,
    *,
    archive_root: str | Path,
    materialization_root: str | Path,
) -> HandoffArchiveMaterializationRun:
    """Materialize a zip archive transport into a DEC-010 package directory."""

    archive_base = _existing_directory_root(
        Path(archive_root),
        "archive materialization archive root",
    )
    materialization_base = _existing_directory_root(
        Path(materialization_root),
        "archive materialization root",
    )
    if not request.approved:
        return HandoffArchiveMaterializationRun(
            request=request,
            archive_root=archive_base,
            materialization_root=materialization_base,
        )
    archive_path = _path_under(
        archive_base,
        request.archive_path,
        "archive materialization archive_path",
    )
    package_path = materialization_base / request.package_dir
    member_reviews: tuple[ArchiveMaterializationMemberReview, ...] = ()
    try:
        _validate_archive_file(archive_path)
        _validate_materialization_target(package_path)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            member_reviews = tuple(_review_zip_member(member) for member in members)
            _validate_zip_members_for_materialization(
                request,
                member_reviews,
                members,
            )
            materialized_files = _materialize_zip_members(
                archive,
                members,
                materialization_base,
            )
        open_package(package_path)
    except (
        KeyError,
        NotImplementedError,
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        cleanup_performed = _cleanup_partial_package(package_path)
        return HandoffArchiveMaterializationRun(
            request=request,
            archive_root=archive_base,
            materialization_root=materialization_base,
            member_reviews=member_reviews,
            package_path=package_path,
            cleanup_performed=cleanup_performed,
            materialization_error=str(exc),
        )

    return HandoffArchiveMaterializationRun(
        request=request,
        archive_root=archive_base,
        materialization_root=materialization_base,
        member_reviews=member_reviews,
        package_path=package_path,
        materialized_files=tuple(materialized_files),
    )


def materialize_handoff_archive_package(
    source: dict[str, Any],
    *,
    archive_root: str | Path,
    materialization_root: str | Path,
) -> HandoffArchiveMaterializationRun:
    """Materialize a zip archive package from a raw route-local source."""

    request = _parse_materialization_source(source)
    return materialize_handoff_archive_package_from_request(
        request,
        archive_root=archive_root,
        materialization_root=materialization_root,
    )


def create_handoff_archive_package_from_request(
    request: HandoffArchiveCreationRequest,
    *,
    package_root: str | Path,
    archive_root: str | Path,
) -> HandoffArchiveCreationRun:
    """Create a zip transport archive from a DEC-010 package directory."""

    package_base = _existing_directory_root(Path(package_root), "archive creation package root")
    archive_base = _existing_directory_root(Path(archive_root), "archive creation archive root")
    if not request.approved:
        return HandoffArchiveCreationRun(
            request=request,
            package_root=package_base,
            archive_root=archive_base,
        )
    package_path = package_base / request.package_dir
    archive_path = _path_under(archive_base, request.archive_path, "archive creation archive_path")
    try:
        if archive_path.exists() or archive_path.is_symlink():
            raise ValueError("archive creation archive target already exists")
        package = open_package(package_path)
        package_members = _collect_package_files(package_path, package.package_id)
        _write_zip_archive(archive_path, package_members)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        _cleanup_partial_archive(archive_path)
        return HandoffArchiveCreationRun(
            request=request,
            package_root=package_base,
            archive_root=archive_base,
            archive_path=archive_path,
            creation_error=str(exc),
        )

    return HandoffArchiveCreationRun(
        request=request,
        package_root=package_base,
        archive_root=archive_base,
        archive_path=archive_path,
        archived_files=tuple(relative_path for relative_path, _ in package_members),
    )


def create_handoff_archive_package(
    source: dict[str, Any],
    *,
    package_root: str | Path,
    archive_root: str | Path,
) -> HandoffArchiveCreationRun:
    """Create a zip archive package from a raw route-local source."""

    request = _parse_creation_source(source)
    return create_handoff_archive_package_from_request(
        request,
        package_root=package_root,
        archive_root=archive_root,
    )


def _review_handoff_archive_materialization_contract(
    source: dict[str, Any],
) -> ArchiveMaterializationContractReview:
    source = _require_mapping(source, "archive materialization review source")
    _require_keys(
        source,
        {
            "archive_materialization_review_schema",
            "archive_materialization_policy",
            "review_id",
            "archive_format",
            "staging_policy",
            "resource_limits",
            "members",
        },
        "archive materialization review source",
    )
    if (
        source["archive_materialization_review_schema"]
        != HANDOFF_ARCHIVE_MATERIALIZATION_REVIEW_SCHEMA
    ):
        raise ValueError("archive_materialization_review_schema is unsupported")
    if source["archive_materialization_policy"] != HANDOFF_ARCHIVE_MATERIALIZATION_POLICY:
        raise ValueError("archive_materialization_policy is unsupported")
    review_id = validate_public_identifier(source["review_id"], "archive review_id")
    archive_format = validate_public_identifier(source["archive_format"], "archive_format")
    staging_policy = _parse_string_mapping(source["staging_policy"], "staging_policy")
    resource_limits = _parse_resource_limits(source["resource_limits"])
    members = _parse_members(source["members"])
    return ArchiveMaterializationContractReview(
        review_id=review_id,
        archive_format=archive_format,
        staging_policy=staging_policy,
        resource_limits=resource_limits,
        member_reviews=members,
    )


def _parse_creation_source(source: dict[str, Any]) -> HandoffArchiveCreationRequest:
    source = _require_mapping(source, "archive creation source")
    _require_keys(
        source,
        {
            "archive_creation_schema",
            "archive_creation_policy",
            "archive_creation_request",
        },
        "archive creation source",
    )
    if source["archive_creation_schema"] != HANDOFF_ARCHIVE_CREATION_SCHEMA:
        raise ValueError("archive_creation_schema is unsupported")
    if source["archive_creation_policy"] != HANDOFF_ARCHIVE_PACKAGE_CREATION_POLICY:
        raise ValueError("archive_creation_policy is unsupported")
    request = _require_mapping(
        source["archive_creation_request"],
        "archive_creation_request",
    )
    return HandoffArchiveCreationRequest(
        request_id=_read_text(request, "request_id", "archive creation request_id"),
        approval_state=_read_text(request, "approval_state", "archive creation approval_state"),
        package_dir=_read_text(request, "package_dir", "archive creation package_dir"),
        archive_path=_read_text(request, "archive_path", "archive creation archive_path"),
        collision_policy=_read_text(
            request,
            "collision_policy",
            "archive creation collision_policy",
        ),
    )


def _parse_materialization_source(source: dict[str, Any]) -> HandoffArchiveMaterializationRequest:
    source = _require_mapping(source, "archive materialization source")
    _require_keys(
        source,
        {
            "archive_materialization_schema",
            "archive_materialization_policy",
            "archive_materialization_request",
        },
        "archive materialization source",
    )
    if source["archive_materialization_schema"] != HANDOFF_ARCHIVE_MATERIALIZATION_SCHEMA:
        raise ValueError("archive_materialization_schema is unsupported")
    if source["archive_materialization_policy"] != HANDOFF_ARCHIVE_PACKAGE_MATERIALIZATION_POLICY:
        raise ValueError("archive_materialization_policy is unsupported")
    request = _require_mapping(
        source["archive_materialization_request"],
        "archive_materialization_request",
    )
    return HandoffArchiveMaterializationRequest(
        request_id=_read_text(request, "request_id", "archive materialization request_id"),
        approval_state=_read_text(
            request,
            "approval_state",
            "archive materialization approval_state",
        ),
        archive_path=_read_text(request, "archive_path", "archive materialization archive_path"),
        package_dir=_read_text(request, "package_dir", "archive materialization package_dir"),
        collision_policy=_read_text(
            request,
            "collision_policy",
            "archive materialization collision_policy",
        ),
    )


def _review_zip_member(member: zipfile.ZipInfo) -> ArchiveMaterializationMemberReview:
    member_type = _zip_member_type(member)
    normalized_path, path_reasons = _normalize_archive_member_path(member.filename)
    metadata_reasons = _metadata_path_blockers(normalized_path)
    type_reasons = _member_type_blockers(member_type)
    return ArchiveMaterializationMemberReview(
        path=member.filename,
        member_type=member_type,
        normalized_path=normalized_path,
        blocked_reasons=tuple([*path_reasons, *metadata_reasons, *type_reasons]),
    )


def _zip_member_type(member: zipfile.ZipInfo) -> str:
    mode = member.external_attr >> 16
    if stat.S_ISLNK(mode):
        return "symlink"
    if member.is_dir():
        return "directory"
    return "regular_file"


def _validate_zip_members_for_materialization(
    request: HandoffArchiveMaterializationRequest,
    reviews: tuple[ArchiveMaterializationMemberReview, ...],
    members: list[zipfile.ZipInfo],
) -> None:
    if not members:
        raise ValueError("archive materialization archive must contain package members")
    blocked_reasons = [reason for review in reviews for reason in review.blocked_reasons]
    if blocked_reasons:
        raise ValueError(
            "archive materialization member review blocked: "
            + ", ".join(tuple(dict.fromkeys(blocked_reasons)))
        )
    normalized_paths = [
        review.normalized_path for review in reviews if review.normalized_path is not None
    ]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise ValueError("archive materialization duplicate archive member path")
    package_prefix = f"{request.package_dir}/"
    if any(path is None or not path.startswith(package_prefix) for path in normalized_paths):
        raise ValueError("archive materialization members must stay under package_dir")
    if f"{request.package_dir}/package-manifest.json" not in normalized_paths:
        raise ValueError("archive materialization package-manifest.json is required")


def _collect_package_files(package_path: Path, package_id: str) -> list[tuple[str, Path]]:
    package_root = package_path.resolve()
    members: list[tuple[str, Path]] = []
    for path in sorted(package_root.rglob("*")):
        if path.is_symlink():
            raise ValueError("archive creation package member must not be a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("archive creation package member must be a regular file")
        relative = path.relative_to(package_root).as_posix()
        archive_member = f"{package_id}/{relative}"
        normalized, reasons = _normalize_archive_member_path(archive_member)
        if normalized is None or reasons:
            raise ValueError("archive creation package member path is unsafe")
        if _metadata_path_blockers(normalized):
            raise ValueError("archive creation package member metadata path is not allowed")
        members.append((normalized, path))
    if not members:
        raise ValueError("archive creation package must contain package members")
    member_paths = [relative_path for relative_path, _ in members]
    if len(set(member_paths)) != len(member_paths):
        raise ValueError("archive creation duplicate archive member path")
    if f"{package_id}/package-manifest.json" not in member_paths:
        raise ValueError("archive creation package-manifest.json is required")
    return members


def _write_zip_archive(archive_path: Path, members: list[tuple[str, Path]]) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.parent.is_symlink():
        raise ValueError("archive creation archive parent must not be a symlink")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path, source_path in members:
            archive.write(source_path, arcname=relative_path)


def _materialize_zip_members(
    archive: zipfile.ZipFile,
    members: list[zipfile.ZipInfo],
    materialization_root: Path,
) -> list[str]:
    materialized_files: list[str] = []
    for member in members:
        normalized, reasons = _normalize_archive_member_path(member.filename)
        if normalized is None or reasons:
            raise ValueError("archive materialization member path is unsafe")
        target = _path_under(materialization_root, normalized, "archive materialization member")
        _ensure_materialization_parent(materialization_root, normalized)
        if target.exists():
            raise ValueError("archive materialization member target already exists")
        with archive.open(member, "r") as source, target.open("xb") as destination:
            shutil.copyfileobj(source, destination)
        materialized_files.append(normalized)
    return materialized_files


def _validate_archive_file(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("archive materialization archive_path must not be a symlink")
    if not path.is_file():
        raise ValueError("archive materialization archive_path must be an existing file")
    if not zipfile.is_zipfile(path):
        raise ValueError("archive materialization archive_path must be a zip archive")


def _validate_materialization_target(package_path: Path) -> None:
    if package_path.is_symlink():
        raise ValueError("archive materialization package target must not be a symlink")
    if package_path.exists():
        raise ValueError("archive materialization package target already exists")


def _ensure_materialization_parent(root: Path, relative_path: str) -> None:
    parts = relative_path.replace("\\", "/").split("/")[:-1]
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("archive materialization member parent must not be a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("archive materialization member parent must be a directory")
    parent = root.joinpath(*parts)
    if parent.exists() and not parent.is_dir():
        raise ValueError("archive materialization member parent must be a directory")
    parent.mkdir(parents=True, exist_ok=True)


def _cleanup_partial_package(package_path: Path) -> bool:
    if not package_path.exists():
        return False
    if package_path.is_symlink():
        raise ValueError("archive materialization cleanup target must not be a symlink")
    shutil.rmtree(package_path)
    return True


def _cleanup_partial_archive(archive_path: Path) -> bool:
    if not archive_path.exists() and not archive_path.is_symlink():
        return False
    if archive_path.is_symlink():
        return False
    if archive_path.is_file():
        archive_path.unlink()
        return True
    return False


def _creation_block_reason(run: HandoffArchiveCreationRun) -> str | None:
    if run.created:
        return None
    if not run.request.approved:
        return "request_not_approved"
    if run.creation_error is not None:
        if "target already exists" in run.creation_error:
            return "archive_destination_collision"
        if "symlink" in run.creation_error:
            return "archive_creation_symlink_blocked"
        if "metadata path" in run.creation_error:
            return "archive_creation_metadata_member_blocked"
        if "package-manifest.json" in run.creation_error:
            return "missing_package_manifest"
        return "archive_creation_error"
    return "archive_creation_not_performed"


def _creation_next_action(run: HandoffArchiveCreationRun) -> str:
    block_reason = _creation_block_reason(run)
    if block_reason is None:
        return "transfer_zip_archive_to_receiving_side"
    if block_reason == "request_not_approved":
        return "approve_archive_creation_request"
    if block_reason == "archive_destination_collision":
        return "choose_unused_archive_path_before_retry"
    if block_reason in {
        "archive_creation_symlink_blocked",
        "archive_creation_metadata_member_blocked",
        "missing_package_manifest",
    }:
        return "provide_openable_dec010_package_before_retry"
    return "review_archive_creation_error_before_retry"


def _creation_retry_requirement(run: HandoffArchiveCreationRun) -> str | None:
    block_reason = _creation_block_reason(run)
    if block_reason is None:
        return None
    if block_reason == "request_not_approved":
        return "approved_archive_creation_request"
    if block_reason == "archive_destination_collision":
        return "unused_archive_destination"
    return "openable_dec010_package_and_reviewed_archive_creation_request"


def _materialization_block_reason(run: HandoffArchiveMaterializationRun) -> str | None:
    if run.materialized:
        return None
    if not run.request.approved:
        return "request_not_approved"
    if run.materialization_error is not None:
        if "target already exists" in run.materialization_error:
            return "package_destination_collision"
        if "member review blocked" in run.materialization_error:
            return "archive_member_review_blocked"
        if "package-manifest.json is required" in run.materialization_error:
            return "missing_package_manifest"
        if "must stay under package_dir" in run.materialization_error:
            return "archive_member_scope_violation"
        if "zip archive" in run.materialization_error:
            return "unsupported_archive_input"
        return "archive_materialization_error"
    return "archive_materialization_not_performed"


def _materialization_next_action(run: HandoffArchiveMaterializationRun) -> str:
    block_reason = _materialization_block_reason(run)
    if block_reason is None:
        return "open_materialized_package_for_receiving_review"
    if block_reason == "request_not_approved":
        return "approve_archive_materialization_request"
    if block_reason == "package_destination_collision":
        return "choose_empty_materialization_destination_before_retry"
    if block_reason in {
        "archive_member_review_blocked",
        "archive_member_scope_violation",
        "missing_package_manifest",
        "unsupported_archive_input",
    }:
        return "provide_safe_dec010_archive_before_retry"
    return "review_archive_materialization_error_before_retry"


def _materialization_retry_requirement(run: HandoffArchiveMaterializationRun) -> str | None:
    block_reason = _materialization_block_reason(run)
    if block_reason is None:
        return None
    if block_reason == "request_not_approved":
        return "approved_archive_materialization_request"
    if block_reason == "package_destination_collision":
        return "fresh_empty_materialization_destination"
    if block_reason in {
        "archive_member_review_blocked",
        "archive_member_scope_violation",
        "missing_package_manifest",
        "unsupported_archive_input",
    }:
        return "safe_zip_archive_with_dec010_package_members"
    return "reviewed_archive_materialization_input_correction"


def _existing_directory_root(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    if not path.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return path.resolve()


def _path_under(root: Path, relative_path: str, label: str) -> Path:
    validate_relative_path(relative_path, label)
    candidate = root.joinpath(*relative_path.replace("\\", "/").split("/")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"{label} must stay under root")
    return candidate


def _parse_members(value: Any) -> tuple[ArchiveMaterializationMemberReview, ...]:
    if not isinstance(value, list):
        raise ValueError("archive materialization members must be a list")
    if not value:
        raise ValueError("archive materialization members must not be empty")
    return tuple(_parse_member(item) for item in value)


def _parse_member(value: Any) -> ArchiveMaterializationMemberReview:
    member = _require_mapping(value, "archive materialization member")
    _require_keys(member, {"path", "member_type"}, "archive materialization member")
    path = _read_text(member, "path", "archive materialization member.path")
    member_type = validate_public_identifier(
        member["member_type"],
        "archive materialization member.member_type",
    )
    normalized_path, path_reasons = _normalize_archive_member_path(path)
    metadata_reasons = _metadata_path_blockers(normalized_path)
    type_reasons = _member_type_blockers(member_type)
    return ArchiveMaterializationMemberReview(
        path=path,
        member_type=member_type,
        normalized_path=normalized_path,
        blocked_reasons=tuple([*path_reasons, *metadata_reasons, *type_reasons]),
    )


def _normalize_archive_member_path(path: str) -> tuple[str | None, list[str]]:
    reasons: list[str] = []
    if path.startswith("/") or path.startswith("\\") or _looks_like_windows_absolute_path(path):
        reasons.append("absolute_archive_member_path")
    normalized = posixpath.normpath(path.replace("\\", "/"))
    parts = normalized.split("/")
    if normalized in {"", "."}:
        reasons.append("empty_archive_member_path")
    if ".." in parts:
        reasons.append("parent_traversal_archive_member_path")
    if any(part == "" for part in parts):
        reasons.append("empty_archive_member_path_part")
    if reasons:
        return None, reasons
    return normalized, []


def _looks_like_windows_absolute_path(path: str) -> bool:
    return len(path) >= 3 and path[1] == ":" and path[2] in {"/", "\\"}


def _metadata_path_blockers(normalized_path: str | None) -> list[str]:
    if normalized_path is None:
        return []
    parts = normalized_path.split("/")
    if parts[0] == "__MACOSX" or any(part == ".DS_Store" for part in parts):
        return ["metadata_archive_member_not_allowed"]
    return []


def _member_type_blockers(member_type: str) -> list[str]:
    if member_type == "regular_file":
        return []
    if member_type == "directory":
        return ["directory_archive_member_requires_explicit_policy"]
    if member_type == "symlink":
        return ["symlink_archive_member_not_allowed"]
    if member_type in {"metadata", "hidden_metadata"}:
        return ["metadata_archive_member_not_allowed"]
    return ["unsupported_archive_member_type"]


def _staging_policy_blockers(policy: dict[str, str]) -> list[str]:
    required = {
        "staging_directory": "required_unique_empty_scopecat_owned_directory",
        "overwrite": "no_overwrite",
        "cleanup": "explicit_success_and_failure_cleanup_required",
    }
    return [
        f"{key}_policy_required"
        for key, expected in required.items()
        if policy.get(key) != expected
    ]


def _resource_limit_blockers(limits: dict[str, str]) -> list[str]:
    return [
        f"{key}_limit_required"
        for key in REQUIRED_RESOURCE_LIMITS
        if limits.get(key) != "required_before_archive_materialization"
    ]


def _review_state(blocked_reasons: tuple[str, ...]) -> dict[str, str | list[str] | None]:
    if blocked_reasons:
        return {
            "block_reason": "archive_materialization_contract_not_ready",
            "blocked_reasons": list(blocked_reasons),
            "next_action": "resolve_archive_materialization_contract_before_implementation",
            "retry_requires": "fresh_archive_materialization_contract_review",
        }
    return {
        "block_reason": None,
        "blocked_reasons": [],
        "next_action": "decide_whether_archive_transport_workflow_justifies_implementation",
        "retry_requires": None,
    }


def _parse_string_mapping(value: Any, owner: str) -> dict[str, str]:
    mapping = _require_mapping(value, owner)
    result: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise ValueError(f"{owner} keys must be strings")
        if not isinstance(item, str):
            raise ValueError(f"{owner}.{key} must be a string")
        result[key] = item
    return result


def _parse_resource_limits(value: Any) -> dict[str, str]:
    limits = _parse_string_mapping(value, "resource_limits")
    for key in REQUIRED_RESOURCE_LIMITS:
        if key in limits:
            validate_public_identifier(limits[key], f"resource_limits.{key}")
    return limits


def _read_text(source: dict[str, Any], key: str, owner: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner} must be a non-empty string")
    return value


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")

"""Zip archive transport creation and materialization for handoff packages."""

from __future__ import annotations

import posixpath
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier, validate_relative_path
from scopecat.handoff.read_only import open_package


@dataclass(frozen=True)
class ArchiveMaterializationMemberReview:
    """Review-only classification for one declared archive member."""

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
            },
        }


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
        return ["directory_archive_member_not_allowed"]
    if member_type == "symlink":
        return ["symlink_archive_member_not_allowed"]
    if member_type in {"metadata", "hidden_metadata"}:
        return ["metadata_archive_member_not_allowed"]
    return ["unsupported_archive_member_type"]

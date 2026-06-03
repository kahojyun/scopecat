"""Read-only integrity observation for directory-shaped handoff packages."""

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
    validate_positive_integer,
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
)
from scopecat.handoff._manifest_preview import preview_handoff_manifest

_MANIFEST_NAME = "package-manifest.json"
_HASH_CHUNK_SIZE = 1024 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_EXPECTED_POLICY = {
    "observation_authority": "caller_provided_package_directory",
    "manifest_name": _MANIFEST_NAME,
    "manifest_preview": "scopecat_export_manifest_contract_reused",
    "file_observation": "package_local_declared_members",
    "checksum_algorithm": "sha256",
    "size_observation": "byte_count",
    "archive_extraction": "not_performed",
    "external_authenticity_validation": "not_performed",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "schema_inference": "not_performed",
    "gui_workflow": "not_defined",
}


@dataclass(frozen=True)
class HandoffIntegrityOwnerRef:
    """Manifest owner reference for one observed package member."""

    owner_type: str
    owner_id: str
    item_id: str
    kind: str

    def to_dict(self) -> dict[str, str]:
        return {
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "item_id": self.item_id,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class _DeclaredMember:
    package_path: str
    owner_refs: tuple[HandoffIntegrityOwnerRef, ...]
    declared_digest: str | None = None
    declared_size_bytes: int | None = None


@dataclass(frozen=True)
class HandoffIntegrityMemberObservation:
    """Local integrity observation for one declared package member."""

    package_path: str
    owner_refs: tuple[HandoffIntegrityOwnerRef, ...]
    observation_state: str
    comparison: str
    mismatches: tuple[str, ...]
    declared_digest: str | None = None
    declared_size_bytes: int | None = None
    observed_digest: str | None = None
    observed_size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "package_path": self.package_path,
            "owner_refs": [owner.to_dict() for owner in self.owner_refs],
            "declared_digest": self.declared_digest,
            "declared_size_bytes": self.declared_size_bytes,
            "observation_state": self.observation_state,
            "comparison": self.comparison,
            "mismatches": list(self.mismatches),
        }
        if self.observed_digest is not None:
            result["observed_digest"] = self.observed_digest
        if self.observed_size_bytes is not None:
            result["observed_size_bytes"] = self.observed_size_bytes
        return result


@dataclass(frozen=True)
class HandoffPackageIntegrityReport:
    """Read-only package integrity report for receiving/import gating."""

    package_id: str
    display_name: str
    preview_classification: str
    classification: str
    member_observations: tuple[HandoffIntegrityMemberObservation, ...]
    integrity_findings: tuple[dict[str, Any], ...]

    @property
    def member_count(self) -> int:
        return len(self.member_observations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_review_summary",
            "integrity_observation_policy": copy.deepcopy(_EXPECTED_POLICY),
            "classification": self.classification,
            "package": {
                "package_id": self.package_id,
                "display_name": self.display_name,
                "preview_classification": self.preview_classification,
            },
            "member_count": self.member_count,
            "member_observations": [
                observation.to_dict() for observation in self.member_observations
            ],
            "integrity_findings": [copy.deepcopy(finding) for finding in self.integrity_findings],
            "attention": _attention(self.classification),
        }


def observe_package_integrity(package_dir: str | Path) -> HandoffPackageIntegrityReport:
    """Observe declared package-local member integrity without import or mutation."""

    package_root = _existing_package_dir(Path(package_dir))
    manifest = _load_manifest(package_root)
    preview = preview_handoff_manifest(manifest)
    _validate_package_dir_identity(package_root, preview.package_id)
    members = _declared_members(manifest)
    observations = tuple(_observe_member(package_root, member) for member in members)
    classification = _classification(observations)
    findings = tuple(_findings(observations))
    return HandoffPackageIntegrityReport(
        package_id=preview.package_id,
        display_name=preview.display_name,
        preview_classification=preview.classification,
        classification=classification,
        member_observations=observations,
        integrity_findings=findings,
    )


def _existing_package_dir(package_dir: Path) -> Path:
    if package_dir.is_symlink():
        raise ValueError("handoff package integrity package directory must not be a symlink")
    if not package_dir.is_dir():
        raise ValueError("handoff package integrity requires an existing package directory")
    return package_dir.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*relative_path_parts(relative_path, "handoff package member path"))


def _member_path_state(package_dir: Path, relative_path: str) -> tuple[str, Path | None]:
    current = package_dir
    for part in relative_path_parts(relative_path, "handoff package member path")[:-1]:
        current = current / part
        if current.is_symlink():
            return "blocked_symlink_parent", None
        if current.exists() and not current.is_dir():
            return "blocked_non_directory_parent", None

    target = _path_under(package_dir, relative_path)
    if target.is_symlink():
        return "blocked_symlink_file", None
    try:
        target_stat = target.lstat()
    except (FileNotFoundError, OSError):
        return "unavailable", None
    if not stat.S_ISREG(target_stat.st_mode):
        return "blocked_non_regular_file", None
    return "observed", target


def _open_regular_member(target: Path) -> tuple[str, int | None]:
    try:
        file_fd = os.open(target, os.O_RDONLY | _NOFOLLOW | _NONBLOCK)
    except (FileNotFoundError, OSError):
        return "unavailable", None
    file_stat = os.fstat(file_fd)
    if not stat.S_ISREG(file_stat.st_mode):
        os.close(file_fd)
        return "blocked_non_regular_file", None
    return "observed", file_fd


def _read_regular_member(package_dir: Path, relative_path: str) -> tuple[str, bytes | None]:
    state, target = _member_path_state(package_dir, relative_path)
    if state != "observed" or target is None:
        return state, None
    state, file_fd = _open_regular_member(target)
    if state != "observed" or file_fd is None:
        return state, None
    with os.fdopen(file_fd, "rb") as handle:
        return "observed", handle.read()


def _load_manifest(package_dir: Path) -> dict[str, Any]:
    state, content = _read_regular_member(package_dir, _MANIFEST_NAME)
    if state != "observed" or content is None:
        raise ValueError("handoff package manifest is unavailable")
    try:
        manifest = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("handoff package manifest must be valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("handoff package manifest must be a JSON object")
    return manifest


def _validate_package_dir_identity(package_dir: Path, package_id: str) -> None:
    validate_public_identifier(package_id, "handoff package package_id")
    if package_dir.name != package_id:
        raise ValueError("handoff package directory name must match package_id")


def _declared_integrity(item: dict[str, Any], *, owner: str) -> tuple[str | None, int | None]:
    has_digest = "digest" in item
    has_size = "size_bytes" in item
    if has_digest != has_size:
        raise ValueError(f"{owner} digest and size_bytes must be declared together")
    if not has_digest:
        return None, None
    return (
        validate_sha256_digest(item["digest"], f"{owner} digest"),
        validate_positive_integer(item["size_bytes"], f"{owner} size_bytes"),
    )


def _owner_ref(
    *, owner_type: str, owner_id: str, item_id: str, kind: str
) -> HandoffIntegrityOwnerRef:
    return HandoffIntegrityOwnerRef(
        owner_type=owner_type,
        owner_id=validate_public_identifier(owner_id, f"{owner_type} owner_id"),
        item_id=validate_public_identifier(item_id, f"{owner_type} item_id"),
        kind=validate_public_identifier(kind, f"{owner_type} kind"),
    )


def _merge_member(
    members_by_path: dict[str, dict[str, Any]],
    *,
    package_path: str,
    owner_ref: HandoffIntegrityOwnerRef,
    declared_digest: str | None,
    declared_size_bytes: int | None,
) -> None:
    path = validate_relative_path(package_path, "handoff package member")
    member = members_by_path.setdefault(
        path,
        {
            "package_path": path,
            "owner_refs": [],
            "declared_digest": declared_digest,
            "declared_size_bytes": declared_size_bytes,
        },
    )
    member["owner_refs"].append(owner_ref)
    if declared_digest is not None:
        if member.get("declared_digest") not in {None, declared_digest}:
            raise ValueError("conflicting package member declared digest")
        member["declared_digest"] = declared_digest
    if declared_size_bytes is not None:
        if member.get("declared_size_bytes") not in {None, declared_size_bytes}:
            raise ValueError("conflicting package member declared size_bytes")
        member["declared_size_bytes"] = declared_size_bytes


def _declared_members(manifest: dict[str, Any]) -> tuple[_DeclaredMember, ...]:
    members_by_path: dict[str, dict[str, Any]] = {}
    for record in manifest["selected_measurements"]:
        measurement_id = record["measurement_record_id"]
        primary = record["primary_data"]
        declared_digest, declared_size_bytes = _declared_integrity(
            primary,
            owner=f"selected measurement {measurement_id} primary data",
        )
        _merge_member(
            members_by_path,
            package_path=primary["package_path"],
            owner_ref=_owner_ref(
                owner_type="selected_measurement",
                owner_id=measurement_id,
                item_id="primary_data",
                kind=primary["kind"],
            ),
            declared_digest=declared_digest,
            declared_size_bytes=declared_size_bytes,
        )
        for item in record["default_bundle"]:
            package_path = item.get("package_path")
            if not package_path:
                continue
            declared_digest, declared_size_bytes = _declared_integrity(
                item,
                owner=f"default bundle item {item['item_id']}",
            )
            _merge_member(
                members_by_path,
                package_path=package_path,
                owner_ref=_owner_ref(
                    owner_type="default_bundle",
                    owner_id=measurement_id,
                    item_id=item["item_id"],
                    kind=item["kind"],
                ),
                declared_digest=declared_digest,
                declared_size_bytes=declared_size_bytes,
            )

    for item in manifest["linked_context"]:
        package_path = item.get("package_path")
        if not package_path:
            continue
        declared_digest, declared_size_bytes = _declared_integrity(
            item,
            owner=f"linked context {item['link_id']}",
        )
        _merge_member(
            members_by_path,
            package_path=package_path,
            owner_ref=_owner_ref(
                owner_type="linked_context",
                owner_id=item["link_id"],
                item_id=item["link_id"],
                kind=item["kind"],
            ),
            declared_digest=declared_digest,
            declared_size_bytes=declared_size_bytes,
        )

    return tuple(
        _DeclaredMember(
            package_path=item["package_path"],
            owner_refs=tuple(item["owner_refs"]),
            declared_digest=item["declared_digest"],
            declared_size_bytes=item["declared_size_bytes"],
        )
        for item in (members_by_path[path] for path in sorted(members_by_path))
    )


def _observe_regular_member(package_dir: Path, relative_path: str) -> dict[str, Any]:
    state, target = _member_path_state(package_dir, relative_path)
    if state != "observed" or target is None:
        return {
            "observation_state": state,
            "comparison": "not_observed",
            "mismatches": (),
        }
    state, file_fd = _open_regular_member(target)
    if state != "observed" or file_fd is None:
        return {
            "observation_state": state,
            "comparison": "not_observed",
            "mismatches": (),
        }

    digest = hashlib.sha256()
    observed_size_bytes = 0
    with os.fdopen(file_fd, "rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            observed_size_bytes += len(chunk)
            digest.update(chunk)
    return {
        "observation_state": "observed",
        "comparison": "not_observed",
        "mismatches": (),
        "observed_digest": f"sha256:{digest.hexdigest()}",
        "observed_size_bytes": observed_size_bytes,
    }


def _observe_member(
    package_dir: Path, member: _DeclaredMember
) -> HandoffIntegrityMemberObservation:
    observed = _observe_regular_member(package_dir, member.package_path)
    observation_state = observed["observation_state"]
    comparison = observed["comparison"]
    mismatches: tuple[str, ...] = ()
    if observation_state == "observed":
        if member.declared_digest is None or member.declared_size_bytes is None:
            comparison = "not_declared"
        else:
            mismatch_list = []
            if observed["observed_digest"] != member.declared_digest:
                mismatch_list.append("digest")
            if observed["observed_size_bytes"] != member.declared_size_bytes:
                mismatch_list.append("size_bytes")
            mismatches = tuple(mismatch_list)
            comparison = "verified" if not mismatches else "mismatch"

    return HandoffIntegrityMemberObservation(
        package_path=member.package_path,
        owner_refs=member.owner_refs,
        declared_digest=member.declared_digest,
        declared_size_bytes=member.declared_size_bytes,
        observation_state=observation_state,
        comparison=comparison,
        mismatches=mismatches,
        observed_digest=observed.get("observed_digest"),
        observed_size_bytes=observed.get("observed_size_bytes"),
    )


def _findings(
    member_observations: tuple[HandoffIntegrityMemberObservation, ...],
) -> list[dict[str, Any]]:
    findings = []
    for member in member_observations:
        if member.comparison == "verified":
            continue
        if member.comparison == "mismatch":
            findings.append(
                {
                    "subject_type": "package_member",
                    "subject_id": member.package_path,
                    "severity": "error",
                    "finding": "declared_integrity_mismatch",
                    "basis": "Observed package-local bytes do not match declared digest or size.",
                    "mismatches": list(member.mismatches),
                    "does_not_claim": "authenticity_or_external_validation_failure",
                }
            )
            continue
        if member.comparison == "not_declared" and member.observation_state == "observed":
            findings.append(
                {
                    "subject_type": "package_member",
                    "subject_id": member.package_path,
                    "severity": "review",
                    "finding": "declared_integrity_not_available",
                    "basis": "The member was observed, but no paired digest and size facts were declared for comparison.",
                    "does_not_claim": "member_corruption_or_validity",
                }
            )
            continue
        findings.append(
            {
                "subject_type": "package_member",
                "subject_id": member.package_path,
                "severity": "error" if member.observation_state == "unavailable" else "review",
                "finding": member.observation_state,
                "basis": "The member could not be read as a regular package-local file.",
                "does_not_claim": "schema_or_payload_validity",
            }
        )
    return findings


def _classification(member_observations: tuple[HandoffIntegrityMemberObservation, ...]) -> str:
    comparisons = {member.comparison for member in member_observations}
    states = {member.observation_state for member in member_observations}
    if "mismatch" in comparisons or "unavailable" in states:
        return "integrity_review_required"
    if any(state.startswith("blocked_") for state in states):
        return "integrity_review_required"
    if comparisons == {"verified"}:
        return "declared_integrity_verified"
    if "not_declared" in comparisons:
        return "integrity_observed_with_undeclared_members"
    return "integrity_not_observed"


def _attention(classification: str) -> list[dict[str, str]]:
    return [
        {
            "code": "package_integrity_observed",
            "severity": "info" if classification == "declared_integrity_verified" else "review",
            "basis": "Package-local files were compared to paired manifest-declared digest and size facts where available.",
            "does_not_claim": "external_authenticity_or_trust_validation",
        },
        {
            "code": "receiving_acceptance_not_performed",
            "severity": "review",
            "basis": "Integrity observation is read-only and does not import, accept, or mutate storage.",
            "does_not_claim": "package_import_or_storage_acceptance",
        },
    ]

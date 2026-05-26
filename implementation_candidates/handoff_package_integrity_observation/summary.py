"""Read-only integrity observation for directory-shaped handoff packages.

This candidate compares package-local files to manifest-declared size and
digest facts where present. It deliberately does not accept/import packages,
mutate storage, extract archives, validate signatures, infer schemas, or claim
authenticity.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts,
    validate_positive_integer,
    validate_public_identifier,
    validate_sha256_digest,
)
from implementation_candidates.handoff_package_contents_preview import (
    build_handoff_package_contents_preview_summary,
)

_MANIFEST_NAME = "package-manifest.json"
_EXPECTED_POLICY = {
    "observation_authority": "caller_provided_package_directory",
    "manifest_name": _MANIFEST_NAME,
    "manifest_preview": "scopecat_export_manifest_contract_reused",
    "file_observation": "package_local_declared_members",
    "checksum_algorithm": "sha256",
    "size_observation": "byte_count",
    "archive_extraction": "not_performed",
    "signature_validation": "not_performed",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "schema_inference": "not_performed",
    "gui_workflow": "not_defined",
}
_HASH_CHUNK_SIZE = 1024 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


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
    except FileNotFoundError:
        return "unavailable", None
    except OSError:
        return "unavailable", None
    if not stat.S_ISREG(target_stat.st_mode):
        return "blocked_non_regular_file", None

    return "observed", target


def _open_regular_member(target: Path) -> tuple[str, int | None]:
    try:
        file_fd = os.open(target, os.O_RDONLY | _NOFOLLOW | _NONBLOCK)
    except FileNotFoundError:
        return "unavailable", None
    except OSError:
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


def _observe_regular_member(package_dir: Path, relative_path: str) -> dict[str, Any]:
    state, target = _member_path_state(package_dir, relative_path)
    if state != "observed" or target is None:
        return {
            "observation_state": state,
            "comparison": "not_observed",
            "mismatches": [],
        }

    state, file_fd = _open_regular_member(target)
    if state != "observed" or file_fd is None:
        return {
            "observation_state": state,
            "comparison": "not_observed",
            "mismatches": [],
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
        "mismatches": [],
        "observed_digest": f"sha256:{digest.hexdigest()}",
        "observed_size_bytes": observed_size_bytes,
    }


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


def _validate_manifest_identity(package_dir: Path, manifest: dict[str, Any]) -> None:
    package_id = manifest["package_identity"]["package_id"]
    validate_public_identifier(package_id, "handoff package package_id")
    if package_dir.name != package_id:
        raise ValueError("handoff package directory name must match package_id")


def _add_member(
    members_by_path: dict[str, dict[str, Any]],
    *,
    package_path: str,
    owner_ref: dict[str, str],
    declared_digest: str | None = None,
    declared_size_bytes: int | None = None,
) -> None:
    member = members_by_path.setdefault(
        package_path,
        {
            "package_path": package_path,
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


def _declared_integrity(
    item: dict[str, Any],
    *,
    owner: str,
) -> tuple[str | None, int | None]:
    has_digest = "digest" in item
    has_size = "size_bytes" in item
    if has_digest != has_size:
        raise ValueError(f"{owner} digest and size_bytes must be declared together")
    if not has_digest:
        return None, None
    validate_sha256_digest(item["digest"], f"{owner} digest")
    validate_positive_integer(item["size_bytes"], f"{owner} size_bytes")
    return item["digest"], item["size_bytes"]


def _declared_members(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    members_by_path: dict[str, dict[str, Any]] = {}

    for record in manifest["selected_measurements"]:
        measurement_id = record["measurement_record_id"]
        primary = record["primary_data"]
        declared_digest, declared_size_bytes = _declared_integrity(
            primary,
            owner=f"selected measurement {measurement_id} primary data",
        )
        _add_member(
            members_by_path,
            package_path=primary["package_path"],
            owner_ref={
                "owner_type": "selected_measurement",
                "owner_id": measurement_id,
                "item_id": "primary_data",
                "kind": primary["kind"],
            },
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
            _add_member(
                members_by_path,
                package_path=package_path,
                owner_ref={
                    "owner_type": "default_bundle",
                    "owner_id": measurement_id,
                    "item_id": item["item_id"],
                    "kind": item["kind"],
                },
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
        _add_member(
            members_by_path,
            package_path=package_path,
            owner_ref={
                "owner_type": "linked_context",
                "owner_id": item["link_id"],
                "item_id": item["link_id"],
                "kind": item["kind"],
            },
            declared_digest=declared_digest,
            declared_size_bytes=declared_size_bytes,
        )

    return [members_by_path[path] for path in sorted(members_by_path)]


def _observation_for_member(package_dir: Path, member: dict[str, Any]) -> dict[str, Any]:
    observation = {
        "package_path": member["package_path"],
        "owner_refs": copy.deepcopy(member["owner_refs"]),
        "declared_digest": member.get("declared_digest"),
        "declared_size_bytes": member.get("declared_size_bytes"),
        **_observe_regular_member(package_dir, member["package_path"]),
    }
    if observation["observation_state"] != "observed":
        return observation

    declared_digest = member.get("declared_digest")
    declared_size_bytes = member.get("declared_size_bytes")
    if declared_digest is None or declared_size_bytes is None:
        observation["comparison"] = "not_declared"
        return observation

    mismatches = []
    if observation["observed_digest"] != declared_digest:
        mismatches.append("digest")
    if observation["observed_size_bytes"] != declared_size_bytes:
        mismatches.append("size_bytes")
    observation["mismatches"] = mismatches
    observation["comparison"] = "verified" if not mismatches else "mismatch"
    return observation


def _findings(member_observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for member in member_observations:
        comparison = member["comparison"]
        state = member["observation_state"]
        if comparison == "verified":
            continue
        if comparison == "mismatch":
            findings.append(
                {
                    "subject_type": "package_member",
                    "subject_id": member["package_path"],
                    "severity": "error",
                    "finding": "declared_integrity_mismatch",
                    "basis": "Observed package-local bytes do not match declared digest or size.",
                    "mismatches": list(member["mismatches"]),
                    "does_not_claim": "authenticity_or_signature_failure",
                }
            )
            continue
        if comparison == "not_declared" and state == "observed":
            findings.append(
                {
                    "subject_type": "package_member",
                    "subject_id": member["package_path"],
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
                "subject_id": member["package_path"],
                "severity": "error" if state == "unavailable" else "review",
                "finding": state,
                "basis": "The member could not be read as a regular package-local file.",
                "does_not_claim": "schema_or_payload_validity",
            }
        )
    return findings


def _classification(member_observations: list[dict[str, Any]]) -> str:
    comparisons = {member["comparison"] for member in member_observations}
    states = {member["observation_state"] for member in member_observations}
    if "mismatch" in comparisons or "unavailable" in states:
        return "integrity_review_required"
    if any(state.startswith("blocked_") for state in states):
        return "integrity_review_required"
    if comparisons == {"verified"}:
        return "declared_integrity_verified"
    if "not_declared" in comparisons:
        return "integrity_observed_with_undeclared_members"
    return "integrity_not_observed"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "package_members_observed_read_only",
            "severity": "info",
            "basis": "Manifest-declared package members were read from the caller-provided package directory without storage mutation.",
            "does_not_claim": "package_import_or_acceptance",
        },
        {
            "code": "checksum_comparison_is_local_observation",
            "severity": "review",
            "basis": "Digest and size comparison checks observed bytes against manifest facts only.",
            "does_not_claim": "authenticity_signature_or_provenance_trust",
        },
        {
            "code": "archive_not_extracted",
            "severity": "review",
            "basis": "This candidate observes an already expanded directory-shaped package.",
            "does_not_claim": "archive_contents_verified",
        },
    ]


def observe_handoff_package_integrity(package_dir: Path) -> dict[str, Any]:
    """Observe package-local member integrity for a directory-shaped package."""

    package_dir = _existing_package_dir(package_dir)
    manifest = _load_manifest(package_dir)
    preview_summary = build_handoff_package_contents_preview_summary(manifest)
    _validate_manifest_identity(package_dir, manifest)

    member_observations = [
        _observation_for_member(package_dir, member) for member in _declared_members(manifest)
    ]
    return {
        "package_integrity_observation_policy": copy.deepcopy(_EXPECTED_POLICY),
        "package": {
            "package_id": manifest["package_identity"]["package_id"],
            "display_name": manifest["package_identity"]["display_name"],
            "created_by": manifest["package_identity"]["created_by"],
            "source_export_summary_id": manifest["package_identity"]["source_export_summary_id"],
            "manifest_path": _MANIFEST_NAME,
            "preview_classification": preview_summary["package"]["classification"],
        },
        "member_count": len(member_observations),
        "member_observations": member_observations,
        "classification": _classification(member_observations),
        "integrity_findings": _findings(member_observations),
        "attention": _attention(),
    }

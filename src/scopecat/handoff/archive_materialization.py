"""Future archive materialization contract review for handoff packages."""

from __future__ import annotations

import copy
import posixpath
from dataclasses import dataclass
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier
from scopecat.handoff.errors import promote_handoff_contract_error

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

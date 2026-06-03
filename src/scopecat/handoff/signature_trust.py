"""Future signature and trust contract review for handoff packages."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier
from scopecat.handoff.errors import promote_handoff_contract_error

HANDOFF_SIGNATURE_TRUST_REVIEW_SCHEMA = "scopecat.handoff_signature_trust_review.v0"
HANDOFF_SIGNATURE_TRUST_POLICY = {
    "signature_implementation": "not_performed",
    "signature_verification": "not_performed",
    "trusted_source_acceptance": "not_performed",
    "signer_identity_validation": "not_performed",
    "key_management": "not_performed",
    "trust_root_configuration": "not_performed",
    "signature_gated_durable_import": "not_performed",
    "current_integrity_authority": "declared_digest_local_review_only",
    "package_artifact_of_record": "dec010_directory_manifest_package",
    "signed_scope_decision": "DEC-022",
}
REQUIRED_VERIFICATION_TIMING = [
    "package_open",
    "receiving_review",
    "import_planning",
    "durable_import",
]
REQUIRED_FAILURE_CLASSIFICATIONS = [
    "unsigned",
    "invalid_signature",
    "unknown_signer",
    "untrusted_signer",
    "stale_signature",
]
DOES_NOT_CLAIM = [
    "signature_verification",
    "source_authenticity",
    "sender_trust",
    "trusted_source_acceptance",
    "signature_gated_durable_import",
    "key_management",
    "trust_root_configuration",
    "scientific_validity",
]


@dataclass(frozen=True)
class SignatureTrustContractReview:
    """Review-only signature/trust policy candidate."""

    review_id: str
    signed_content_scope: str
    canonical_artifact: str
    canonicalization: str
    signer_identity: str
    trust_root: str
    unsigned_handling: str
    durable_import_gate: str
    verification_timing: dict[str, str]
    failure_classifications: dict[str, str]

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        reasons.extend(
            _signed_scope_blockers(
                signed_content_scope=self.signed_content_scope,
                canonical_artifact=self.canonical_artifact,
            )
        )
        reasons.extend(_required_value_blockers("canonicalization", self.canonicalization))
        reasons.extend(_required_value_blockers("signer_identity", self.signer_identity))
        reasons.extend(_required_value_blockers("trust_root", self.trust_root))
        reasons.extend(_unsigned_handling_blockers(self.unsigned_handling))
        reasons.extend(_durable_import_gate_blockers(self.durable_import_gate))
        reasons.extend(_verification_timing_blockers(self.verification_timing))
        reasons.extend(_failure_classification_blockers(self.failure_classifications))
        return tuple(dict.fromkeys(reasons))

    @property
    def classification(self) -> str:
        if self.blocked_reasons:
            return "blocked_before_signature_trust_contract"
        return "review_clean_signature_trust_contract"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_signature_trust_contract_review",
            "signature_trust_policy": copy.deepcopy(HANDOFF_SIGNATURE_TRUST_POLICY),
            "review_id": self.review_id,
            "classification": self.classification,
            "candidate": {
                "signed_content_scope": self.signed_content_scope,
                "canonical_artifact": self.canonical_artifact,
                "canonicalization": self.canonicalization,
                "signer_identity": self.signer_identity,
                "trust_root": self.trust_root,
                "unsigned_handling": self.unsigned_handling,
                "durable_import_gate": self.durable_import_gate,
                "verification_timing": copy.deepcopy(self.verification_timing),
                "failure_classifications": copy.deepcopy(self.failure_classifications),
            },
            "blocked_reasons": list(self.blocked_reasons),
            "review_state": _review_state(self.blocked_reasons),
            "trust_language": {
                "integrity": "declared_digest_integrity_is_local_review_evidence",
                "authenticity": "not_claimed_until_signature_contract_accepted",
                "sender_trust": "not_claimed_until_trust_root_contract_accepted",
                "scientific_validity": "not_claimed_by_signature_or_digest",
            },
            "does_not_claim": list(DOES_NOT_CLAIM),
        }


def current_handoff_signature_trust_contract() -> dict[str, Any]:
    """Return the current DEC-019/DEC-022 signature/trust contract posture."""

    return {
        "artifact_posture": "local_signature_trust_contract",
        "contract_version": HANDOFF_SIGNATURE_TRUST_REVIEW_SCHEMA,
        "signature_trust_policy": copy.deepcopy(HANDOFF_SIGNATURE_TRUST_POLICY),
        "current_posture": {
            "package_trust": "unsigned_local_review_evidence",
            "integrity": "declared_digest_integrity_only",
            "authenticity": "not_claimed",
            "sender_trust": "not_claimed",
            "durable_import_gate": "local_review_and_approval_not_signature_trust",
        },
        "future_contract_requirements": {
            "scope_decision": "DEC-022",
            "signed_content_scope": [
                "manifest_and_declared_members",
                "dec010_directory_manifest_package",
            ],
            "canonical_artifact": "dec010_directory_manifest_package",
            "canonicalization": "required_before_signature_verification",
            "signer_identity": "required_before_trusted_source_acceptance",
            "trust_root": "required_before_trusted_source_acceptance",
            "verification_timing": list(REQUIRED_VERIFICATION_TIMING),
            "failure_classifications": list(REQUIRED_FAILURE_CLASSIFICATIONS),
            "unsigned_handling": "locally_reviewable_not_trusted",
        },
        "does_not_claim": list(DOES_NOT_CLAIM),
    }


def review_handoff_signature_trust_contract(
    source: dict[str, Any],
) -> SignatureTrustContractReview:
    """Review a future signature/trust contract candidate without verification."""

    try:
        return _review_handoff_signature_trust_contract(source)
    except ValueError as exc:
        raise promote_handoff_contract_error(
            exc,
            operation="review_handoff_signature_trust_contract",
        ) from exc


def _review_handoff_signature_trust_contract(
    source: dict[str, Any],
) -> SignatureTrustContractReview:
    source = _require_mapping(source, "signature trust review source")
    _require_keys(
        source,
        {
            "signature_trust_review_schema",
            "signature_trust_policy",
            "review_id",
            "signed_content_scope",
            "canonical_artifact",
            "canonicalization",
            "signer_identity",
            "trust_root",
            "unsigned_handling",
            "durable_import_gate",
            "verification_timing",
            "failure_classifications",
        },
        "signature trust review source",
    )
    if source["signature_trust_review_schema"] != HANDOFF_SIGNATURE_TRUST_REVIEW_SCHEMA:
        raise ValueError("signature_trust_review_schema is unsupported")
    if source["signature_trust_policy"] != HANDOFF_SIGNATURE_TRUST_POLICY:
        raise ValueError("signature_trust_policy is unsupported")
    return SignatureTrustContractReview(
        review_id=validate_public_identifier(source["review_id"], "signature trust review_id"),
        signed_content_scope=validate_public_identifier(
            source["signed_content_scope"],
            "signed_content_scope",
        ),
        canonical_artifact=validate_public_identifier(
            source["canonical_artifact"],
            "canonical_artifact",
        ),
        canonicalization=validate_public_identifier(
            source["canonicalization"],
            "canonicalization",
        ),
        signer_identity=validate_public_identifier(source["signer_identity"], "signer_identity"),
        trust_root=validate_public_identifier(source["trust_root"], "trust_root"),
        unsigned_handling=validate_public_identifier(
            source["unsigned_handling"],
            "unsigned_handling",
        ),
        durable_import_gate=validate_public_identifier(
            source["durable_import_gate"],
            "durable_import_gate",
        ),
        verification_timing=_parse_string_mapping(
            source["verification_timing"],
            "verification_timing",
        ),
        failure_classifications=_parse_string_mapping(
            source["failure_classifications"],
            "failure_classifications",
        ),
    )


def _signed_scope_blockers(*, signed_content_scope: str, canonical_artifact: str) -> list[str]:
    reasons: list[str] = []
    if signed_content_scope == "declared_digest_only":
        reasons.append("digest_only_signature_is_not_authenticity")
    if signed_content_scope == "manifest_only":
        reasons.append("manifest_only_signature_excludes_package_members")
    if signed_content_scope == "archive_bytes":
        reasons.append("archive_bytes_signature_requires_archive_artifact_authority")
    if signed_content_scope not in {
        "manifest_and_declared_members",
        "dec010_directory_manifest_package",
    }:
        reasons.append("signed_content_scope_not_accepted")
    if canonical_artifact == "archive_bytes":
        reasons.append("archive_bytes_canonical_artifact_not_accepted")
    if canonical_artifact != "dec010_directory_manifest_package":
        reasons.append("canonical_artifact_must_be_dec010_directory_manifest_package")
    return reasons


def _required_value_blockers(owner: str, value: str) -> list[str]:
    if value == "not_defined":
        return [f"{owner}_required"]
    return []


def _unsigned_handling_blockers(value: str) -> list[str]:
    if value == "treat_as_trusted":
        return ["unsigned_package_must_not_be_trusted"]
    if value != "locally_reviewable_not_trusted":
        return ["unsigned_handling_not_accepted"]
    return []


def _durable_import_gate_blockers(value: str) -> list[str]:
    if value == "signature_required_now":
        return ["signature_gated_durable_import_not_accepted"]
    if value != "local_review_approval_until_trust_policy_accepted":
        return ["durable_import_gate_not_accepted"]
    return []


def _verification_timing_blockers(timing: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    for key in REQUIRED_VERIFICATION_TIMING:
        if timing.get(key) != "defined_before_signature_implementation":
            reasons.append(f"{key}_verification_timing_required")
    return reasons


def _failure_classification_blockers(classifications: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    for key in REQUIRED_FAILURE_CLASSIFICATIONS:
        if classifications.get(key) != "defined_before_signature_implementation":
            reasons.append(f"{key}_failure_classification_required")
    if classifications.get("unknown_signer") == "trusted":
        reasons.append("unknown_signer_must_not_be_trusted")
    if classifications.get("unsigned") == "trusted":
        reasons.append("unsigned_package_must_not_be_trusted")
    return reasons


def _review_state(blocked_reasons: tuple[str, ...]) -> dict[str, str | list[str] | None]:
    if blocked_reasons:
        return {
            "block_reason": "signature_trust_contract_not_ready",
            "blocked_reasons": list(blocked_reasons),
            "next_action": "resolve_signature_trust_contract_before_implementation",
            "retry_requires": "fresh_signature_trust_contract_review",
        }
    return {
        "block_reason": None,
        "blocked_reasons": [],
        "next_action": "decide_whether_trust_boundary_justifies_signature_implementation",
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


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")

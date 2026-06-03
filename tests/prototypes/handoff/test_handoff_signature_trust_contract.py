from __future__ import annotations

import copy
import unittest

from scopecat.handoff import (
    HandoffContractError,
    current_handoff_signature_trust_contract,
    review_handoff_signature_trust_contract,
)
from scopecat.handoff.signature_trust import (
    HANDOFF_SIGNATURE_TRUST_POLICY,
    HANDOFF_SIGNATURE_TRUST_REVIEW_SCHEMA,
)


def _source(**overrides: object) -> dict:
    source = {
        "signature_trust_review_schema": HANDOFF_SIGNATURE_TRUST_REVIEW_SCHEMA,
        "signature_trust_policy": HANDOFF_SIGNATURE_TRUST_POLICY,
        "review_id": "signature-trust-contract-review-001",
        "signed_content_scope": "manifest_and_declared_members",
        "canonical_artifact": "dec010_directory_manifest_package",
        "canonicalization": "required_before_signature_verification",
        "signer_identity": "required_before_trusted_source_acceptance",
        "trust_root": "required_before_trusted_source_acceptance",
        "unsigned_handling": "locally_reviewable_not_trusted",
        "durable_import_gate": "local_review_approval_until_trust_policy_accepted",
        "verification_timing": {
            "package_open": "defined_before_signature_implementation",
            "receiving_review": "defined_before_signature_implementation",
            "import_planning": "defined_before_signature_implementation",
            "durable_import": "defined_before_signature_implementation",
        },
        "failure_classifications": {
            "unsigned": "defined_before_signature_implementation",
            "invalid_signature": "defined_before_signature_implementation",
            "unknown_signer": "defined_before_signature_implementation",
            "untrusted_signer": "defined_before_signature_implementation",
            "stale_signature": "defined_before_signature_implementation",
        },
    }
    source.update(overrides)
    return source


class HandoffSignatureTrustContractTest(unittest.TestCase):
    def test_current_contract_keeps_integrity_separate_from_trust(self) -> None:
        contract = current_handoff_signature_trust_contract()

        self.assertEqual(contract["artifact_posture"], "local_signature_trust_contract")
        self.assertEqual(
            contract["current_posture"]["package_trust"],
            "unsigned_local_review_evidence",
        )
        self.assertEqual(contract["current_posture"]["authenticity"], "not_claimed")
        self.assertEqual(contract["current_posture"]["sender_trust"], "not_claimed")
        self.assertIn(
            "unknown_signer", contract["future_contract_requirements"]["failure_classifications"]
        )
        self.assertEqual(contract["future_contract_requirements"]["scope_decision"], "DEC-022")
        self.assertEqual(
            contract["signature_trust_policy"]["signed_scope_decision"],
            "DEC-022",
        )
        self.assertIn("signature_verification", contract["does_not_claim"])

    def test_review_clean_candidate_still_does_not_verify_or_accept_trust(self) -> None:
        review = review_handoff_signature_trust_contract(_source()).to_dict()

        self.assertEqual(review["artifact_posture"], "local_signature_trust_contract_review")
        self.assertEqual(review["classification"], "review_clean_signature_trust_contract")
        self.assertEqual(
            review["candidate"]["canonical_artifact"],
            "dec010_directory_manifest_package",
        )
        self.assertEqual(
            review["trust_language"]["integrity"],
            "declared_digest_integrity_is_local_review_evidence",
        )
        self.assertIn("signature_verification", review["does_not_claim"])
        self.assertIn("trusted_source_acceptance", review["does_not_claim"])

    def test_blocks_digest_only_or_manifest_only_signature_scope(self) -> None:
        digest_review = review_handoff_signature_trust_contract(
            _source(signed_content_scope="declared_digest_only")
        ).to_dict()
        manifest_review = review_handoff_signature_trust_contract(
            _source(signed_content_scope="manifest_only")
        ).to_dict()

        self.assertIn("digest_only_signature_is_not_authenticity", digest_review["blocked_reasons"])
        self.assertIn("signed_content_scope_not_accepted", digest_review["blocked_reasons"])
        self.assertIn(
            "manifest_only_signature_excludes_package_members",
            manifest_review["blocked_reasons"],
        )

    def test_blocks_archive_bytes_without_archive_artifact_authority(self) -> None:
        review = review_handoff_signature_trust_contract(
            _source(
                signed_content_scope="archive_bytes",
                canonical_artifact="archive_bytes",
            )
        ).to_dict()

        self.assertIn(
            "archive_bytes_signature_requires_archive_artifact_authority",
            review["blocked_reasons"],
        )
        self.assertIn(
            "archive_bytes_canonical_artifact_not_accepted",
            review["blocked_reasons"],
        )
        self.assertIn(
            "canonical_artifact_must_be_dec010_directory_manifest_package",
            review["blocked_reasons"],
        )

    def test_blocks_unsigned_and_unknown_signer_trusted_states(self) -> None:
        source = _source(
            unsigned_handling="treat_as_trusted",
            failure_classifications={
                "unsigned": "trusted",
                "invalid_signature": "defined_before_signature_implementation",
                "unknown_signer": "trusted",
                "untrusted_signer": "defined_before_signature_implementation",
                "stale_signature": "defined_before_signature_implementation",
            },
        )

        review = review_handoff_signature_trust_contract(source).to_dict()

        self.assertIn("unsigned_package_must_not_be_trusted", review["blocked_reasons"])
        self.assertIn("unknown_signer_must_not_be_trusted", review["blocked_reasons"])

    def test_blocks_signature_gated_durable_import_before_policy_is_accepted(self) -> None:
        review = review_handoff_signature_trust_contract(
            _source(durable_import_gate="signature_required_now")
        ).to_dict()

        self.assertIn("signature_gated_durable_import_not_accepted", review["blocked_reasons"])
        self.assertEqual(
            review["review_state"]["next_action"],
            "resolve_signature_trust_contract_before_implementation",
        )

    def test_blocks_missing_verification_timing_and_failure_classifications(self) -> None:
        review = review_handoff_signature_trust_contract(
            _source(
                verification_timing={"package_open": "defined_before_signature_implementation"},
                failure_classifications={
                    "unsigned": "defined_before_signature_implementation",
                },
            )
        ).to_dict()

        self.assertIn("receiving_review_verification_timing_required", review["blocked_reasons"])
        self.assertIn("import_planning_verification_timing_required", review["blocked_reasons"])
        self.assertIn("durable_import_verification_timing_required", review["blocked_reasons"])
        self.assertIn(
            "invalid_signature_failure_classification_required", review["blocked_reasons"]
        )
        self.assertIn("unknown_signer_failure_classification_required", review["blocked_reasons"])
        self.assertIn("untrusted_signer_failure_classification_required", review["blocked_reasons"])
        self.assertIn("stale_signature_failure_classification_required", review["blocked_reasons"])

    def test_blocks_missing_identity_canonicalization_and_trust_root(self) -> None:
        review = review_handoff_signature_trust_contract(
            _source(
                canonicalization="not_defined",
                signer_identity="not_defined",
                trust_root="not_defined",
            )
        ).to_dict()

        self.assertIn("canonicalization_required", review["blocked_reasons"])
        self.assertIn("signer_identity_required", review["blocked_reasons"])
        self.assertIn("trust_root_required", review["blocked_reasons"])

    def test_policy_drift_is_a_contract_error(self) -> None:
        source = _source()
        source["signature_trust_policy"] = copy.deepcopy(HANDOFF_SIGNATURE_TRUST_POLICY)
        source["signature_trust_policy"]["signature_verification"] = "performed"

        with self.assertRaises(HandoffContractError) as context:
            review_handoff_signature_trust_contract(source)

        self.assertEqual(
            context.exception.to_diagnostic().to_dict()["error"],
            {
                "code": "handoff_contract_error",
                "operation": "review_handoff_signature_trust_contract",
                "message": "signature_trust_policy is unsupported",
            },
        )


if __name__ == "__main__":
    unittest.main()

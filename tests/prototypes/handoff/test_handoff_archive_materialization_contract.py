from __future__ import annotations

import copy
import unittest

from scopecat.handoff import (
    HandoffContractError,
    current_handoff_archive_materialization_contract,
    review_handoff_archive_materialization_contract,
)
from scopecat.handoff.archive_materialization import (
    HANDOFF_ARCHIVE_MATERIALIZATION_POLICY,
    HANDOFF_ARCHIVE_MATERIALIZATION_REVIEW_SCHEMA,
)


def _source(**overrides: object) -> dict:
    source = {
        "archive_materialization_review_schema": (HANDOFF_ARCHIVE_MATERIALIZATION_REVIEW_SCHEMA),
        "archive_materialization_policy": HANDOFF_ARCHIVE_MATERIALIZATION_POLICY,
        "review_id": "archive-materialization-contract-review-001",
        "archive_format": "zip_candidate",
        "staging_policy": {
            "staging_directory": "required_unique_empty_scopecat_owned_directory",
            "overwrite": "no_overwrite",
            "cleanup": "explicit_success_and_failure_cleanup_required",
        },
        "resource_limits": {
            "archive_size_bytes": "required_before_archive_materialization",
            "extracted_size_bytes": "required_before_archive_materialization",
            "member_count": "required_before_archive_materialization",
            "compression_ratio": "required_before_archive_materialization",
            "extraction_time": "required_before_archive_materialization",
        },
        "members": [
            {
                "path": "handoff-package-legacy-rabi-001/package-manifest.json",
                "member_type": "regular_file",
            },
            {
                "path": "handoff-package-legacy-rabi-001/measurements/legacy-rabi-001/primary.csv",
                "member_type": "regular_file",
            },
        ],
    }
    source.update(overrides)
    return source


class HandoffArchiveMaterializationContractTest(unittest.TestCase):
    def test_current_contract_keeps_directory_manifest_as_artifact_of_record(self) -> None:
        contract = current_handoff_archive_materialization_contract()

        self.assertEqual(contract["artifact_posture"], "local_archive_materialization_contract")
        self.assertEqual(
            contract["artifact_authority"]["current_package_of_record"],
            "dec010_directory_manifest_package",
        )
        self.assertEqual(
            contract["artifact_authority"]["future_archive_bytes"],
            "transport_container_only",
        )
        self.assertIn(
            "reject_parent_traversal",
            contract["future_materialization_requirements"]["path_safety"],
        )
        self.assertIn(
            "compression_ratio",
            contract["future_materialization_requirements"]["resource_limits"],
        )
        self.assertIn("archive_extraction", contract["does_not_claim"])

    def test_review_clean_candidate_still_does_not_extract_or_accept_archive(self) -> None:
        review = review_handoff_archive_materialization_contract(_source()).to_dict()

        self.assertEqual(
            review["artifact_posture"],
            "local_archive_materialization_contract_review",
        )
        self.assertEqual(
            review["classification"],
            "review_clean_archive_materialization_contract",
        )
        self.assertEqual(
            review["artifact_authority"]["archive_bytes"],
            "transport_container_only",
        )
        self.assertEqual(
            review["artifact_authority"]["package_of_record"],
            "dec010_directory_manifest_package",
        )
        self.assertIn("archive_extraction", review["does_not_claim"])
        self.assertIn("safe_to_extract_archive", review["does_not_claim"])

    def test_blocks_parent_traversal_and_absolute_member_paths(self) -> None:
        source = _source(
            members=[
                {"path": "../outside/package-manifest.json", "member_type": "regular_file"},
                {"path": "/tmp/package-manifest.json", "member_type": "regular_file"},
                {"path": "C:\\temp\\package-manifest.json", "member_type": "regular_file"},
            ]
        )

        review = review_handoff_archive_materialization_contract(source).to_dict()

        self.assertEqual(
            review["classification"],
            "blocked_before_archive_materialization_contract",
        )
        self.assertIn("parent_traversal_archive_member_path", review["blocked_reasons"])
        self.assertIn("absolute_archive_member_path", review["blocked_reasons"])
        self.assertEqual(
            review["review_state"]["next_action"],
            "resolve_archive_materialization_contract_before_implementation",
        )

    def test_blocks_duplicate_normalized_archive_member_paths(self) -> None:
        source = _source(
            members=[
                {"path": "pkg/manifest/../package-manifest.json", "member_type": "regular_file"},
                {"path": "pkg/package-manifest.json", "member_type": "regular_file"},
            ]
        )

        review = review_handoff_archive_materialization_contract(source).to_dict()

        self.assertIn("duplicate_archive_member_path", review["blocked_reasons"])

    def test_blocks_symlink_directory_and_hidden_metadata_members(self) -> None:
        source = _source(
            members=[
                {"path": "pkg/link", "member_type": "symlink"},
                {"path": "pkg/", "member_type": "directory"},
                {"path": "__MACOSX/pkg/package-manifest.json", "member_type": "hidden_metadata"},
            ]
        )

        review = review_handoff_archive_materialization_contract(source).to_dict()

        self.assertIn("symlink_archive_member_not_allowed", review["blocked_reasons"])
        self.assertIn(
            "directory_archive_member_requires_explicit_policy",
            review["blocked_reasons"],
        )
        self.assertIn("metadata_archive_member_not_allowed", review["blocked_reasons"])

    def test_blocks_hidden_metadata_paths_even_when_declared_as_regular_files(self) -> None:
        source = _source(
            members=[
                {"path": "__MACOSX/pkg/package-manifest.json", "member_type": "regular_file"},
                {"path": "pkg/.DS_Store", "member_type": "regular_file"},
            ]
        )

        review = review_handoff_archive_materialization_contract(source).to_dict()

        self.assertIn("metadata_archive_member_not_allowed", review["blocked_reasons"])

    def test_blocks_missing_staging_and_resource_limit_contracts(self) -> None:
        source = _source()
        source["staging_policy"] = {
            "staging_directory": "reuse_existing_directory",
            "overwrite": "overwrite_allowed",
            "cleanup": "best_effort",
        }
        source["resource_limits"] = {
            "archive_size_bytes": "required_before_archive_materialization",
        }

        review = review_handoff_archive_materialization_contract(source).to_dict()

        self.assertIn("staging_directory_policy_required", review["blocked_reasons"])
        self.assertIn("overwrite_policy_required", review["blocked_reasons"])
        self.assertIn("cleanup_policy_required", review["blocked_reasons"])
        self.assertIn("extracted_size_bytes_limit_required", review["blocked_reasons"])
        self.assertIn("member_count_limit_required", review["blocked_reasons"])
        self.assertIn("compression_ratio_limit_required", review["blocked_reasons"])
        self.assertIn("extraction_time_limit_required", review["blocked_reasons"])

    def test_policy_drift_is_a_contract_error(self) -> None:
        source = _source()
        source["archive_materialization_policy"] = copy.deepcopy(
            HANDOFF_ARCHIVE_MATERIALIZATION_POLICY
        )
        source["archive_materialization_policy"]["archive_extraction"] = "extract_zip"

        with self.assertRaises(HandoffContractError) as context:
            review_handoff_archive_materialization_contract(source)

        self.assertEqual(
            context.exception.to_diagnostic().to_dict()["error"],
            {
                "code": "handoff_contract_error",
                "operation": "review_handoff_archive_materialization_contract",
                "message": "archive_materialization_policy is unsupported",
            },
        )


if __name__ == "__main__":
    unittest.main()

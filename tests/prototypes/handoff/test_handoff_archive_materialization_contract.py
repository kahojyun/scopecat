from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from scopecat.handoff import (
    HandoffArchiveCreationRequest,
    HandoffArchiveMaterializationRequest,
    HandoffContractError,
    create_handoff_archive_package,
    create_handoff_archive_package_from_request,
    current_handoff_archive_materialization_contract,
    materialize_handoff_archive_package,
    materialize_handoff_archive_package_from_request,
    open_package,
    review_handoff_archive_materialization_contract,
)
from scopecat.handoff.archive_materialization import (
    HANDOFF_ARCHIVE_MATERIALIZATION_POLICY,
    HANDOFF_ARCHIVE_MATERIALIZATION_REVIEW_SCHEMA,
    HANDOFF_ARCHIVE_MATERIALIZATION_SCHEMA,
    HANDOFF_ARCHIVE_PACKAGE_CREATION_POLICY,
    HANDOFF_ARCHIVE_PACKAGE_MATERIALIZATION_POLICY,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "handoff"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
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


def _request(**overrides: object) -> HandoffArchiveMaterializationRequest:
    values = {
        "request_id": "materialize-archive-001",
        "approval_state": "approved",
        "archive_path": "handoff-package-legacy-rabi-001.zip",
        "package_dir": "handoff-package-legacy-rabi-001",
    }
    values.update(overrides)
    return HandoffArchiveMaterializationRequest(**values)


def _creation_request(**overrides: object) -> HandoffArchiveCreationRequest:
    values = {
        "request_id": "create-archive-001",
        "approval_state": "approved",
        "package_dir": "handoff-package-legacy-rabi-001",
        "archive_path": "handoff-package-legacy-rabi-001.zip",
    }
    values.update(overrides)
    return HandoffArchiveCreationRequest(**values)


def _raw_source(**overrides: object) -> dict:
    return {
        "archive_materialization_schema": HANDOFF_ARCHIVE_MATERIALIZATION_SCHEMA,
        "archive_materialization_policy": HANDOFF_ARCHIVE_PACKAGE_MATERIALIZATION_POLICY,
        "archive_materialization_request": _request(**overrides).to_dict(),
    }


def _raw_creation_source(**overrides: object) -> dict:
    return {
        "archive_creation_schema": "scopecat.handoff_archive_creation.v0",
        "archive_creation_policy": HANDOFF_ARCHIVE_PACKAGE_CREATION_POLICY,
        "archive_creation_request": _creation_request(**overrides).to_dict(),
    }


def _write_package_zip(archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in sorted(PACKAGE_FIXTURE.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    arcname=f"{PACKAGE_FIXTURE.name}/{path.relative_to(PACKAGE_FIXTURE)}",
                )


def _write_zip(archive_path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


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

    def test_creates_zip_transport_archive_and_round_trips_to_materialized_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            package_root.mkdir()
            archive_root.mkdir()
            materialization_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )
            materialized = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )
            package = open_package(materialization_root / "handoff-package-legacy-rabi-001")

        creation_payload = creation.to_dict()
        self.assertTrue(creation.created)
        self.assertTrue(materialized.materialized)
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        self.assertEqual(
            creation_payload["artifact_authority"]["archive_bytes"],
            "transport_container_only",
        )
        self.assertEqual(
            creation_payload["artifact_authority"]["package_of_record"],
            "dec010_directory_manifest_package",
        )
        self.assertIn(
            "handoff-package-legacy-rabi-001/package-manifest.json",
            creation_payload["archive"]["archived_files"],
        )
        self.assertEqual(creation_payload["creation_review"]["block_reason"], None)

    def test_raw_source_archive_creation_uses_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            package_root.mkdir()
            archive_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)

            creation = create_handoff_archive_package(
                _raw_creation_source(),
                package_root=package_root,
                archive_root=archive_root,
            )

        self.assertTrue(creation.created)

    def test_archive_creation_blocks_existing_archive_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            package_root.mkdir()
            archive_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)
            (archive_root / "handoff-package-legacy-rabi-001.zip").write_text(
                "existing",
                encoding="utf-8",
            )

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )

        self.assertFalse(creation.created)
        self.assertEqual(
            creation.to_dict()["creation_review"]["block_reason"],
            "archive_destination_collision",
        )

    def test_archive_creation_blocks_symlink_archive_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            package_root.mkdir()
            archive_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)
            (archive_root / "existing.zip").write_text("existing", encoding="utf-8")
            (archive_root / "handoff-package-legacy-rabi-001.zip").symlink_to(
                "existing.zip",
            )

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )

        self.assertFalse(creation.created)
        self.assertEqual(
            creation.to_dict()["creation_review"]["block_reason"],
            "archive_destination_collision",
        )

    def test_archive_creation_blocks_symlink_package_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            archive_root = temp_root / "archives"
            package_root.mkdir()
            archive_root.mkdir()
            shutil.copytree(PACKAGE_FIXTURE, package_root / PACKAGE_FIXTURE.name)
            (
                package_root
                / PACKAGE_FIXTURE.name
                / "measurements"
                / "legacy-rabi-001"
                / "linked-primary.csv"
            ).symlink_to("primary.csv")

            creation = create_handoff_archive_package_from_request(
                _creation_request(),
                package_root=package_root,
                archive_root=archive_root,
            )

        self.assertFalse(creation.created)
        self.assertEqual(
            creation.to_dict()["creation_review"]["block_reason"],
            "archive_creation_symlink_blocked",
        )

    def test_materializes_zip_transport_into_openable_directory_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_package_zip(archive_root / "handoff-package-legacy-rabi-001.zip")

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )
            package = open_package(materialization_root / "handoff-package-legacy-rabi-001")

        payload = run.to_dict()
        self.assertTrue(run.materialized)
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        self.assertEqual(
            payload["artifact_authority"]["archive_bytes"],
            "transport_container_only",
        )
        self.assertEqual(
            payload["artifact_authority"]["package_of_record"],
            "materialized_dec010_directory_manifest_package",
        )
        self.assertIn(
            "handoff-package-legacy-rabi-001/package-manifest.json",
            payload["materialization"]["materialized_files"],
        )
        self.assertEqual(payload["materialization_review"]["block_reason"], None)

    def test_raw_source_materialization_uses_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_package_zip(archive_root / "handoff-package-legacy-rabi-001.zip")

            run = materialize_handoff_archive_package(
                _raw_source(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

        self.assertTrue(run.materialized)

    def test_materialization_blocks_parent_traversal_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_zip(
                archive_root / "handoff-package-legacy-rabi-001.zip",
                {
                    "../outside.txt": "outside",
                    "handoff-package-legacy-rabi-001/package-manifest.json": "{}",
                },
            )

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

        payload = run.to_dict()
        self.assertFalse(run.materialized)
        self.assertIn(
            "parent_traversal_archive_member_path",
            payload["materialization"]["materialization_error"],
        )
        self.assertFalse((materialization_root / "handoff-package-legacy-rabi-001").exists())

    def test_materialization_blocks_symlink_member_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            archive_path = archive_root / "handoff-package-legacy-rabi-001.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                info = zipfile.ZipInfo("handoff-package-legacy-rabi-001/link")
                info.external_attr = 0o120777 << 16
                archive.writestr(info, "package-manifest.json")
                archive.writestr("handoff-package-legacy-rabi-001/package-manifest.json", "{}")

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

        self.assertFalse(run.materialized)
        self.assertIn(
            "symlink_archive_member_not_allowed",
            run.to_dict()["materialization"]["materialization_error"],
        )

    def test_materialization_blocks_existing_package_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_package_zip(archive_root / "handoff-package-legacy-rabi-001.zip")
            shutil.copytree(
                PACKAGE_FIXTURE,
                materialization_root / "handoff-package-legacy-rabi-001",
            )

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

        self.assertFalse(run.materialized)
        self.assertIn("target already exists", run.materialization_error or "")

    def test_materialization_cleans_partial_package_when_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_root = temp_root / "archives"
            materialization_root = temp_root / "materialized"
            archive_root.mkdir()
            materialization_root.mkdir()
            _write_zip(
                archive_root / "handoff-package-legacy-rabi-001.zip",
                {"handoff-package-legacy-rabi-001/package-manifest.json": "{}"},
            )

            run = materialize_handoff_archive_package_from_request(
                _request(),
                archive_root=archive_root,
                materialization_root=materialization_root,
            )

            self.assertFalse((materialization_root / "handoff-package-legacy-rabi-001").exists())

        self.assertFalse(run.materialized)
        self.assertTrue(run.cleanup_performed)
        self.assertIn("package_identity", run.materialization_error or "")


if __name__ == "__main__":
    unittest.main()

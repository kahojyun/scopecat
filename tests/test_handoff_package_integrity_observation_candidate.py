from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_integrity_observation import (
    observe_handoff_package_integrity,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _load_manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict) -> None:
    (package_dir / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class HandoffPackageIntegrityObservationCandidateTest(unittest.TestCase):
    def test_observes_verified_declared_primary_data_integrity(self) -> None:
        summary = observe_handoff_package_integrity(PACKAGE)

        self.assertEqual(summary["classification"], "declared_integrity_verified")
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["member_count"], 1)
        self.assertEqual(summary["integrity_findings"], [])
        member = summary["member_observations"][0]
        self.assertEqual(member["package_path"], "measurements/legacy-rabi-001/primary.csv")
        self.assertEqual(member["observation_state"], "observed")
        self.assertEqual(member["comparison"], "verified")
        self.assertEqual(member["observed_size_bytes"], 73)
        self.assertEqual(
            member["observed_digest"],
            "sha256:e7407c74b4bb35e1cc350ae2cc4829981c5b48ac7db4364366f0b30802eab887",
        )
        self.assertEqual(member["declared_size_bytes"], 73)
        self.assertEqual(
            member["declared_digest"],
            "sha256:e7407c74b4bb35e1cc350ae2cc4829981c5b48ac7db4364366f0b30802eab887",
        )

    def test_reports_changed_package_member_as_integrity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )

            summary = observe_handoff_package_integrity(package_dir)

        member = summary["member_observations"][0]
        self.assertEqual(summary["classification"], "integrity_review_required")
        self.assertEqual(member["comparison"], "mismatch")
        self.assertEqual(member["mismatches"], ["digest", "size_bytes"])
        self.assertEqual(
            summary["integrity_findings"][0]["finding"],
            "declared_integrity_mismatch",
        )

    def test_reports_missing_package_member_without_importing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").unlink()

            summary = observe_handoff_package_integrity(package_dir)

        member = summary["member_observations"][0]
        self.assertEqual(summary["classification"], "integrity_review_required")
        self.assertEqual(member["observation_state"], "unavailable")
        self.assertEqual(member["comparison"], "not_observed")
        self.assertEqual(summary["integrity_findings"][0]["finding"], "unavailable")

    def test_blocks_symlink_package_member_without_following_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            primary_path = package_dir / "measurements" / "legacy-rabi-001" / "primary.csv"
            primary_path.unlink()
            os.symlink("/tmp/not-a-package-member.csv", primary_path)

            summary = observe_handoff_package_integrity(package_dir)

        member = summary["member_observations"][0]
        self.assertEqual(summary["classification"], "integrity_review_required")
        self.assertEqual(member["observation_state"], "blocked_symlink_file")
        self.assertEqual(member["comparison"], "not_observed")
        self.assertEqual(
            summary["integrity_findings"][0]["finding"],
            "blocked_symlink_file",
        )

    def test_blocks_symlink_package_member_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            record_dir = package_dir / "measurements" / "legacy-rabi-001"
            shutil.rmtree(record_dir)
            os.symlink(temp_root / "outside-record", record_dir)

            summary = observe_handoff_package_integrity(package_dir)

        member = summary["member_observations"][0]
        self.assertEqual(summary["classification"], "integrity_review_required")
        self.assertEqual(member["observation_state"], "blocked_symlink_parent")
        self.assertEqual(member["comparison"], "not_observed")
        self.assertEqual(
            summary["integrity_findings"][0]["finding"],
            "blocked_symlink_parent",
        )

    def test_blocks_non_regular_package_member_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            primary_path = package_dir / "measurements" / "legacy-rabi-001" / "primary.csv"
            primary_path.unlink()
            os.mkfifo(primary_path)

            summary = observe_handoff_package_integrity(package_dir)

        member = summary["member_observations"][0]
        self.assertEqual(summary["classification"], "integrity_review_required")
        self.assertEqual(member["observation_state"], "blocked_non_regular_file")
        self.assertEqual(member["comparison"], "not_observed")
        self.assertEqual(
            summary["integrity_findings"][0]["finding"],
            "blocked_non_regular_file",
        )

    def test_reports_observed_member_without_declared_integrity_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _load_manifest(package_dir)
            manifest["selected_measurements"][0]["primary_data"].pop("digest")
            manifest["selected_measurements"][0]["primary_data"].pop("size_bytes")
            _write_manifest(package_dir, manifest)

            summary = observe_handoff_package_integrity(package_dir)

        member = summary["member_observations"][0]
        self.assertEqual(
            summary["classification"],
            "integrity_observed_with_undeclared_members",
        )
        self.assertEqual(member["observation_state"], "observed")
        self.assertEqual(member["comparison"], "not_declared")
        self.assertIsNone(member["declared_digest"])
        self.assertIsNone(member["declared_size_bytes"])
        self.assertEqual(
            summary["integrity_findings"][0]["finding"],
            "declared_integrity_not_available",
        )

    def test_observes_distinct_packaged_linked_context_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            context_dir = package_dir / "context"
            context_dir.mkdir()
            context_path = context_dir / "package-legacy-001-parameter-snapshot.json"
            context_content = b'{"attenuation_db":"12"}\n'
            context_path.write_bytes(context_content)
            manifest = _load_manifest(package_dir)
            manifest["linked_context"][0].update(
                {
                    "package_path": "context/package-legacy-001-parameter-snapshot.json",
                    "include_status": "included_by_user",
                    "package_state": "packaged",
                    "reason": None,
                    "digest": f"sha256:{hashlib.sha256(context_content).hexdigest()}",
                    "size_bytes": len(context_content),
                }
            )
            _write_manifest(package_dir, manifest)

            summary = observe_handoff_package_integrity(package_dir)

        observations = {member["package_path"]: member for member in summary["member_observations"]}
        self.assertEqual(summary["classification"], "declared_integrity_verified")
        self.assertEqual(summary["member_count"], 2)
        self.assertEqual(
            observations["context/package-legacy-001-parameter-snapshot.json"]["comparison"],
            "verified",
        )
        self.assertEqual(
            observations["context/package-legacy-001-parameter-snapshot.json"]["owner_refs"],
            [
                {
                    "owner_type": "linked_context",
                    "owner_id": "package-legacy-001-parameter-snapshot",
                    "item_id": "package-legacy-001-parameter-snapshot",
                    "kind": "parameter_state",
                }
            ],
        )

    def test_rejects_partial_integrity_declaration_on_packaged_linked_context(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _load_manifest(package_dir)
            manifest["linked_context"][0].update(
                {
                    "package_path": "context/package-legacy-001-parameter-snapshot.json",
                    "include_status": "included_by_user",
                    "package_state": "packaged",
                    "reason": None,
                    "digest": (
                        "sha256:e7407c74b4bb35e1cc350ae2cc4829981c5b48ac7db4364366f0b30802eab887"
                    ),
                }
            )
            _write_manifest(package_dir, manifest)

            with self.assertRaisesRegex(
                ValueError,
                "digest and size_bytes must be declared together",
            ):
                observe_handoff_package_integrity(package_dir)

    def test_rejects_directory_name_that_does_not_match_manifest_package_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "different-package-name"
            shutil.copytree(PACKAGE, package_dir)

            with self.assertRaisesRegex(ValueError, "directory name must match package_id"):
                observe_handoff_package_integrity(package_dir)


if __name__ == "__main__":
    unittest.main()

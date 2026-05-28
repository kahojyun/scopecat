from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.adapter_output_boundary import (
    validate_adapter_output_boundary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "adapter_output_boundary" / "basic_bundle"
ADAPTER_OUTPUT_ROOT = FIXTURE / "adapter-output"


def _load_boundary_manifest(root: Path = ADAPTER_OUTPUT_ROOT) -> dict:
    return json.loads((root / "adapter-output-boundary.json").read_text(encoding="utf-8"))


def _write_boundary_manifest(root: Path, manifest: dict) -> None:
    (root / "adapter-output-boundary.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def _file_facts(path: Path) -> tuple[str, int]:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}", path.stat().st_size


def _refresh_declared_file_facts(root: Path, manifest: dict, file_id: str) -> None:
    declared = next(
        file_record
        for file_record in manifest["declared_files"]
        if file_record["file_id"] == file_id
    )
    declared["digest"], declared["size_bytes"] = _file_facts(root / declared["path"])


def _refresh_linked_context_ref_facts(root: Path, manifest: dict, link_id: str) -> None:
    ref = next(ref for ref in manifest["linked_context_refs"] if ref["link_id"] == link_id)
    ref["digest"], ref["size_bytes"] = _file_facts(root / ref["path"])


class AdapterOutputBoundarySummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_adapter_output_boundary_summary(self) -> None:
        summary = validate_adapter_output_boundary(ADAPTER_OUTPUT_ROOT)
        expected = json.loads(
            (FIXTURE / "expected-adapter-output-boundary-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)

    def test_file_fixture_transport_does_not_accept_final_api(self) -> None:
        summary = validate_adapter_output_boundary(ADAPTER_OUTPUT_ROOT)

        self.assertEqual(summary["adapter_output_policy"]["final_transport_api"], "not_decided")
        self.assertEqual(
            summary["adapter_output_policy"]["writer_like_api_compatibility"],
            "logical_contract_only",
        )
        self.assertEqual(summary["storage_mutation"], "not_performed")
        self.assertEqual(summary["import_acceptance"], "not_performed")
        self.assertEqual(
            summary["attention"][1]["does_not_claim"],
            "final_transport_or_storage_protocol",
        )

    def test_missing_normalized_primary_data_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            (root / "source-data" / "measurement.csv").unlink()

            summary = validate_adapter_output_boundary(root)

        self.assertEqual(summary["classification"], "adapter_output_blocked_by_file_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["adapter_output_file_unavailable"],
        )
        self.assertEqual(
            summary["adapter_manifest_review"]["classification"],
            "adapter_manifest_ready_for_review",
        )

    def test_declared_digest_mismatch_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            manifest = _load_boundary_manifest(root)
            manifest["declared_files"][1]["digest"] = (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
            _write_boundary_manifest(root, manifest)

            summary = validate_adapter_output_boundary(root)

        self.assertEqual(summary["classification"], "adapter_output_blocked_by_file_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["adapter_output_digest_mismatch"],
        )

    def test_declared_primary_data_must_match_adapter_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            other_primary = root / "source-data" / "other-measurement.csv"
            shutil.copyfile(root / "source-data" / "measurement.csv", other_primary)
            manifest = _load_boundary_manifest(root)
            primary_file = next(
                file_record
                for file_record in manifest["declared_files"]
                if file_record["role"] == "normalized_primary_data"
            )
            primary_file["path"] = "source-data/other-measurement.csv"
            primary_file["digest"], primary_file["size_bytes"] = _file_facts(other_primary)
            _write_boundary_manifest(root, manifest)

            summary = validate_adapter_output_boundary(root)

        self.assertEqual(summary["classification"], "adapter_output_blocked_by_file_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["adapter_output_primary_data_not_declared"],
        )

    def test_transport_policy_claims_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            manifest = _load_boundary_manifest(root)
            manifest["adapter_output_policy"]["final_transport_api"] = "stable_writer_api"
            _write_boundary_manifest(root, manifest)

            with self.assertRaisesRegex(ValueError, "final_transport_api"):
                validate_adapter_output_boundary(root)

    def test_transport_summary_claims_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            manifest = _load_boundary_manifest(root)
            manifest["transport"]["final_transport"] = "stable_writer_api"
            _write_boundary_manifest(root, manifest)

            with self.assertRaisesRegex(ValueError, "transport final_transport"):
                validate_adapter_output_boundary(root)

    def test_manifest_file_mismatch_blocks_before_manifest_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            manifest = _load_boundary_manifest(root)
            manifest["declared_files"][0]["digest"] = (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
            _write_boundary_manifest(root, manifest)

            summary = validate_adapter_output_boundary(root)

        self.assertEqual(
            summary["classification"],
            "adapter_output_blocked_by_manifest_file_findings",
        )
        self.assertIsNone(summary["adapter_manifest_review"])
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["adapter_output_digest_mismatch"],
        )

    def test_core_legacy_parser_claims_are_rejected_by_delegated_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            adapter_manifest_path = root / "adapter-import-manifest.json"
            adapter_manifest = json.loads(adapter_manifest_path.read_text(encoding="utf-8"))
            adapter_manifest["adapter"]["parsing_authority"] = "scopecat_core"
            adapter_manifest_path.write_text(
                json.dumps(adapter_manifest, indent=2) + "\n",
                encoding="utf-8",
            )
            boundary_manifest = _load_boundary_manifest(root)
            _refresh_declared_file_facts(root, boundary_manifest, "adapter-manifest")
            _write_boundary_manifest(root, boundary_manifest)

            with self.assertRaisesRegex(ValueError, "parsing authority"):
                validate_adapter_output_boundary(root)

    def test_linked_context_ref_must_match_adapter_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            manifest = _load_boundary_manifest(root)
            manifest["linked_context_refs"][0]["link_id"] = "other-link"
            _write_boundary_manifest(root, manifest)

            summary = validate_adapter_output_boundary(root)

        self.assertEqual(summary["classification"], "adapter_output_blocked_by_file_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            [
                "adapter_output_linked_context_not_declared",
                "adapter_output_linked_context_ref_missing",
            ],
        )

    def test_available_manifest_linked_context_requires_output_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            adapter_manifest_path = root / "adapter-import-manifest.json"
            adapter_manifest = json.loads(adapter_manifest_path.read_text(encoding="utf-8"))
            adapter_manifest["linked_context"].append(
                {
                    "link_id": "legacy-001-calibration-note",
                    "kind": "note",
                    "role": "analysis_context",
                    "label": "Calibration note",
                    "reference": "legacy-record-001 calibration note",
                    "authority": "adapter_declared",
                    "reference_state": "adapter_declared_available",
                    "reason": None,
                }
            )
            adapter_manifest_path.write_text(
                json.dumps(adapter_manifest, indent=2) + "\n",
                encoding="utf-8",
            )
            boundary_manifest = _load_boundary_manifest(root)
            _refresh_declared_file_facts(root, boundary_manifest, "adapter-manifest")
            _write_boundary_manifest(root, boundary_manifest)

            summary = validate_adapter_output_boundary(root)

        self.assertEqual(summary["classification"], "adapter_output_blocked_by_file_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["adapter_output_linked_context_ref_missing"],
        )

    def test_multiple_available_linked_context_refs_can_be_declared(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            second_ref_path = root / "context" / "calibration-note.reference.json"
            second_ref_path.write_text(
                json.dumps(
                    {
                        "status": "fixture",
                        "reference": "legacy-record-001 calibration note",
                        "payload_import": "not_performed",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            adapter_manifest_path = root / "adapter-import-manifest.json"
            adapter_manifest = json.loads(adapter_manifest_path.read_text(encoding="utf-8"))
            adapter_manifest["linked_context"].append(
                {
                    "link_id": "legacy-001-calibration-note",
                    "kind": "note",
                    "role": "analysis_context",
                    "label": "Calibration note",
                    "reference": "legacy-record-001 calibration note",
                    "authority": "adapter_declared",
                    "reference_state": "adapter_declared_available",
                    "reason": None,
                }
            )
            adapter_manifest_path.write_text(
                json.dumps(adapter_manifest, indent=2) + "\n",
                encoding="utf-8",
            )
            boundary_manifest = _load_boundary_manifest(root)
            boundary_manifest["linked_context_refs"].append(
                {
                    "link_id": "legacy-001-calibration-note",
                    "path": "context/calibration-note.reference.json",
                    "authority": "adapter_declared",
                    "payload_import": "not_performed",
                    "digest": "",
                    "size_bytes": 1,
                }
            )
            _refresh_declared_file_facts(root, boundary_manifest, "adapter-manifest")
            _refresh_linked_context_ref_facts(
                root, boundary_manifest, "legacy-001-calibration-note"
            )
            _write_boundary_manifest(root, boundary_manifest)

            summary = validate_adapter_output_boundary(root)

        self.assertEqual(summary["classification"], "adapter_output_ready_for_review")
        self.assertEqual(summary["review_findings"], [])
        self.assertEqual(
            [ref["file_id"] for ref in summary["observed_linked_context_refs"]],
            ["legacy-001-parameter-snapshot", "legacy-001-calibration-note"],
        )

    def test_target_symlink_is_refused_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "adapter-output"
            shutil.copytree(ADAPTER_OUTPUT_ROOT, root)
            target = root / "source-data" / "measurement.csv"
            target.unlink()
            target.symlink_to("redirected.csv")

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                validate_adapter_output_boundary(root)

            self.assertTrue(target.is_symlink())
            self.assertFalse((target.parent / "redirected.csv").exists())

    def test_output_does_not_alias_boundary_manifest(self) -> None:
        source = _load_boundary_manifest()
        source_copy = copy.deepcopy(source)

        summary = validate_adapter_output_boundary(ADAPTER_OUTPUT_ROOT)
        source["adapter_output_policy"]["final_transport_api"] = "mutated"

        self.assertEqual(
            summary["adapter_output_policy"],
            source_copy["adapter_output_policy"],
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.editable_folder_observation import (
    build_editable_folder_observation_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "editable_folder_observation" / "basic_observation"
WORKSPACE = FIXTURE / "workspace"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "editable-folder-observation-input.json").read_text(encoding="utf-8")
    )


class EditableFolderObservationSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_editable_folder_observation_summary(
            _load_input(),
            workspace_root=WORKSPACE,
        )
        expected = json.loads(
            (FIXTURE / "expected-editable-folder-observation-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("fixture_id", summary)
        self.assertNotIn("source_research_notes", summary)

    def test_reports_expected_observation_findings(self) -> None:
        summary = build_editable_folder_observation_summary(
            _load_input(),
            workspace_root=WORKSPACE,
        )
        observations_by_path = {
            item["workspace_path"]: item for item in summary["file_observations"]
        }

        self.assertEqual(
            observations_by_path["readout-rerun-0001/code/readout_calibration_entrypoint.py"][
                "finding"
            ],
            "same_observed",
        )
        self.assertEqual(
            observations_by_path["readout-rerun-0001/code/experiment_session_setup.py"]["finding"],
            "changed_observed",
        )
        self.assertEqual(
            observations_by_path["readout-rerun-0001/code/secrets/device_config.py"]["finding"],
            "skipped_redacted",
        )
        self.assertEqual(
            observations_by_path["readout-rerun-0001/code/helpers/lab_local_driver.py"]["finding"],
            "unavailable_reference",
        )
        self.assertEqual(
            observations_by_path["readout-rerun-0001/notes/manual_tuning_note.md"]["finding"],
            "extra_observed",
        )

    def test_observation_summary_counts_findings_without_semantic_claims(self) -> None:
        summary = build_editable_folder_observation_summary(
            _load_input(),
            workspace_root=WORKSPACE,
        )
        request = summary["observation_requests"][0]
        changed = [
            item for item in summary["file_observations"] if item["finding"] == "changed_observed"
        ][0]
        extra = [
            item for item in summary["file_observations"] if item["finding"] == "extra_observed"
        ][0]

        self.assertEqual(request["expected_path_count"], 4)
        self.assertEqual(request["extra_path_count"], 1)
        self.assertEqual(request["observed_content_path_count"], 3)
        self.assertEqual(
            request["finding_counts"],
            {
                "changed_observed": 1,
                "extra_observed": 1,
                "same_observed": 1,
                "skipped_redacted": 1,
                "unavailable_reference": 1,
            },
        )
        self.assertEqual(changed["does_not_claim"], "semantic_source_diff_or_change_cause")
        self.assertEqual(extra["does_not_claim"], "generated_artifact_dependency_or_user_intent")

    def test_attention_records_boundary_deferrals(self) -> None:
        summary = build_editable_folder_observation_summary(
            _load_input(),
            workspace_root=WORKSPACE,
        )
        source = _load_input()

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            source["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["observation_policy"]["code_execution"] = "performed_elsewhere"

        with self.assertRaisesRegex(ValueError, "code_execution"):
            build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["observation_policy"]["dependency_sync"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected editable folder observation"):
            build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

        source["observation_policy"]["content_observation"] = "mutated"
        source["managed_code_versions"][0]["stable_identity"]["stable_id"] = "mutated"

        self.assertEqual(
            summary["observation_policy"]["content_observation"],
            "sha256_and_size_only",
        )
        self.assertEqual(
            summary["selected_versions"][0]["stable_identity"]["stable_id"],
            "sc-codever-readout-0001",
        )

    def test_duplicate_materialization_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][1]["materialization_path"] = (
            "code/readout_calibration_entrypoint.py"
        )

        with self.assertRaisesRegex(ValueError, "duplicate materialization paths"):
            build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

    def test_file_paths_must_be_relative(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["path"] = "/private/path.py"

        with self.assertRaisesRegex(ValueError, "non-relative file path"):
            build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

    def test_workspace_root_must_be_relative(self) -> None:
        source = _load_input()
        source["observation_requests"][0]["workspace_reference"]["root_path"] = "/tmp/outside"

        with self.assertRaisesRegex(ValueError, "root path must be relative"):
            build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

    def test_content_captured_files_require_integrity_hint(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0].pop("content_state")

        with self.assertRaisesRegex(ValueError, "require content_state"):
            build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

    def test_non_content_available_files_must_not_carry_integrity_hint(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][2]["content_state"] = {
            "digest_algorithm": "sha256",
            "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "size_bytes": 1,
            "observed_at": "2026-05-21T12:00:00Z",
        }

        with self.assertRaisesRegex(ValueError, "must not carry content_state"):
            build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

    def test_expected_symlink_target_is_not_followed(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            shutil.copytree(WORKSPACE, workspace_root, dirs_exist_ok=True)
            target = (
                workspace_root / "readout-rerun-0001" / "code" / "readout_calibration_entrypoint.py"
            )
            target.unlink()
            target.symlink_to("redirected.py")

            summary = build_editable_folder_observation_summary(
                source,
                workspace_root=workspace_root,
            )
            observations_by_path = {
                item["workspace_path"]: item for item in summary["file_observations"]
            }

            self.assertEqual(
                observations_by_path["readout-rerun-0001/code/readout_calibration_entrypoint.py"][
                    "finding"
                ],
                "target_is_symlink",
            )
            self.assertTrue(target.is_symlink())
            self.assertFalse((target.parent / "redirected.py").exists())

    def test_missing_request_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "request root must be an existing directory"):
                build_editable_folder_observation_summary(
                    _load_input(),
                    workspace_root=Path(temp_dir),
                )

    def test_unrequested_managed_versions_are_not_reported_as_selected(self) -> None:
        source = _load_input()
        extra_version = copy.deepcopy(source["managed_code_versions"][0])
        extra_version["version_id"] = "managed-code-version-not-selected"
        extra_version["stable_identity"]["stable_id"] = "sc-codever-not-selected"
        source["managed_code_versions"].append(extra_version)

        summary = build_editable_folder_observation_summary(source, workspace_root=WORKSPACE)

        self.assertEqual(
            [item["version_id"] for item in summary["selected_versions"]],
            ["managed-code-version-readout-0001"],
        )

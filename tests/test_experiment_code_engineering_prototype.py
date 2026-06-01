from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.experiment_code import (
    EditableFolderObservationRequest,
    ExperimentCodeRecordingRequest,
    ManagedCodeVersionRequest,
    ReferenceBasedRerunPreparationRequest,
    WorkspaceMaterializationIntentRequest,
    WorkspaceMaterializationRequest,
    build_editable_folder_observation_summary,
    build_experiment_code_recording_summary,
    build_managed_code_version_summary,
    build_reference_based_rerun_preparation_summary,
    build_workspace_materialization_intent_summary,
    execute_workspace_materialization,
    materialize_workspace,
    observe_editable_folder,
    plan_workspace_materialization,
    prepare_reference_based_rerun,
    summarize_experiment_code_recording,
    summarize_managed_code_version,
)

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_summary(path: Path) -> dict:
    return _read_json(path)["candidate_summary"]


def _precreate_declared_existing_targets(workspace_root: Path, source: dict) -> None:
    for request in source["materialization_requests"]:
        for target_path in request["preexisting_target_paths"]:
            path = workspace_root / target_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("existing session setup\n", encoding="utf-8")


def _snapshot_regular_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if not path.is_symlink() and path.is_file()
    }


class ExperimentCodeEngineeringPrototypeTest(unittest.TestCase):
    def test_recording_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = (
            ROOT / "tests" / "fixtures" / "experiment_code_recording" / "basic_step_code_record"
        )
        source = _read_json(fixture / "code-recording-input.json")
        request = ExperimentCodeRecordingRequest.from_dict(source)
        result = summarize_experiment_code_recording(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(fixture / "expected-code-recording-summary.json"),
        )
        self.assertEqual(
            result.recorded_code_contexts[0]["context_id"],
            "code-context-readout-cali-0001",
        )
        self.assertEqual(build_experiment_code_recording_summary(source), result.to_dict())

    def test_managed_version_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "managed_code_version" / "basic_record"
        source = _read_json(fixture / "managed-code-version-input.json")
        request = ManagedCodeVersionRequest.from_dict(source)
        result = summarize_managed_code_version(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(fixture / "expected-managed-code-version-summary.json"),
        )
        self.assertEqual(result.managed_code_versions[0]["file_count"], 3)
        self.assertEqual(build_managed_code_version_summary(source), result.to_dict())

    def test_materialization_intent_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "workspace_materialization_intent" / "basic_plan"
        source = _read_json(fixture / "workspace-materialization-intent-input.json")
        request = WorkspaceMaterializationIntentRequest.from_dict(source)
        result = plan_workspace_materialization(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(fixture / "expected-workspace-materialization-intent-summary.json"),
        )
        self.assertEqual(
            result.materialization_requests[0]["request_id"],
            "materialize-intent-readout-0001",
        )
        self.assertEqual(build_workspace_materialization_intent_summary(source), result.to_dict())

    def test_approved_materialization_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "workspace_materialization" / "basic_workspace"
        source = _read_json(fixture / "workspace-materialization-input.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            _precreate_declared_existing_targets(workspace_root, source)
            request = WorkspaceMaterializationRequest.from_dict(
                source,
                content_root=fixture / "managed_content",
                workspace_root=workspace_root,
            )
            result = execute_workspace_materialization(request)

            self.assertEqual(
                result.to_dict(),
                _candidate_summary(fixture / "expected-workspace-materialization-summary.json"),
            )
            self.assertEqual(result.file_results[0]["result"], "written")
            self.assertEqual(
                materialize_workspace(
                    source,
                    content_root=fixture / "managed_content",
                    workspace_root=workspace_root,
                )["materialization_requests"][0]["result_counts"]["skipped_existing_target"],
                2,
            )

    def test_editable_observation_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "editable_folder_observation" / "basic_observation"
        source = _read_json(fixture / "editable-folder-observation-input.json")
        request = EditableFolderObservationRequest.from_dict(
            source,
            workspace_root=fixture / "workspace",
        )
        result = observe_editable_folder(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(fixture / "expected-editable-folder-observation-summary.json"),
        )
        self.assertEqual(result.observation_requests[0]["extra_path_count"], 1)
        self.assertEqual(
            build_editable_folder_observation_summary(
                source,
                workspace_root=fixture / "workspace",
            ),
            result.to_dict(),
        )

    def test_reference_based_rerun_typed_api_matches_validated_candidate_output(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "reference_based_rerun_preparation" / "basic_rerun"
        source = _read_json(fixture / "rerun-preparation-input.json")
        request = ReferenceBasedRerunPreparationRequest.from_dict(source)
        result = prepare_reference_based_rerun(request)

        self.assertEqual(
            result.to_dict(),
            _candidate_summary(fixture / "expected-rerun-preparation-summary.json"),
        )
        self.assertEqual(
            result.rerun_preparations[0]["preparation_claim"],
            "manual_rerun_seed_summary_only",
        )
        self.assertEqual(build_reference_based_rerun_preparation_summary(source), result.to_dict())

    def test_summary_shape_regression_covers_accepted_chain(self) -> None:
        cases = [
            (
                "recording",
                build_experiment_code_recording_summary,
                ROOT
                / "tests"
                / "fixtures"
                / "experiment_code_recording"
                / "basic_step_code_record"
                / "code-recording-input.json",
                [
                    "recording_policy",
                    "recorded_code_contexts",
                    "code_snapshot_records",
                    "attention",
                ],
            ),
            (
                "managed",
                build_managed_code_version_summary,
                ROOT
                / "tests"
                / "fixtures"
                / "managed_code_version"
                / "basic_record"
                / "managed-code-version-input.json",
                [
                    "managed_version_policy",
                    "managed_code_versions",
                    "file_inventory",
                    "attention",
                ],
            ),
            (
                "intent",
                build_workspace_materialization_intent_summary,
                ROOT
                / "tests"
                / "fixtures"
                / "workspace_materialization_intent"
                / "basic_plan"
                / "workspace-materialization-intent-input.json",
                [
                    "materialization_policy",
                    "selected_versions",
                    "materialization_requests",
                    "file_plans",
                    "attention",
                ],
            ),
        ]
        for label, builder, path, required_keys in cases:
            with self.subTest(label=label):
                summary = builder(_read_json(path))
                for key in required_keys:
                    self.assertIn(key, summary)

    def test_malformed_input_is_rejected_at_typed_request_boundary(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "managed_code_version" / "basic_record"
        source = _read_json(fixture / "managed-code-version-input.json")
        source["managed_code_versions"][0]["file_records"][0]["path"] = "/private/path.py"

        with self.assertRaisesRegex(ValueError, "non-relative file path"):
            ManagedCodeVersionRequest.from_dict(source)

    def test_materialization_blocked_path_does_not_write_any_file(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "workspace_materialization" / "basic_workspace"
        source = _read_json(fixture / "workspace-materialization-input.json")
        source["materialization_requests"][0]["preexisting_target_paths"] = []
        source["managed_code_versions"][0]["file_inventory"][1]["content_state"]["digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            request = WorkspaceMaterializationRequest.from_dict(
                source,
                content_root=fixture / "managed_content",
                workspace_root=workspace_root,
            )

            with self.assertRaisesRegex(ValueError, "digest does not match"):
                execute_workspace_materialization(request)

            self.assertEqual(_snapshot_regular_files(workspace_root), {})

    def test_editable_observation_is_read_only(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "editable_folder_observation" / "basic_observation"
        source = _read_json(fixture / "editable-folder-observation-input.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            shutil.copytree(fixture / "workspace", workspace_root, dirs_exist_ok=True)
            before = _snapshot_regular_files(workspace_root)

            observe_editable_folder(
                EditableFolderObservationRequest.from_dict(source, workspace_root=workspace_root)
            )

            self.assertEqual(_snapshot_regular_files(workspace_root), before)

    def test_reference_rerun_rejects_context_continuity_mismatch(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "reference_based_rerun_preparation" / "basic_rerun"
        source = _read_json(fixture / "rerun-preparation-input.json")
        source["rerun_preparations"][0]["selected_contexts"][1]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "references missing selected context"):
            ReferenceBasedRerunPreparationRequest.from_dict(source)

    def test_result_properties_do_not_alias_internal_summary(self) -> None:
        fixture = (
            ROOT / "tests" / "fixtures" / "experiment_code_recording" / "basic_step_code_record"
        )
        result = summarize_experiment_code_recording(
            ExperimentCodeRecordingRequest.from_dict(
                _read_json(fixture / "code-recording-input.json")
            )
        )
        contexts = list(result.recorded_code_contexts)
        contexts[0]["context_id"] = "mutated"

        self.assertEqual(
            result.recorded_code_contexts[0]["context_id"],
            "code-context-readout-cali-0001",
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.workspace_materialization import materialize_workspace

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "workspace_materialization" / "basic_workspace"
CONTENT_ROOT = FIXTURE / "managed_content"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "workspace-materialization-input.json").read_text(encoding="utf-8")
    )


def _precreate_collision(workspace_root: Path) -> Path:
    collision = workspace_root / "readout-rerun-0001" / "code" / "experiment_session_setup.py"
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_text("existing session setup\n", encoding="utf-8")
    return collision


class WorkspaceMaterializationSummaryCandidateTest(unittest.TestCase):
    def test_materializes_expected_workspace_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            collision = _precreate_collision(workspace_root)

            summary = materialize_workspace(
                _load_input(),
                content_root=CONTENT_ROOT,
                workspace_root=workspace_root,
            )
            expected = json.loads(
                (FIXTURE / "expected-workspace-materialization-summary.json").read_text(
                    encoding="utf-8"
                )
            )["candidate_summary"]

            self.assertEqual(summary, expected)
            self.assertEqual(collision.read_text(encoding="utf-8"), "existing session setup\n")
            self.assertEqual(
                (
                    workspace_root
                    / "readout-rerun-0001"
                    / "code"
                    / "readout_calibration_entrypoint.py"
                ).read_text(encoding="utf-8"),
                (CONTENT_ROOT / "readout_calibration_entrypoint.py").read_text(encoding="utf-8"),
            )
            self.assertFalse(
                (
                    workspace_root / "readout-rerun-0001" / "code" / "secrets" / "device_config.py"
                ).exists()
            )
            self.assertFalse(
                (
                    workspace_root
                    / "readout-rerun-0001"
                    / "code"
                    / "helpers"
                    / "lab_local_driver.py"
                ).exists()
            )

    def test_without_collision_writes_all_available_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)

            summary = materialize_workspace(
                _load_input(),
                content_root=CONTENT_ROOT,
                workspace_root=workspace_root,
            )
            request = summary["materialization_requests"][0]

            self.assertEqual(request["written_file_count"], 2)
            self.assertEqual(request["bytes_written"], 301)
            self.assertEqual(
                request["result_counts"],
                {
                    "skipped_redacted": 1,
                    "unavailable": 1,
                    "written": 2,
                },
            )
            self.assertTrue(
                (
                    workspace_root / "readout-rerun-0001" / "code" / "experiment_session_setup.py"
                ).is_file()
            )

    def test_attention_records_all_boundary_deferrals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = materialize_workspace(
                _load_input(),
                content_root=CONTENT_ROOT,
                workspace_root=Path(temp_dir),
            )

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            _load_input()["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["materialization_policy"]["code_execution"] = "performed_elsewhere"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "code_execution"):
                materialize_workspace(
                    source,
                    content_root=CONTENT_ROOT,
                    workspace_root=Path(temp_dir),
                )

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["materialization_policy"]["dependency_sync"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected workspace materialization"):
                materialize_workspace(
                    source,
                    content_root=CONTENT_ROOT,
                    workspace_root=Path(temp_dir),
                )

    def test_materialization_requires_approval(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["approval"]["approval_state"] = "proposed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must be approved"):
                materialize_workspace(
                    source,
                    content_root=CONTENT_ROOT,
                    workspace_root=Path(temp_dir),
                )

    def test_declared_digest_must_match_content_before_write(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["content_state"]["digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "digest does not match"):
                materialize_workspace(
                    source,
                    content_root=CONTENT_ROOT,
                    workspace_root=workspace_root,
                )

            self.assertFalse(
                (
                    workspace_root
                    / "readout-rerun-0001"
                    / "code"
                    / "readout_calibration_entrypoint.py"
                ).exists()
            )

    def test_duplicate_materialization_paths_are_rejected(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][1]["materialization_path"] = (
            "code/readout_calibration_entrypoint.py"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "duplicate materialization paths"):
                materialize_workspace(
                    source,
                    content_root=CONTENT_ROOT,
                    workspace_root=Path(temp_dir),
                )

    def test_content_refs_must_be_relative(self) -> None:
        source = _load_input()
        source["managed_code_versions"][0]["file_inventory"][0]["content_ref"] = "../outside.py"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "content refs must be relative"):
                materialize_workspace(
                    source,
                    content_root=CONTENT_ROOT,
                    workspace_root=Path(temp_dir),
                )

    def test_destination_root_must_be_relative(self) -> None:
        source = _load_input()
        source["materialization_requests"][0]["destination"]["root_path"] = "/tmp/outside"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "destination root path must be relative"):
                materialize_workspace(
                    source,
                    content_root=CONTENT_ROOT,
                    workspace_root=Path(temp_dir),
                )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()

        with tempfile.TemporaryDirectory() as temp_dir:
            summary = materialize_workspace(
                source,
                content_root=CONTENT_ROOT,
                workspace_root=Path(temp_dir),
            )

        source["materialization_policy"]["workspace_creation"] = "mutated"
        source["managed_code_versions"][0]["stable_identity"]["stable_id"] = "mutated"

        self.assertEqual(
            summary["materialization_policy"]["workspace_creation"],
            "approved_write_to_target_workspace",
        )
        self.assertEqual(
            summary["selected_versions"][0]["stable_identity"]["stable_id"],
            "sc-codever-readout-0001",
        )

    def test_unrequested_managed_versions_are_not_reported_as_selected(self) -> None:
        source = _load_input()
        extra_version = copy.deepcopy(source["managed_code_versions"][0])
        extra_version["version_id"] = "managed-code-version-not-selected"
        extra_version["stable_identity"]["stable_id"] = "sc-codever-not-selected"
        source["managed_code_versions"].append(extra_version)

        with tempfile.TemporaryDirectory() as temp_dir:
            summary = materialize_workspace(
                source,
                content_root=CONTENT_ROOT,
                workspace_root=Path(temp_dir),
            )

        self.assertEqual(
            [item["version_id"] for item in summary["selected_versions"]],
            ["managed-code-version-readout-0001"],
        )

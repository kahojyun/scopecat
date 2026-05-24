from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.environment_file_observation import observe_environment_files

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "environment_file_observation" / "basic_manifest_observation"
)
WORKSPACE_ROOT = FIXTURE / "workspace"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "environment-file-observation-input.json").read_text(encoding="utf-8")
    )


def _set_expected_file_facts(file_record: dict, path: Path) -> None:
    content = path.read_bytes()
    file_record["expected_digest"] = f"sha256:{hashlib.sha256(content).hexdigest()}"
    file_record["expected_size_bytes"] = len(content)


class EnvironmentFileObservationSummaryCandidateTest(unittest.TestCase):
    def test_observes_expected_environment_files_without_sync(self) -> None:
        summary = observe_environment_files(_load_input(), workspace_root=WORKSPACE_ROOT)
        expected = json.loads(
            (FIXTURE / "expected-environment-file-observation-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertEqual(
            (WORKSPACE_ROOT / "env" / "uv.lock").read_text(encoding="utf-8"),
            'version = 1\nrequires-python = ">=3.11,<3.13"\n',
        )

    def test_pyproject_summary_keeps_dependency_resolution_out_of_scope(self) -> None:
        summary = observe_environment_files(_load_input(), workspace_root=WORKSPACE_ROOT)
        pyproject = summary["observed_files"][0]

        self.assertEqual(pyproject["parsed_summary"]["project_name"], "qa-chevron-calibration")
        self.assertEqual(pyproject["parsed_summary"]["dependency_names"], ["numpy", "qcodes"])
        self.assertEqual(pyproject["parsed_summary"]["dependency_group_names"], ["analysis", "lab"])
        self.assertEqual(
            pyproject["parsed_summary"]["does_not_claim"],
            "dependency_resolution_or_runtime_compatibility",
        )
        self.assertEqual(
            summary["environment_file_observation_policy"]["dependency_sync"],
            "not_performed",
        )

    def test_attention_records_all_boundary_deferrals(self) -> None:
        summary = observe_environment_files(_load_input(), workspace_root=WORKSPACE_ROOT)

        self.assertEqual(
            [item["code"] for item in summary["attention"]],
            _load_input()["attention_expected"],
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["environment_file_observation_policy"]["dependency_sync"] = "performed"

        with self.assertRaisesRegex(ValueError, "dependency_sync"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["environment_file_observation_policy"]["runtime_ready"] = True

        with self.assertRaisesRegex(ValueError, "expected environment file observation"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

        source["environment_file_observation_policy"]["dependency_sync"] = "mutated"
        source["environment_record"]["scope"]["managed_code_version_id"] = "mutated"
        source["environment_record"]["environment_claims"]["readiness_claim"] = "ready"

        self.assertEqual(
            summary["environment_file_observation_policy"]["dependency_sync"],
            "not_performed",
        )
        self.assertEqual(
            summary["environment_record"]["scope"]["managed_code_version_id"],
            "managed-code-version-chevron-qA-current",
        )
        self.assertEqual(
            summary["environment_record"]["environment_claims"]["readiness_claim"],
            "not_checked",
        )

    def test_unavailable_environment_file_is_reported_as_review_finding(self) -> None:
        source = _load_input()
        source["observation_request"]["declared_files"][0]["relative_path"] = "env/missing.toml"

        summary = observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

        self.assertEqual(
            summary["environment_record"]["classification"],
            "environment_files_unavailable_for_review",
        )
        self.assertEqual(summary["observed_files"][0]["status"], "unavailable")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["environment_file_unavailable"],
        )

    def test_empty_declared_file_request_is_rejected(self) -> None:
        source = _load_input()
        source["observation_request"]["declared_files"] = []

        with self.assertRaisesRegex(ValueError, "at least one declared file"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_digest_mismatch_is_reported_without_dependency_operation(self) -> None:
        source = _load_input()
        source["observation_request"]["declared_files"][0]["expected_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        summary = observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

        self.assertEqual(
            summary["environment_record"]["classification"],
            "environment_files_observed_with_mismatch",
        )
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["environment_file_digest_mismatch"],
        )
        self.assertEqual(
            summary["review_findings"][0]["does_not_claim"],
            "dependency_resolution_or_file_repair",
        )

    def test_size_mismatch_is_reported(self) -> None:
        source = _load_input()
        source["observation_request"]["declared_files"][1]["expected_size_bytes"] = 99

        summary = observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["environment_file_size_mismatch"],
        )

    def test_declared_paths_must_stay_relative(self) -> None:
        cases = [
            "../pyproject.toml",
            "/private/pyproject.toml",
            "C:/lab/pyproject.toml",
            "env\\pyproject.toml",
        ]

        for path in cases:
            with self.subTest(path=path):
                source = _load_input()
                source["observation_request"]["declared_files"][0]["relative_path"] = path

                with self.assertRaisesRegex(ValueError, "declared environment file path"):
                    observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_expected_digest_must_be_sha256_prefixed(self) -> None:
        source = _load_input()
        source["observation_request"]["declared_files"][0]["expected_digest"] = "caa918"

        with self.assertRaisesRegex(ValueError, "sha256-prefixed"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_expected_size_must_be_strict_nonnegative_integer(self) -> None:
        cases = [True, -1, 5.5]

        for value in cases:
            with self.subTest(value=value):
                source = _load_input()
                source["observation_request"]["declared_files"][0]["expected_size_bytes"] = value

                with self.assertRaisesRegex(ValueError, "expected_size_bytes"):
                    observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_duplicate_file_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["observation_request"]["declared_files"][0])
        source["observation_request"]["declared_files"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate file_id"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_managed_identifiers_must_stay_public_safe(self) -> None:
        cases = [
            ("environment_record", "environment_id", "/private/env"),
            ("observation_request", "request_id", "../request"),
        ]

        for section, field, value in cases:
            with self.subTest(section=section, field=field):
                source = _load_input()
                source[section][field] = value

                with self.assertRaisesRegex(ValueError, "managed identifier"):
                    observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

        source = _load_input()
        source["observation_request"]["declared_files"][0]["file_id"] = "env/pyproject"

        with self.assertRaisesRegex(ValueError, "managed identifier"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

        for scope_key in [
            "managed_code_version_id",
            "editable_workspace_id",
            "prepared_run_context_id",
        ]:
            with self.subTest(scope_key=scope_key):
                source = _load_input()
                source["environment_record"]["scope"][scope_key] = f"../{scope_key}"

                with self.assertRaisesRegex(ValueError, "managed identifier"):
                    observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_workspace_root_label_must_not_be_path_like(self) -> None:
        cases = [
            "/private/workspace",
            "C:/lab/workspace",
            "lab\\workspace",
            "",
        ]

        for label in cases:
            with self.subTest(label=label):
                source = _load_input()
                source["observation_request"]["workspace_root_label"] = label

                with self.assertRaisesRegex(ValueError, "workspace_root_label"):
                    observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_environment_claim_shape_must_stay_non_operational(self) -> None:
        source = _load_input()
        source["environment_record"]["environment_claims"]["readiness_claim"] = "ready"

        with self.assertRaisesRegex(ValueError, "readiness_claim"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_unsupported_role_format_pair_is_rejected(self) -> None:
        source = _load_input()
        source["observation_request"]["declared_files"][0]["format"] = "uv_lock"

        with self.assertRaisesRegex(ValueError, "modern_python_manifest"):
            observe_environment_files(source, workspace_root=WORKSPACE_ROOT)

    def test_target_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            target = workspace_root / "env" / "pyproject.toml"
            target.parent.mkdir(parents=True)
            target.symlink_to("redirected.toml")

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                observe_environment_files(source, workspace_root=workspace_root)

            self.assertTrue(target.is_symlink())
            self.assertFalse((target.parent / "redirected.toml").exists())

    def test_workspace_root_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            real_workspace = temp_root / "real-workspace"
            real_workspace.mkdir()
            linked_workspace = temp_root / "linked-workspace"
            linked_workspace.symlink_to(real_workspace, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "workspace root must not be a symlink"):
                observe_environment_files(source, workspace_root=linked_workspace)

            self.assertTrue(linked_workspace.is_symlink())

    def test_parent_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            outside = workspace_root / "outside"
            outside.mkdir()
            env = workspace_root / "env"
            env.symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                observe_environment_files(source, workspace_root=workspace_root)

            self.assertTrue(env.is_symlink())

    def test_pyproject_parse_uses_declared_manifest_only(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            pyproject = workspace_root / "env" / "pyproject.toml"
            lockfile = workspace_root / "env" / "uv.lock"
            pyproject.parent.mkdir(parents=True)
            pyproject.write_text(
                (
                    "[project]\n"
                    'name = "minimal"\n'
                    'requires-python = ">=3.12"\n'
                    "dependencies = []\n"
                    "\n"
                    "[dependency-groups]\n"
                    "lab = []\n"
                ),
                encoding="utf-8",
            )
            lockfile.write_text("version = 1\n", encoding="utf-8")
            _set_expected_file_facts(source["observation_request"]["declared_files"][0], pyproject)
            _set_expected_file_facts(source["observation_request"]["declared_files"][1], lockfile)

            summary = observe_environment_files(source, workspace_root=workspace_root)

        self.assertEqual(summary["observed_files"][0]["parsed_summary"]["project_name"], "minimal")
        self.assertEqual(summary["observed_files"][0]["parsed_summary"]["dependency_names"], [])
        self.assertIsNone(summary["observed_files"][1]["parsed_summary"])

    def test_malformed_pyproject_reports_parse_finding_without_losing_file_facts(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            pyproject = workspace_root / "env" / "pyproject.toml"
            lockfile = workspace_root / "env" / "uv.lock"
            pyproject.parent.mkdir(parents=True)
            pyproject.write_text("[project\nname = broken\n", encoding="utf-8")
            lockfile.write_text("version = 1\n", encoding="utf-8")
            _set_expected_file_facts(source["observation_request"]["declared_files"][0], pyproject)
            _set_expected_file_facts(source["observation_request"]["declared_files"][1], lockfile)

            summary = observe_environment_files(source, workspace_root=workspace_root)

        observed = summary["observed_files"][0]
        self.assertEqual(
            summary["environment_record"]["classification"],
            "environment_files_observed_with_review_findings",
        )
        self.assertEqual(summary["observed_files"][0]["status"], "observed")
        self.assertEqual(observed["observed_digest"], observed["expected_digest"])
        self.assertEqual(observed["observed_size_bytes"], observed["expected_size_bytes"])
        self.assertIsNone(observed["parsed_summary"])
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["environment_file_parse_failed"],
        )

    def test_invalid_dependency_entries_are_not_emitted_as_dependency_names(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            pyproject = workspace_root / "env" / "pyproject.toml"
            lockfile = workspace_root / "env" / "uv.lock"
            pyproject.parent.mkdir(parents=True)
            pyproject.write_text(
                (
                    "[project]\n"
                    'name = "minimal"\n'
                    'dependencies = ["numpy==1.26", "../private-wheel.whl", '
                    '"https://example.invalid/pkg.whl", '
                    '"private_pkg @ file:///private/pkg.whl", '
                    '"internal-name @ https://example.invalid/pkg.whl"]\n'
                ),
                encoding="utf-8",
            )
            lockfile.write_text("version = 1\n", encoding="utf-8")
            _set_expected_file_facts(source["observation_request"]["declared_files"][0], pyproject)
            _set_expected_file_facts(source["observation_request"]["declared_files"][1], lockfile)

            summary = observe_environment_files(source, workspace_root=workspace_root)

        self.assertEqual(
            summary["observed_files"][0]["parsed_summary"]["dependency_names"], ["numpy"]
        )
        self.assertEqual(
            summary["observed_files"][0]["parsed_summary"]["skipped_dependency_entry_count"],
            4,
        )

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from implementation_candidates.modern_manifest_preflight import (
    build_modern_manifest_preflight_summary,
)
from implementation_candidates.modern_manifest_preflight.contracts import (
    EXPECTED_POLICY,
    POLICY_ATTENTION_MATRIX,
    validate_modern_manifest_preflight_contract,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "modern_manifest_preflight" / "basic_pyproject_preflight"
WORKSPACE_ROOT = FIXTURE / "workspace"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "modern-manifest-preflight-input.json").read_text(encoding="utf-8")
    )


def _set_expected_groups(source: dict, groups: list[str]) -> None:
    source["preflight_request"]["expected_dependency_groups"] = list(groups)
    source["declared_environment"]["modern_python_environment"]["dependency_groups"] = list(groups)


def _write_pyproject(root: Path, content: str) -> None:
    project = root / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(content, encoding="utf-8")


class ModernManifestPreflightSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_modern_manifest_preflight_summary(
            _load_input(), workspace_root=WORKSPACE_ROOT
        )
        expected = json.loads(
            (FIXTURE / "expected-modern-manifest-preflight-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_preflight_reads_only_approved_pyproject_manifest(self) -> None:
        summary = build_modern_manifest_preflight_summary(
            _load_input(), workspace_root=WORKSPACE_ROOT
        )
        manifest = summary["manifest_summary"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["preflight_status"], "manifest_preflight_has_review_findings")
        self.assertEqual(manifest["status"], "parsed")
        self.assertEqual(
            (WORKSPACE_ROOT / "project" / "uv.lock").read_text(encoding="utf-8"),
            'poison = "valid TOML-shaped lockfile fixture; manifest preflight must not read this file"\n',
        )
        self.assertEqual(manifest["requires_python_status"], "declared")
        self.assertEqual(manifest["dependency_names"], ["numpy", "qcodes"])
        self.assertEqual(manifest["skipped_dependency_entry_count"], 1)
        self.assertEqual(manifest["dependency_group_names"], ["default", "analysis"])
        self.assertEqual(manifest["dependency_group_shapes"], {"analysis": "declared_list"})
        self.assertEqual(
            attention["lockfile_read_not_performed"]["does_not_claim"],
            "locked_dependency_graph",
        )
        self.assertEqual(
            attention["dependency_sync_not_performed"]["does_not_claim"],
            "synchronized_environment",
        )

    def test_preflight_does_not_open_declared_lockfile_path(self) -> None:
        source = _load_input()
        _set_expected_groups(source, ["default"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_pyproject(
                root,
                "\n".join(
                    [
                        "[project]",
                        'name = "qa-chevron-calibration"',
                        'requires-python = ">=3.11"',
                        "dependencies = []",
                        "",
                    ]
                ),
            )
            (root / "project" / "uv.lock").mkdir()

            summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(summary["manifest_summary"]["status"], "parsed")
        self.assertEqual(summary["manifest_summary"]["requires_python_status"], "declared")

    def test_preflight_path_open_is_limited_to_approved_pyproject(self) -> None:
        source = _load_input()
        _set_expected_groups(source, ["default"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_pyproject(
                root,
                "\n".join(
                    [
                        "[project]",
                        'name = "qa-chevron-calibration"',
                        'requires-python = ">=3.11"',
                        "dependencies = []",
                        "",
                    ]
                ),
            )
            (root / "project" / "uv.lock").write_text("not toml", encoding="utf-8")
            allowed = (root / "project" / "pyproject.toml").resolve()
            forbidden = (root / "project" / "uv.lock").resolve()
            opened_paths = []
            original_open = Path.open

            def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
                opened_paths.append(path.resolve())
                if path.resolve() == forbidden:
                    raise AssertionError("modern manifest preflight opened the lockfile")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", guarded_open):
                summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(summary["manifest_summary"]["status"], "parsed")
        self.assertEqual(opened_paths, [allowed])

    def test_policy_attention_matrix_covers_explicit_policy_boundaries(self) -> None:
        expected_policy_keys = {
            "summary_policy",
            "lockfile_read",
            "dependency_resolution",
            "dependency_sync",
            "package_install",
            "runtime_probe",
            "code_import_execution",
            "hardware_probe",
            "readiness_claim",
            "shared_environment_schema",
        }
        matrix_policy_keys = {row["policy_key"] for row in POLICY_ATTENTION_MATRIX}
        matrix_codes = [row["code"] for row in POLICY_ATTENTION_MATRIX]

        self.assertEqual(matrix_policy_keys, expected_policy_keys)
        self.assertEqual(len(matrix_codes), len(set(matrix_codes)))
        for row in POLICY_ATTENTION_MATRIX:
            with self.subTest(policy_key=row["policy_key"]):
                self.assertEqual(EXPECTED_POLICY[row["policy_key"]], row["policy_value"])
                self.assertIn(row["severity"], {"info", "review"})
                self.assertTrue(row["basis"])
                self.assertTrue(row["does_not_claim"])

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["modern_manifest_preflight_policy"]["dependency_sync"] = "performed"

        with self.assertRaisesRegex(ValueError, "dependency_sync"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_extra_or_missing_source_shape_is_rejected(self) -> None:
        source = _load_input()
        source["dependency_sync_result"] = {}

        with self.assertRaisesRegex(ValueError, "source"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        source = _load_input()
        del source["preflight_request"]

        with self.assertRaisesRegex(ValueError, "source"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_preflight_requires_explicit_approved_operation(self) -> None:
        source = _load_input()
        source["preflight_request"]["approved_operation"] = "dependency_sync"

        with self.assertRaisesRegex(ValueError, "approved_operation"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_request_must_match_declared_context(self) -> None:
        source = _load_input()
        source["preflight_request"]["manifest_path"] = "other/pyproject.toml"

        with self.assertRaisesRegex(ValueError, "declared pyproject path"):
            validate_modern_manifest_preflight_contract(source)

    def test_preflight_manifest_path_must_name_pyproject_toml(self) -> None:
        source = _load_input()
        source["preflight_request"]["manifest_path"] = "project/uv.lock"
        source["declared_environment"]["modern_python_environment"]["pyproject_path"] = (
            "project/uv.lock"
        )

        with self.assertRaisesRegex(ValueError, "pyproject.toml"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_pyproject_path_must_differ_from_lockfile_path(self) -> None:
        source = _load_input()
        source["declared_environment"]["modern_python_environment"]["lockfile_path"] = (
            "project/pyproject.toml"
        )

        with self.assertRaisesRegex(ValueError, "differ from lockfile_path"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_declared_environment_scope_must_match_prepared_context(self) -> None:
        source = _load_input()
        source["declared_environment"]["scope"]["prepared_run_context_id"] = (
            "prepared-run-context-chevron-qA-other"
        )

        with self.assertRaisesRegex(ValueError, "scope"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_manifest_paths_must_stay_relative(self) -> None:
        cases = [
            "../pyproject.toml",
            "/private/pyproject.toml",
            "C:/lab/pyproject.toml",
            "project\\pyproject.toml",
        ]
        for path in cases:
            with self.subTest(path=path):
                source = _load_input()
                source["preflight_request"]["manifest_path"] = path
                source["declared_environment"]["modern_python_environment"]["pyproject_path"] = path

                with self.assertRaisesRegex(ValueError, "relative"):
                    build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_workspace_root_must_not_be_symlink(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            real_root = base / "real"
            real_root.mkdir()
            symlink_root = base / "workspace-link"
            symlink_root.symlink_to(real_root, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "root must not be a symlink"):
                build_modern_manifest_preflight_summary(source, workspace_root=symlink_root)

    def test_preflight_rejects_symlink_parent_or_manifest_target(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            outside = base / "outside"
            outside.mkdir()
            (outside / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            root = base / "workspace"
            root.mkdir()
            (root / "project").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                build_modern_manifest_preflight_summary(source, workspace_root=root)

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            outside_manifest = base / "outside-pyproject.toml"
            outside_manifest.write_text("[project]\n", encoding="utf-8")
            root = base / "workspace"
            project = root / "project"
            project.mkdir(parents=True)
            (project / "pyproject.toml").symlink_to(outside_manifest)

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                build_modern_manifest_preflight_summary(source, workspace_root=root)

    def test_preflight_rejects_non_directory_parent(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "project").write_text("not a directory", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parent is not a directory"):
                build_modern_manifest_preflight_summary(source, workspace_root=root)

    def test_workspace_root_label_must_not_be_path_like(self) -> None:
        source = _load_input()
        source["preflight_request"]["workspace_root_label"] = "/private/workspace"

        with self.assertRaisesRegex(ValueError, "workspace_root_label"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_dependency_groups_must_match_declared_environment(self) -> None:
        source = _load_input()
        source["preflight_request"]["expected_dependency_groups"] = ["default", "analysis"]

        with self.assertRaisesRegex(ValueError, "dependency groups"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_duplicate_dependency_groups_are_rejected(self) -> None:
        source = _load_input()
        source["declared_environment"]["modern_python_environment"]["dependency_groups"] = [
            "default",
            "lab",
            "lab",
        ]

        with self.assertRaisesRegex(ValueError, "duplicate dependency group"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_nested_contract_shapes_are_exact(self) -> None:
        cases = [
            ("preflight_request", "dependency_sync_result"),
            ("prepared_run_context", "runtime_probe"),
            ("declared_environment", "managed_runner"),
        ]
        for section, extra_key in cases:
            with self.subTest(section=section):
                source = _load_input()
                source[section][extra_key] = "claimed"

                with self.assertRaisesRegex(ValueError, "expected shape"):
                    build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        source = _load_input()
        source["declared_environment"]["environment_claims"]["runtime_ready"] = "claimed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        source = _load_input()
        source["declared_environment"]["modern_python_environment"]["resolver"] = "uv"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        missing_cases = [
            ("prepared_run_context", "scope", "managed_code_version_id"),
            ("declared_environment", "environment_claims", "readiness_claim"),
            ("declared_environment", "modern_python_environment", "manifest_state"),
        ]
        for section, nested_section, missing_key in missing_cases:
            with self.subTest(
                section=section, nested_section=nested_section, missing_key=missing_key
            ):
                source = _load_input()
                del source[section][nested_section][missing_key]

                with self.assertRaisesRegex(ValueError, "expected shape"):
                    build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_declared_environment_enums_and_claims_are_bounded(self) -> None:
        cases = [
            ("authority", "runtime_observed", "authority"),
            ("record_status", "ready", "record_status"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["declared_environment"][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        source = _load_input()
        source["declared_environment"]["environment_claims"]["sync_claim"] = "synced"

        with self.assertRaisesRegex(ValueError, "sync_claim"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        source = _load_input()
        source["declared_environment"]["modern_python_environment"]["python_version_source"] = (
            "runtime_probe"
        )

        with self.assertRaisesRegex(ValueError, "python_version_source"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        source = _load_input()
        source["declared_environment"]["modern_python_environment"]["manifest_state"] = "observed"

        with self.assertRaisesRegex(ValueError, "manifest_state"):
            build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

    def test_manifest_requires_python_must_be_declared_and_simple_specifier(self) -> None:
        cases = [
            (
                '[project]\nname = "qa-chevron-calibration"\ndependencies = []\n',
                None,
            ),
            (
                '[project]\nname = "qa-chevron-calibration"\nrequires-python = "not a specifier"\ndependencies = []\n',
                "not a specifier",
            ),
            (
                '[project]\nname = "qa-chevron-calibration"\nrequires-python = ">=banana"\ndependencies = []\n',
                ">=banana",
            ),
            (
                '[project]\nname = "qa-chevron-calibration"\nrequires-python = ">=..."\ndependencies = []\n',
                ">=...",
            ),
            (
                '[project]\nname = "qa-chevron-calibration"\nrequires-python = ">=*"\ndependencies = []\n',
                ">=*",
            ),
            (
                '[project]\nname = "qa-chevron-calibration"\nrequires-python = "==*"\ndependencies = []\n',
                "==*",
            ),
            (
                '[project]\nname = "qa-chevron-calibration"\nrequires-python = "~=3"\ndependencies = []\n',
                "~=3",
            ),
        ]
        for content, expected_value in cases:
            with self.subTest(expected_value=expected_value):
                source = _load_input()
                _set_expected_groups(source, ["default"])
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    _write_pyproject(root, content)

                    summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

                self.assertEqual(summary["manifest_summary"]["requires_python"], expected_value)
                self.assertEqual(
                    summary["manifest_summary"]["requires_python_status"],
                    "missing_or_malformed",
                )
                self.assertIn(
                    "requires_python_missing_or_malformed",
                    [finding["code"] for finding in summary["preflight_findings"]],
                )

    def test_manifest_requires_python_accepts_simple_numeric_specifiers(self) -> None:
        source = _load_input()
        _set_expected_groups(source, ["default"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_pyproject(
                root,
                "\n".join(
                    [
                        "[project]",
                        'name = "qa-chevron-calibration"',
                        'requires-python = ">=3.11,!=3.12.*,<3.13"',
                        "dependencies = []",
                        "",
                    ]
                ),
            )

            summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(summary["manifest_summary"]["requires_python_status"], "declared")

    def test_malformed_dependency_group_value_is_review_finding(self) -> None:
        source = _load_input()
        _set_expected_groups(source, ["default", "lab"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_pyproject(
                root,
                "\n".join(
                    [
                        "[project]",
                        'name = "qa-chevron-calibration"',
                        'requires-python = ">=3.11"',
                        "dependencies = []",
                        "",
                        "[dependency-groups]",
                        'lab = "not a list"',
                        "",
                    ]
                ),
            )

            summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(
            summary["manifest_summary"]["dependency_group_shapes"],
            {"lab": "malformed_value"},
        )
        self.assertEqual(
            summary["dependency_group_checks"][1]["state"],
            "missing_from_manifest",
        )
        self.assertIn(
            "dependency_group_malformed",
            [finding["code"] for finding in summary["preflight_findings"]],
        )

    def test_dependency_entry_summary_handles_markers_extras_duplicates_and_direct_refs(
        self,
    ) -> None:
        source = _load_input()
        _set_expected_groups(source, ["default", "analysis"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_pyproject(
                root,
                "\n".join(
                    [
                        "[project]",
                        'name = "qa-chevron-calibration"',
                        'requires-python = ">=3.11,<3.13"',
                        "dependencies = [",
                        '  "requests[security]>=2; python_version >= \\"3.11\\"",',
                        '  "numpy==1.26.4",',
                        '  "numpy>=1",',
                        '  "qa-lab-tools @ ./synthetic-wheel.whl",',
                        "]",
                        "",
                        "[dependency-groups]",
                        'analysis = ["scipy>=1.11"]',
                        "",
                    ]
                ),
            )

            summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(summary["manifest_summary"]["dependency_names"], ["numpy", "requests"])
        self.assertEqual(summary["manifest_summary"]["skipped_dependency_entry_count"], 1)

    def test_non_list_project_dependencies_are_not_summarized_as_default_group(self) -> None:
        source = _load_input()
        _set_expected_groups(source, ["default"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_pyproject(
                root,
                "\n".join(
                    [
                        "[project]",
                        'name = "qa-chevron-calibration"',
                        'requires-python = ">=3.11"',
                        'dependencies = "not a list"',
                        "",
                    ]
                ),
            )

            summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(summary["manifest_summary"]["dependency_names"], [])
        self.assertEqual(summary["manifest_summary"]["skipped_dependency_entry_count"], 0)
        self.assertEqual(summary["manifest_summary"]["dependency_group_names"], [])
        self.assertEqual(
            summary["dependency_group_checks"][0]["state"],
            "missing_from_manifest",
        )

    def test_invalid_dependency_group_names_are_ignored(self) -> None:
        source = _load_input()
        _set_expected_groups(source, ["default"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_pyproject(
                root,
                "\n".join(
                    [
                        "[project]",
                        'name = "qa-chevron-calibration"',
                        'requires-python = ">=3.11"',
                        "dependencies = []",
                        "",
                        "[dependency-groups]",
                        '"not a safe group" = ["pytest"]',
                        "",
                    ]
                ),
            )

            summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(summary["manifest_summary"]["dependency_group_names"], ["default"])
        self.assertEqual(summary["manifest_summary"]["dependency_group_shapes"], {})

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        source["modern_manifest_preflight_policy"]["dependency_sync"] = "mutated"
        source["preflight_request"]["expected_dependency_groups"].append("mutated")
        source["prepared_run_context"]["scope"]["managed_code_version_id"] = "mutated"

        self.assertEqual(
            summary["modern_manifest_preflight_policy"]["dependency_sync"], "not_performed"
        )
        self.assertEqual(
            summary["preflight_request"]["expected_dependency_groups"],
            ["default", "analysis", "lab"],
        )
        self.assertEqual(
            summary["prepared_run_context"]["scope"]["managed_code_version_id"],
            "managed-code-version-chevron-qA-current",
        )

    def test_missing_manifest_is_review_finding_not_sync_decision(self) -> None:
        source = _load_input()
        source["preflight_request"]["manifest_path"] = "missing/pyproject.toml"
        source["declared_environment"]["modern_python_environment"]["pyproject_path"] = (
            "missing/pyproject.toml"
        )

        summary = build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        self.assertEqual(summary["preflight_status"], "manifest_unavailable_for_preflight")
        self.assertEqual(summary["manifest_summary"]["status"], "unavailable")
        self.assertEqual(summary["preflight_findings"][0]["code"], "manifest_unavailable")
        self.assertEqual(
            summary["preflight_findings"][0]["does_not_claim"],
            "environment_repair_or_dependency_sync",
        )

    def test_parse_failed_manifest_is_review_finding_not_runtime_decision(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project\n", encoding="utf-8")

            summary = build_modern_manifest_preflight_summary(source, workspace_root=root)

        self.assertEqual(summary["preflight_status"], "manifest_parse_failed_for_preflight")
        self.assertEqual(summary["manifest_summary"]["status"], "parse_failed")
        self.assertEqual(summary["preflight_findings"][0]["code"], "manifest_parse_failed")
        self.assertEqual(
            summary["preflight_findings"][0]["does_not_claim"],
            "dependency_resolution_or_runtime_compatibility",
        )

    def test_passed_declared_checks_still_does_not_claim_readiness(self) -> None:
        source = _load_input()
        source["preflight_request"]["expected_dependency_groups"] = ["default", "analysis"]
        source["declared_environment"]["modern_python_environment"]["dependency_groups"] = [
            "default",
            "analysis",
        ]

        summary = build_modern_manifest_preflight_summary(source, workspace_root=WORKSPACE_ROOT)

        self.assertEqual(summary["preflight_status"], "manifest_preflight_passed_declared_checks")
        self.assertEqual(summary["preflight_findings"], [])
        self.assertEqual(
            summary["attention"][-2]["does_not_claim"],
            "run_can_start",
        )

    def test_expected_output_records_review_summary_boundary_metadata(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-modern-manifest-preflight-summary.json").read_text(
                encoding="utf-8"
            )
        )
        guard = expected["reference_semantics"]["contract_guard"]
        attention_not_claims = {
            item["does_not_claim"] for item in expected["candidate_summary"]["attention"]
        }
        decisions_not_earned = set(expected["decisions_not_earned"])
        boundary_notes = " ".join(expected["boundary_notes"])

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(
            expected["candidate_summary"]["modern_manifest_preflight_policy"]["summary_policy"],
            "review_summary",
        )
        for phrase in [
            "not an environment manager",
            "package resolver",
            "dependency sync operation",
            "package installation step",
            "lockfile parser",
            "runtime probe",
            "code import",
            "execution step",
            "hardware check",
            "shared environment schema",
            "managed runner",
            "run-blocking decision",
            "runnable-readiness claim",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guard)
        self.assertEqual(
            attention_not_claims,
            {
                "environment_operation_beyond_manifest_preflight",
                "locked_dependency_graph",
                "resolved_environment",
                "synchronized_environment",
                "installed_environment",
                "runtime_available_or_compatible",
                "execution_permission",
                "control_pc_or_hardware_ready",
                "run_can_start",
                "shared_environment_schema",
            },
        )
        for decision in [
            "lockfile parsing",
            "dependency resolution",
            "dependency sync",
            "package installation",
            "runtime readiness",
            "code import",
            "code execution",
            "hardware readiness",
            "managed runner",
            "run-blocking decisions",
            "runnable readiness",
            "shared environment schema",
        ]:
            with self.subTest(decision=decision):
                self.assertIn(decision, decisions_not_earned)
        for phrase in [
            "does not read lockfiles",
            "not dependency resolution",
            "does not claim dependency resolution",
            "run-start readiness",
        ]:
            with self.subTest(boundary_phrase=phrase):
                self.assertIn(phrase, boundary_notes)


if __name__ == "__main__":
    unittest.main()

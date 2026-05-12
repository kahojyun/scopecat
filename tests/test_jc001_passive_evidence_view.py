import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "jc001-layered-config-bundle"
EXPECTED_SHAPE = FIXTURE / "expected-shape.json"
MINIMAL_FIXTURE = ROOT / "tests" / "fixtures" / "jc001-minimal-unknown"
MINIMAL_EXPECTED_SHAPE = MINIMAL_FIXTURE / "expected-shape.json"
PROTOTYPE = ROOT / "prototypes" / "jc001_passive_evidence_view.py"


def load_prototype():
    spec = importlib.util.spec_from_file_location("jc001_passive_evidence_view", PROTOTYPE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture_hashes(fixture=FIXTURE):
    hashes = {}
    for path in sorted(fixture.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(fixture).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def assert_expected_shape(test_case, prototype, fixture, expected_shape_path):
    expected = json.loads(expected_shape_path.read_text(encoding="utf-8"))
    view = prototype.build_evidence_view(fixture)
    markdown = prototype.render_markdown(view)

    conflict_types = sorted(
        item["conflict_type"] for item in view["conflict_and_missing_fact_report"]["conflicts"]
    )
    missing_fact_types = sorted(
        item["fact_type"] for item in view["conflict_and_missing_fact_report"]["missing_facts"]
    )

    test_case.assertEqual(view["static_shape_checks"]["artifact_count"], expected["artifact_count"])
    test_case.assertEqual(view["static_shape_checks"]["role_counts"], expected["role_counts"])
    test_case.assertEqual(view["static_shape_checks"]["relation_types"], expected["relation_types"])
    test_case.assertEqual(conflict_types, expected["conflict_types"])
    test_case.assertEqual(missing_fact_types, expected["missing_fact_types"])
    test_case.assertEqual(
        view["readiness_hint_summary"]["status"],
        expected["readiness_hint_status"],
    )
    for section in expected["markdown_sections"]:
        test_case.assertIn(section, markdown)
    return view, markdown


class PassiveEvidenceViewTest(unittest.TestCase):
    def test_builds_expected_evidence_view_without_mutating_fixture(self):
        prototype = load_prototype()
        before = fixture_hashes()

        view = prototype.build_evidence_view(FIXTURE)

        self.assertEqual(before, fixture_hashes())
        self.assertEqual(view["bundle_summary"]["bundle_id"], "jc001-layered-config-bundle")
        self.assertEqual(view["static_shape_checks"]["artifact_count"], 10)
        self.assertEqual(len(view["artifact_role_inventory"]), 10)

        roles = {artifact["role"] for artifact in view["artifact_role_inventory"]}
        self.assertGreaterEqual(
            roles,
            {
                "anchor",
                "selected context",
                "generated sidecar",
                "copied snapshot",
                "variant",
                "code reference",
                "setup evidence",
            },
        )

        relation_types = {relation["relation_type"] for relation in view["relations"]}
        self.assertGreaterEqual(
            relation_types,
            {
                "anchors",
                "appears-selected-for",
                "generated-from",
                "copied-from",
                "references-code",
                "has-variant",
                "has-backup",
                "missing-fact",
                "conflicts-with",
                "redacts",
            },
        )

        self.assertGreaterEqual(len(view["conflict_and_missing_fact_report"]["conflicts"]), 3)
        self.assertEqual(view["readiness_hint_summary"]["readiness_hints"], [])
        self.assertEqual(view["readiness_hint_summary"]["status"], "no static readiness hints observed")
        missing_types = {
            item["fact_type"] for item in view["conflict_and_missing_fact_report"]["missing_facts"]
        }
        self.assertGreaterEqual(
            missing_types,
            {
                "preferred anchor",
                "selected settings authority",
                "generated sidecar freshness",
                "snapshot coverage",
                "code identity",
            },
        )
        self.assertNotIn("source-of-record", json.dumps(view))

    def test_evidence_view_matches_expected_shape_snapshot(self):
        prototype = load_prototype()
        assert_expected_shape(self, prototype, FIXTURE, EXPECTED_SHAPE)

    def test_minimal_unknown_fixture_preserves_absence_and_unknowns(self):
        prototype = load_prototype()
        before = fixture_hashes(MINIMAL_FIXTURE)

        view, markdown = assert_expected_shape(
            self,
            prototype,
            MINIMAL_FIXTURE,
            MINIMAL_EXPECTED_SHAPE,
        )

        self.assertEqual(before, fixture_hashes(MINIMAL_FIXTURE))
        self.assertEqual(view["bundle_summary"]["bundle_id"], "jc001-minimal-unknown")
        self.assertEqual(view["generated_and_copied_relation_summary"]["generated_sidecars"], [])
        self.assertEqual(view["generated_and_copied_relation_summary"]["copied_snapshots"], [])
        self.assertEqual(view["variant_backup_unknown_summary"]["unknown_artifacts"], ["notes__context-note_txt"])
        self.assertEqual(view["readiness_hint_summary"]["readiness_hints"], ["readiness__static-environment_json"])
        self.assertEqual(
            view["readiness_hint_summary"]["readiness_hint_details"],
            [
                {
                    "readiness_hint_id": "readiness__static-environment_json",
                    "source_artifact": "readiness__static-environment_json",
                    "category": "dependency/environment",
                    "evidence_handling": "observed",
                    "suggested_next_check": "Review dependency or environment evidence without executing fixture code.",
                }
            ],
        )
        self.assertIn("Generated sidecars: none observed", markdown)
        self.assertIn("Copied snapshots: none observed", markdown)
        self.assertIn("Unknown artifacts: `notes__context-note_txt`", markdown)
        self.assertIn("Readiness hints: `readiness__static-environment_json`", markdown)

    def test_cli_writes_json_and_markdown_outputs(self):
        before = fixture_hashes()
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = subprocess.run(
                [sys.executable, str(PROTOTYPE), str(FIXTURE), "--out-dir", tmp_dir],
                check=True,
                capture_output=True,
                text=True,
            )

            output_dir = Path(tmp_dir)
            json_path = output_dir / "evidence-view.json"
            markdown_path = output_dir / "evidence-view.md"

            self.assertIn("evidence-view.json", result.stdout)
            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())

            view = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertEqual(view["bundle_summary"]["bundle_id"], "jc001-layered-config-bundle")
            self.assertIn("## Conflict And Missing-Fact Report", markdown)
            self.assertIn("not executed", markdown)
            self.assertIn("Readiness hints: none observed", markdown)

        self.assertEqual(before, fixture_hashes())

    def test_cli_rejects_output_directory_inside_fixture(self):
        before = fixture_hashes()
        result = subprocess.run(
            [sys.executable, str(PROTOTYPE), str(FIXTURE), "--out-dir", str(FIXTURE / "out")],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("output directory must be outside the input fixture directory", result.stderr)
        self.assertEqual(before, fixture_hashes())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_manifest_artifact_symlink_cannot_escape_fixture(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir, tempfile.TemporaryDirectory() as external_dir:
            fixture_path = Path(fixture_dir)
            external_path = Path(external_dir) / "outside.json"
            write_json(external_path, {"outside": True})
            (fixture_path / "leak.json").symlink_to(external_path)
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "symlink-fixture",
                    "purpose": "symlink escape regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "leak.json",
                            "role": "anchor",
                            "status": "symlink",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "manifest artifact escapes fixture directory: leak.json",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_same_shape_value_drift_remains_visible(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "parameters.json", {"alpha": "root"})
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "value-drift-fixture",
                    "purpose": "same-shape drift regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "parameters.json",
                            "role": "anchor",
                            "status": "root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/parameters.json",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        conflict_types = {
            item["conflict_type"] for item in view["conflict_and_missing_fact_report"]["conflicts"]
        }
        self.assertIn("value-drift", conflict_types)

    def test_unlisted_declared_source_is_missing_not_observed(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            write_json(
                fixture_path / "setting" / "temp" / "derived.json",
                {"generated_from": "setting/missing-source.json"},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "unlisted-source-fixture",
                    "purpose": "unlisted source regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "setting/parameters.json",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/temp/derived.json",
                            "role": "generated sidecar",
                            "status": "generated candidate",
                            "evidence_handling": "generated",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        generated_relations = [
            item for item in view["relations"] if item["relation_type"] == "generated-from"
        ]
        self.assertEqual(len(generated_relations), 1)
        self.assertEqual(generated_relations[0]["evidence_handling"], "missing")
        self.assertIn("declared-source-unlisted", generated_relations[0]["flags"])
        self.assertEqual(generated_relations[0]["target_artifact"], "unlisted-source-fixture")

    def test_cli_returns_clear_error_for_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as fixture_dir, tempfile.TemporaryDirectory() as out_dir:
            fixture_path = Path(fixture_dir)
            manifest = {
                "fixture_id": "bad-fixture",
                "purpose": "invalid manifest fixture",
                "redaction_policy": {
                    "source": "public-test-fixture",
                    "forbidden_content": [],
                },
                "artifacts": [
                    {
                        "path": "missing.json",
                        "role": "anchor",
                        "status": "missing",
                        "evidence_handling": "observed",
                        "sharing_boundary": "public-safe",
                    }
                ],
            }
            (fixture_path / "fixture-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(PROTOTYPE), str(fixture_path), "--out-dir", out_dir],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("manifest artifact does not exist: missing.json", result.stderr)


if __name__ == "__main__":
    unittest.main()

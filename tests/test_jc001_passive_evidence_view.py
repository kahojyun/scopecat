import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


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
    if "relation_counts" in expected:
        relation_counts = {}
        for relation in view["relations"]:
            relation_counts[relation["relation_type"]] = (
                relation_counts.get(relation["relation_type"], 0) + 1
            )
        test_case.assertEqual(relation_counts, expected["relation_counts"])
    for expected_relation in expected.get("required_relations", []):
        matches = [
            relation
            for relation in view["relations"]
            if relation["relation_type"] == expected_relation["relation_type"]
            and relation["source_artifact"] == expected_relation["source_artifact"]
            and relation["target_artifact"] == expected_relation["target_artifact"]
        ]
        test_case.assertEqual(
            len(matches),
            1,
            f"missing expected relation {expected_relation}",
        )
        relation = matches[0]
        if "evidence_handling" in expected_relation:
            test_case.assertEqual(
                relation["evidence_handling"],
                expected_relation["evidence_handling"],
            )
        for flag in expected_relation.get("flags", []):
            test_case.assertIn(flag, relation["flags"])
        row_prefix = (
            f"| {expected_relation['relation_type']} | "
            f"`{expected_relation['source_artifact']}` | "
            f"`{expected_relation['target_artifact']}` | "
            f"{relation['evidence_handling']} |"
        )
        markdown_rows = [line for line in markdown.splitlines() if line.startswith(row_prefix)]
        test_case.assertEqual(len(markdown_rows), 1)
        cells = [cell.strip() for cell in markdown_rows[0].strip("|").split("|")]
        test_case.assertEqual(len(cells), 6)
        test_case.assertTrue(cells[4], f"missing reason cell in {markdown_rows[0]}")
        for flag in expected_relation.get("flags", []):
            test_case.assertIn(flag, cells[5])
    test_case.assertEqual(conflict_types, expected["conflict_types"])
    test_case.assertEqual(missing_fact_types, expected["missing_fact_types"])
    test_case.assertEqual(
        view["readiness_hint_summary"]["status"],
        expected["readiness_hint_status"],
    )
    for section in expected["markdown_sections"]:
        test_case.assertIn(section, markdown)
    for snippet in expected.get("markdown_contains", []):
        test_case.assertIn(snippet, markdown)
    return view, markdown


def relation_by_type_and_source(view, relation_type, source_artifact):
    matches = [
        relation
        for relation in view["relations"]
        if relation["relation_type"] == relation_type
        and relation["source_artifact"] == source_artifact
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one {relation_type} relation from {source_artifact}, got {len(matches)}"
        )
    return matches[0]


class PassiveEvidenceViewTest(unittest.TestCase):
    def test_builds_expected_evidence_view_without_mutating_fixture(self):
        prototype = load_prototype()
        before = fixture_hashes()

        view = prototype.build_evidence_view(FIXTURE)

        self.assertEqual(before, fixture_hashes())
        self.assertEqual(view["bundle_summary"]["bundle_id"], "wbq")
        self.assertEqual(view["bundle_summary"]["sharing_boundary"], "public-safe")
        self.assertEqual(
            view["bundle_summary"]["redaction_policy_source"],
            "public-safe redaction policy source retained in fixture",
        )
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
        chip_relation = relation_by_type_and_source(
            view,
            "generated-from",
            "zp",
        )
        self.assertEqual(chip_relation["target_artifact"], "nr")
        self.assertEqual(chip_relation["evidence_handling"], "observed")
        self.assertIn("freshness-unchecked", chip_relation["flags"])

        line_relation = relation_by_type_and_source(
            view,
            "generated-from",
            "lt",
        )
        self.assertEqual(line_relation["target_artifact"], "nr")
        self.assertEqual(line_relation["evidence_handling"], "observed")
        self.assertIn("freshness-unchecked", line_relation["flags"])

        snapshot_relation = relation_by_type_and_source(
            view,
            "copied-from",
            "ky",
        )
        self.assertEqual(snapshot_relation["target_artifact"], "nr")
        self.assertEqual(snapshot_relation["evidence_handling"], "observed")
        self.assertIn("partial-snapshot", snapshot_relation["flags"])

        self.assertEqual(view["readiness_hint_summary"]["readiness_hints"], [])
        self.assertEqual(view["readiness_hint_summary"]["status"], "no static readiness hints observed")
        missing_types = {
            item["fact_type"] for item in view["conflict_and_missing_fact_report"]["missing_facts"]
        }
        self.assertGreaterEqual(
            missing_types,
            {
                "preferred anchor",
                "selected settings provenance",
                "generated sidecar freshness",
                "snapshot coverage",
                "code identity",
            },
        )
        missing_relations_by_type = {}
        for relation in view["relations"]:
            if relation["relation_type"] == "missing-fact":
                missing_relations_by_type.setdefault(relation["flags"][0], set()).add(
                    relation["source_artifact"]
                )
        self.assertGreaterEqual(
            missing_relations_by_type["generated sidecar freshness"],
            {"zp", "lt"},
        )
        self.assertGreaterEqual(
            missing_relations_by_type["code identity"],
            {"yx", "uj"},
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
        self.assertEqual(view["bundle_summary"]["bundle_id"], "wbx")
        self.assertEqual(view["generated_and_copied_relation_summary"]["generated_sidecars"], [])
        self.assertEqual(view["generated_and_copied_relation_summary"]["copied_snapshots"], [])
        self.assertEqual(view["variant_backup_unknown_summary"]["unknown_artifacts"], ["nr"])
        self.assertEqual(view["readiness_hint_summary"]["readiness_hints"], ["hm"])
        self.assertEqual(
            view["readiness_hint_summary"]["readiness_hint_details"],
            [
                {
                    "readiness_hint_id": "hm",
                    "source_artifact": "hm",
                    "category": "dependency/environment",
                    "evidence_handling": "observed",
                    "suggested_next_check": "Review dependency or environment evidence without executing fixture code.",
                }
            ],
        )
        self.assertIn("Generated sidecars: none observed", markdown)
        self.assertIn("Copied snapshots: none observed", markdown)
        self.assertIn("Unknown artifacts: `nr`", markdown)
        self.assertIn("Readiness hints: `hm`", markdown)

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
            self.assertEqual(view["bundle_summary"]["bundle_id"], "wbq")
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
                    "public_bundle_id": "wb",
                    "purpose": "symlink escape regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "leak.json",
                            "public_id": "qa",
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

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_fixture_manifest_symlink_cannot_escape_fixture(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir, tempfile.TemporaryDirectory() as external_dir:
            fixture_path = Path(fixture_dir)
            external_manifest = Path(external_dir) / "fixture-manifest.json"
            write_json(
                external_manifest,
                {
                    "fixture_id": "manifest-symlink-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "manifest symlink regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [],
                },
            )
            (fixture_path / "fixture-manifest.json").symlink_to(external_manifest)

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "fixture manifest escapes fixture directory",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_generated_artifact_id_collisions_are_rejected(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "a" / "b.json", {"value": "nested"})
            write_json(fixture_path / "a__b.json", {"value": "flat"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "id-collision-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "artifact ID collision regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "a/b.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "nested",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "a__b.json",
                            "public_id": "vx",
                            "role": "selected context",
                            "status": "flat",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "duplicate generated artifact ID: a__b_json from a/b.json and a__b.json",
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
                    "public_bundle_id": "wb",
                    "purpose": "same-shape drift regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "parameters.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/parameters.json",
                            "public_id": "vx",
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

    def test_normalized_root_parameter_path_drives_conflicts(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "parameters.json", {"alpha": "root"})
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "normalized-root-parameter-path-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "normalized root parameter path regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "./parameters.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "./setting/parameters.json",
                            "public_id": "vx",
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
        self.assertEqual(view["artifact_role_inventory"][0]["artifact_id"], "qa")

    def test_non_default_selected_context_path_drives_conflicts(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "parameters.json", {"alpha": "root"})
            write_json(fixture_path / "active" / "context.json", {"alpha": "selected", "beta": "extra"})
            write_json(
                fixture_path / "data" / "snapshot.json",
                {"copied_from": "active/context.json", "alpha": "selected"},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "non-default-selected-context-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "selected context path regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "parameters.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/context.json",
                            "public_id": "vx",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "data/snapshot.json",
                            "public_id": "nr",
                            "role": "copied snapshot",
                            "status": "partial snapshot",
                            "evidence_handling": "copied",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        conflict_types = {
            item["conflict_type"] for item in view["conflict_and_missing_fact_report"]["conflicts"]
        }
        self.assertIn("shape-drift", conflict_types)
        self.assertIn("partial-snapshot", conflict_types)

        snapshot_relation = relation_by_type_and_source(
            view,
            "copied-from",
            "nr",
        )
        self.assertEqual(snapshot_relation["target_artifact"], "vx")
        self.assertEqual(snapshot_relation["evidence_handling"], "observed")

    def test_non_default_setup_context_path_drives_setup_drift(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "registry.json", {"instrument": {"slot": "root"}})
            write_json(
                fixture_path / "active" / "setup.json",
                {"instrument": {"slot": "selected"}, "extra": True},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "non-default-setup-context-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "setup context path regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "registry.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root setup candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/setup.json",
                            "public_id": "vx",
                            "role": "setup evidence",
                            "status": "selected setup candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        conflict = next(
            item
            for item in view["conflict_and_missing_fact_report"]["conflicts"]
            if item["conflict_type"] == "setup-context-drift"
        )
        self.assertEqual(conflict["artifacts"], ["qa", "vx"])

    def test_normalized_root_registry_path_drives_setup_drift(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "registry.json", {"instrument": {"slot": "root"}})
            write_json(
                fixture_path / "setting" / "registry.json",
                {"instrument": {"slot": "selected"}, "extra": True},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "normalized-root-registry-path-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "normalized root registry path regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "./registry.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root setup candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "./setting/registry.json",
                            "public_id": "vx",
                            "role": "setup evidence",
                            "status": "selected setup candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        conflict = next(
            item
            for item in view["conflict_and_missing_fact_report"]["conflicts"]
            if item["conflict_type"] == "setup-context-drift"
        )
        self.assertEqual(conflict["artifacts"], ["qa", "vx"])

    def test_default_setting_registry_fallback_drives_setup_drift(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "registry.json", {"instrument": {"slot": "root"}})
            write_json(
                fixture_path / "setting" / "registry.json",
                {"instrument": {"slot": "selected"}, "extra": True},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "default-setting-registry-fallback-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "default setting registry fallback regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "registry.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root setup candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/registry.json",
                            "public_id": "vx",
                            "role": "selected context",
                            "status": "selected registry candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        conflict = next(
            item
            for item in view["conflict_and_missing_fact_report"]["conflicts"]
            if item["conflict_type"] == "setup-context-drift"
        )
        self.assertEqual(conflict["artifacts"], ["qa", "vx"])

    def test_setting_registry_fallback_ignores_non_context_artifact(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "registry.json", {"instrument": {"slot": "root"}})
            write_json(
                fixture_path / "setting" / "registry.json",
                {"instrument": {"slot": "generated"}, "extra": True},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "non-context-setting-registry-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "non-context setting registry fallback regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "registry.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root setup candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/registry.json",
                            "public_id": "vx",
                            "role": "generated sidecar",
                            "status": "generated registry sidecar",
                            "evidence_handling": "generated",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        conflict_types = {
            item["conflict_type"] for item in view["conflict_and_missing_fact_report"]["conflicts"]
        }
        self.assertNotIn("setup-context-drift", conflict_types)
        self.assertNotIn("setup-value-drift", conflict_types)

    def test_empty_json_drift_remains_visible(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "parameters.json", {})
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "empty-drift-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "empty JSON drift regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "parameters.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "empty root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/parameters.json",
                            "public_id": "vx",
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
        self.assertIn("shape-drift", conflict_types)

    def test_clue_free_code_does_not_strengthen_selected_context_evidence(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            code_path = fixture_path / "code" / "notes.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text("def helper():\n    return 'no context here'\n", encoding="utf-8")
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "clue-free-code-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "code clue regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "setting/parameters.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "code/notes.py",
                            "public_id": "vx",
                            "role": "code reference",
                            "status": "text-only pseudocode",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        self.assertIn(
            "no selected-context code clue",
            view["selected_context_explanation"]["selection_evidence"],
        )
        selected_relation = relation_by_type_and_source(
            view,
            "appears-selected-for",
            "qa",
        )
        self.assertIn("manifest-role-only", selected_relation["flags"])

        code_relation = relation_by_type_and_source(view, "references-code", "vx")
        self.assertEqual(code_relation["target_artifact"], "wb")
        self.assertIn("no-static-context-clue", code_relation["flags"])

    def test_unrelated_setting_code_does_not_strengthen_non_default_selected_context(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "active" / "context.json", {"alpha": "selected"})
            code_path = fixture_path / "code" / "notes.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text("SETTING_PATH = 'setting'\n", encoding="utf-8")
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "unrelated-setting-code-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "path-specific selected context clue regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "active/context.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "code/notes.py",
                            "public_id": "vx",
                            "role": "code reference",
                            "status": "text-only pseudocode",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        selected_relation = relation_by_type_and_source(
            view,
            "appears-selected-for",
            "qa",
        )
        self.assertIn("manifest-role-only", selected_relation["flags"])
        code_relation = relation_by_type_and_source(view, "references-code", "vx")
        self.assertEqual(code_relation["target_artifact"], "wb")
        self.assertIn("no-exact-selected-context-path", code_relation["flags"])

    def test_split_path_tokens_do_not_count_as_exact_selected_context_clue(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "active" / "context.json", {"alpha": "selected"})
            code_path = fixture_path / "code" / "notes.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text(
                "SETTING_PATH = 'setting'\nACTIVE_DIR = 'active'\nDEFAULT_FILE = 'context.json'\n",
                encoding="utf-8",
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "split-path-token-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "split path token regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "active/context.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "code/notes.py",
                            "public_id": "vx",
                            "role": "code reference",
                            "status": "text-only pseudocode",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        selected_relation = relation_by_type_and_source(
            view,
            "appears-selected-for",
            "qa",
        )
        self.assertIn("manifest-role-only", selected_relation["flags"])
        code_relation = relation_by_type_and_source(view, "references-code", "vx")
        self.assertEqual(code_relation["target_artifact"], "wb")
        self.assertIn("no-exact-selected-context-path", code_relation["flags"])

    def test_embedded_backup_path_does_not_count_as_exact_selected_context_clue(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            code_path = fixture_path / "code" / "notes.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text(
                "SETTING_PATH = 'archive/setting/parameters.json.bak'\n",
                encoding="utf-8",
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "embedded-backup-path-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "embedded path token regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "setting/parameters.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "code/notes.py",
                            "public_id": "vx",
                            "role": "code reference",
                            "status": "text-only pseudocode",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        selected_relation = relation_by_type_and_source(
            view,
            "appears-selected-for",
            "qa",
        )
        self.assertIn("manifest-role-only", selected_relation["flags"])
        code_relation = relation_by_type_and_source(view, "references-code", "vx")
        self.assertEqual(code_relation["target_artifact"], "wb")
        self.assertIn("no-exact-selected-context-path", code_relation["flags"])

    def test_local_dot_prefix_counts_as_exact_selected_context_clue(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            code_path = fixture_path / "code" / "notes.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text("SETTING_PATH = './setting/parameters.json'\n", encoding="utf-8")
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "dot-prefixed-path-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "dot-prefixed path regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "setting/parameters.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "code/notes.py",
                            "public_id": "vx",
                            "role": "code reference",
                            "status": "text-only pseudocode",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        selected_relation = relation_by_type_and_source(
            view,
            "appears-selected-for",
            "qa",
        )
        self.assertNotIn("manifest-role-only", selected_relation["flags"])
        code_relation = relation_by_type_and_source(view, "references-code", "vx")
        self.assertEqual(code_relation["target_artifact"], "qa")
        self.assertNotIn("no-exact-selected-context-path", code_relation["flags"])

    def test_multiple_selected_context_candidates_get_relations(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "parameters.json", {"alpha": "root", "beta": "root"})
            write_json(fixture_path / "active" / "context-a.json", {"alpha": "a"})
            write_json(fixture_path / "active" / "context-b.json", {"alpha": "b", "beta": "b"})
            write_json(fixture_path / "data" / "snapshot.json", {"alpha": "copied"})
            code_path = fixture_path / "code" / "notes.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text("SETTING_PATH = 'setting'\n", encoding="utf-8")
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "multi-selected-context-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "multiple selected context regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "parameters.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/context-a.json",
                            "public_id": "vx",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/context-b.json",
                            "public_id": "nr",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "data/snapshot.json",
                            "public_id": "hm",
                            "role": "copied snapshot",
                            "status": "partial snapshot",
                            "evidence_handling": "copied",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "code/notes.py",
                            "public_id": "zp",
                            "role": "code reference",
                            "status": "text-only pseudocode",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)
            markdown = prototype.render_markdown(view)

        selected_relations = [
            item
            for item in view["relations"]
            if item["relation_type"] == "appears-selected-for"
        ]
        self.assertEqual(
            [item["source_artifact"] for item in selected_relations],
            ["vx", "nr"],
        )
        self.assertEqual(
            view["selected_context_explanation"]["selected_context_candidates"],
            ["vx", "nr"],
        )
        self.assertIsNone(view["selected_context_explanation"]["selected_context_candidate"])
        self.assertIn(
            "Selected context candidates: `vx`, `nr`",
            markdown,
        )
        self.assertIn("Selected context candidate: none observed", markdown)
        self.assertIn("`qa`, `vx`", markdown)
        self.assertIn("`vx`, `nr`", markdown)

        conflict_artifacts = [
            item["artifacts"]
            for item in view["conflict_and_missing_fact_report"]["conflicts"]
        ]
        self.assertIn(["qa", "vx"], conflict_artifacts)
        self.assertIn(["qa", "nr"], conflict_artifacts)
        self.assertIn(["hm", "nr"], conflict_artifacts)

        copied_relations = [
            relation
            for relation in view["relations"]
            if relation["relation_type"] == "copied-from"
        ]
        self.assertEqual(
            [relation["target_artifact"] for relation in copied_relations],
            ["vx", "nr"],
        )
        for relation in copied_relations:
            self.assertIn("multiple-selected-context-candidates", relation["flags"])

        code_relation = relation_by_type_and_source(view, "references-code", "zp")
        self.assertEqual(code_relation["target_artifact"], "wb")
        self.assertIn("multiple-selected-context-candidates", code_relation["flags"])
        self.assertIn(
            "Ask which selected-looking context applies, or preserve explicit alternatives.",
            view["next_checks"],
        )

    def test_dot_prefixed_copied_from_routes_partial_snapshot_conflict(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "parameters.json", {"alpha": "root", "beta": "root"})
            write_json(fixture_path / "active" / "context-a.json", {"alpha": "a"})
            write_json(fixture_path / "active" / "context-b.json", {"alpha": "b", "beta": "b"})
            write_json(
                fixture_path / "data" / "snapshot.json",
                {"copied_from": "./active/context-a.json", "alpha": "a"},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "dot-prefixed-copied-source-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "dot-prefixed copied source conflict routing regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "parameters.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/context-a.json",
                            "public_id": "vx",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/context-b.json",
                            "public_id": "nr",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "data/snapshot.json",
                            "public_id": "hm",
                            "role": "copied snapshot",
                            "status": "partial snapshot",
                            "evidence_handling": "copied",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        relation = relation_by_type_and_source(view, "copied-from", "hm")
        self.assertEqual(relation["target_artifact"], "vx")
        conflict_artifacts = [
            item["artifacts"]
            for item in view["conflict_and_missing_fact_report"]["conflicts"]
        ]
        self.assertNotIn(["hm", "nr"], conflict_artifacts)

    def test_canonical_copied_from_routes_partial_snapshot_conflict(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "parameters.json", {"alpha": "root", "beta": "root"})
            write_json(fixture_path / "active" / "context-a.json", {"alpha": "a"})
            write_json(fixture_path / "active" / "context-b.json", {"alpha": "b", "beta": "b"})
            write_json(
                fixture_path / "data" / "snapshot.json",
                {"copied_from": "active/./context-a.json", "alpha": "a"},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "canonical-copied-source-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "canonical copied source conflict routing regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "parameters.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "root candidate",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/context-a.json",
                            "public_id": "vx",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "active/context-b.json",
                            "public_id": "nr",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "data/snapshot.json",
                            "public_id": "hm",
                            "role": "copied snapshot",
                            "status": "partial snapshot",
                            "evidence_handling": "copied",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        relation = relation_by_type_and_source(view, "copied-from", "hm")
        self.assertEqual(relation["target_artifact"], "vx")
        conflict_artifacts = [
            item["artifacts"]
            for item in view["conflict_and_missing_fact_report"]["conflicts"]
        ]
        self.assertNotIn(["hm", "nr"], conflict_artifacts)

    def test_variant_without_backup_does_not_emit_backup_relation(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "variants" / "manifest.json",
                {
                    "fixture": "variant-only-fixture",
                    "entries": [
                        {
                            "name": "no-backup-placeholder",
                            "role": "variant-ambiguity",
                            "included_as_full_file": False,
                        }
                    ],
                },
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "variant-without-backup-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "variant backup relation regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "variants/manifest.json",
                            "public_id": "vx",
                            "role": "variant",
                            "status": "manifest-only ambiguity",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        relation_types = {relation["relation_type"] for relation in view["relations"]}
        self.assertIn("has-variant", relation_types)
        self.assertNotIn("has-backup", relation_types)
        self.assertFalse(view["variant_backup_unknown_summary"]["backup_ambiguity_visible"])

    def test_backup_prefixed_variant_name_emits_backup_relation(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "variants" / "manifest.json",
                {
                    "fixture": "backup-prefix-fixture",
                    "entries": [
                        {
                            "name": "backup-branch-placeholder",
                            "role": "variant-ambiguity",
                            "included_as_full_file": False,
                        }
                    ],
                },
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "backup-prefixed-variant-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "backup prefix relation regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "variants/manifest.json",
                            "public_id": "vx",
                            "role": "variant",
                            "status": "manifest-only ambiguity",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        relation_types = {relation["relation_type"] for relation in view["relations"]}
        self.assertIn("has-backup", relation_types)
        self.assertTrue(view["variant_backup_unknown_summary"]["backup_ambiguity_visible"])

    def test_markdown_redacts_non_public_artifact_labels(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"alpha": "selected"})
            write_json(fixture_path / "private" / "env.json", {"dependency": "private"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "private/secret-fixture",
                    "public_bundle_id": "redacted-work-bundle-a",
                    "purpose": "explain private/secret-settings.json",
                    "redaction_policy": {
                        "source": "private/secret-map.md",
                        "forbidden_content": ["private/secret-settings.json"],
                    },
                    "artifacts": [
                        {
                            "path": "private/secret-settings.json",
                            "public_id": "redacted-selected-context-a",
                            "role": "selected context",
                            "status": "selected from private/secret-settings.json",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        },
                        {
                            "path": "private/env.json",
                            "public_id": "redacted-readiness-hint-a",
                            "role": "readiness hint",
                            "status": "readiness from private/env.json",
                            "evidence_handling": "observed",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)
            markdown = prototype.render_markdown(view)

        selected_id = view["artifact_role_inventory"][0]["artifact_id"]
        readiness_id = view["artifact_role_inventory"][1]["artifact_id"]
        self.assertEqual(view["bundle_summary"]["bundle_id"], "redacted-work-bundle-a")
        self.assertEqual(
            view["bundle_summary"]["redaction_policy_source"],
            "redacted non-public redaction policy source",
        )
        self.assertEqual(selected_id, "redacted-selected-context-a")
        self.assertEqual(readiness_id, "redacted-readiness-hint-a")
        self.assertEqual(view["bundle_summary"]["purpose"], "redacted non-public bundle purpose")
        self.assertEqual(
            view["artifact_role_inventory"][0]["status"],
            "redacted",
        )
        self.assertEqual(
            view["artifact_role_inventory"][1]["status"],
            "redacted",
        )
        replacement_labels = [
            item["public_safe_replacement_label"]
            for item in view["sharing_boundary_summary"]["artifact_boundaries"]
        ]
        self.assertEqual(replacement_labels, [selected_id, readiness_id])
        self.assertEqual(
            view["sharing_boundary_summary"]["forbidden_content_categories"],
            ["redacted non-public forbidden content categories"],
        )
        self.assertIn(f"`{selected_id}`", markdown)
        self.assertIn(f"`{readiness_id}`", markdown)
        self.assertIn("redaction-sensitive", markdown)
        self.assertNotIn("private/secret-settings.json", markdown)
        self.assertNotIn("private__secret-settings_json", markdown)
        self.assertNotIn("private/env.json", markdown)
        self.assertNotIn("private__env_json", markdown)
        serialized_view = json.dumps(view)
        self.assertNotIn("explain private/secret-settings.json", serialized_view)
        self.assertNotIn("private/secret-fixture", serialized_view)
        self.assertNotIn("private/secret-map.md", serialized_view)
        self.assertNotIn("private/secret-settings.json", serialized_view)
        self.assertNotIn("private__secret-settings_json", serialized_view)
        self.assertNotIn("private/env.json", serialized_view)
        self.assertNotIn("private__env_json", serialized_view)

    def test_non_public_artifact_id_is_stable_across_manifest_order(self):
        prototype = load_prototype()
        public_ids = {
            "private/first-settings.json": "redacted-selected-context-a",
            "private/second-settings.json": "redacted-selected-context-b",
        }

        def build_view_with_order(paths: list[str]) -> dict[str, Any]:
            with tempfile.TemporaryDirectory() as fixture_dir:
                fixture_path = Path(fixture_dir)
                for path in paths:
                    write_json(fixture_path / path, {"path": path})
                write_json(
                    fixture_path / "fixture-manifest.json",
                    {
                        "fixture_id": "stable-redaction-id-fixture",
                        "public_bundle_id": "redacted-work-bundle-a",
                        "purpose": "redacted artifact identity stability regression",
                        "redaction_policy": {
                            "source": "public-test-fixture",
                            "forbidden_content": ["raw private paths"],
                        },
                        "artifacts": [
                            {
                                "path": path,
                                "public_id": public_ids[path],
                                "role": "selected context",
                                "status": "private selected candidate",
                                "evidence_handling": "inferred",
                                "sharing_boundary": "redaction-sensitive",
                            }
                            for path in paths
                        ],
                    },
                )
                return prototype.build_evidence_view(fixture_path)

        first_view = build_view_with_order(
            ["private/first-settings.json", "private/second-settings.json"]
        )
        second_view = build_view_with_order(
            ["private/second-settings.json", "private/first-settings.json"]
        )

        first_inventory = first_view["artifact_role_inventory"]
        second_inventory = second_view["artifact_role_inventory"]

        self.assertEqual([item["artifact_id"] for item in first_inventory], list(public_ids.values()))
        self.assertEqual(
            [item["artifact_id"] for item in second_inventory],
            [
                public_ids["private/second-settings.json"],
                public_ids["private/first-settings.json"],
            ],
        )
        self.assertEqual([item["label"] for item in first_inventory], list(public_ids.values()))
        self.assertEqual(
            [item["label"] for item in second_inventory],
            [
                public_ids["private/second-settings.json"],
                public_ids["private/first-settings.json"],
            ],
        )

    def test_non_public_artifact_requires_explicit_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "missing-public-id-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "missing public id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/secret-settings.json",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                r"artifacts\[0\]\.public_id must be a non-empty string",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_non_public_artifact_rejects_source_derived_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "source-derived-public-id-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "source-derived public id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/secret-settings.json",
                            "public_id": "redacted-selected-context-secret1",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_non_public_artifact_rejects_status_derived_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "status-derived-public-id-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "status-derived public id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/settings.json",
                            "public_id": "redacted-selected-context-alpha",
                            "role": "selected context",
                            "status": "alpha candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_bundle_id_rejects_purpose_derived_handle(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "purpose-derived-bundle-id-fixture",
                    "public_bundle_id": "redacted-work-bundle-alpha",
                    "purpose": "alpha handoff",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/settings.json",
                            "public_id": "redacted-selected-context-a",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_bundle_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_non_public_artifact_rejects_payload_derived_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "settings.json", {"secret_label": "qubit"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "payload-derived-public-id-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "payload-derived public id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/settings.json",
                            "public_id": "redacted-selected-context-qubi",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_safe_artifact_rejects_source_derived_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bad" / "path!.json", {"id": "bundle"})
            manifest = {
                "fixture_id": "bad-public-artifact-id-fixture",
                "public_bundle_id": "wb",
                "purpose": "bad public artifact id regression",
                "redaction_policy": {
                    "source": "public-test-fixture",
                    "forbidden_content": [],
                },
                "artifacts": [
                    {
                        "path": "bad/path!.json",
                        "public_id": "bad-path-json",
                        "role": "anchor",
                        "status": "bundle seed",
                        "evidence_handling": "observed",
                        "sharing_boundary": "public-safe",
                    }
                ],
            }
            (fixture_path / "fixture-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_safe_artifact_requires_explicit_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            manifest = {
                "fixture_id": "missing-public-artifact-id-fixture",
                "public_bundle_id": "wb",
                "purpose": "missing public artifact id regression",
                "redaction_policy": {
                    "source": "public-test-fixture",
                    "forbidden_content": [],
                },
                "artifacts": [
                    {
                        "path": "bundle.json",
                        "role": "anchor",
                        "status": "bundle seed",
                        "evidence_handling": "observed",
                        "sharing_boundary": "public-safe",
                    }
                ],
            }
            (fixture_path / "fixture-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                r"artifacts\[0\]\.public_id must be a non-empty string",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_safe_artifact_public_id_is_used_as_public_label(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"id": "bundle"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "public-label-redaction-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "public-safe label regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "private/secret-settings.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)
            markdown = prototype.render_markdown(view)

        self.assertEqual(view["artifact_role_inventory"][0]["label"], "qa")
        self.assertNotIn("private/secret-settings.json", json.dumps(view))
        self.assertNotIn("private__secret-settings_json", json.dumps(view))
        self.assertNotIn("private/secret-settings.json", markdown)
        self.assertNotIn("private__secret-settings_json", markdown)

    def test_tiny_source_metadata_does_not_invalidate_public_id(self):
        prototype = load_prototype()
        self.assertFalse(prototype.contains_source_derived_text("qa", ["a"]))
        prototype.validate_fixture_authored_handle("qa", ["a"], "public_id")

        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "a",
                    "public_bundle_id": "wb",
                    "purpose": "tiny metadata regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        self.assertEqual(view["artifact_role_inventory"][0]["artifact_id"], "qa")

    def test_public_safe_artifact_rejects_path_derived_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"id": "bundle"})
            manifest = {
                "fixture_id": "public-label-redaction-fixture",
                "public_bundle_id": "wb",
                "purpose": "public-safe label regression",
                "redaction_policy": {
                    "source": "public-test-fixture",
                    "forbidden_content": [],
                },
                "artifacts": [
                    {
                        "path": "private/secret-settings.json",
                        "public_id": "private-secret-settings",
                        "role": "anchor",
                        "status": "bundle seed",
                        "evidence_handling": "observed",
                        "sharing_boundary": "public-safe",
                    }
                ],
            }
            (fixture_path / "fixture-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_source_text_redaction_checks_are_hash_seed_stable(self):
        script = "\n".join(
            [
                "import importlib.util",
                "import sys",
                f"prototype_path = {str(PROTOTYPE)!r}",
                "spec = importlib.util.spec_from_file_location("
                "'jc001_passive_evidence_view', prototype_path)",
                "module = importlib.util.module_from_spec(spec)",
                "sys.modules[spec.name] = module",
                "spec.loader.exec_module(module)",
                "print(module.contains_source_derived_text('abcdef', ['abc def']))",
            ]
        )

        for seed in ("1", "5"):
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.check_output(
                [sys.executable, "-c", script],
                env=env,
                text=True,
            ).strip()
            self.assertEqual(result, "True")

        prototype = load_prototype()
        with self.assertRaisesRegex(
            prototype.EvidenceViewError,
            "public_id must not include source-derived text",
        ):
            prototype.validate_fixture_authored_handle("abxycd", ["ab xy cd"], "public_id")

    def test_non_public_artifact_rejects_hash_like_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "hash-like-public-id-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "hash-like public id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/settings.json",
                            "public_id": "redacted-selected-context-a1b2c3d4",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not look hash-derived",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_non_public_artifact_rejects_all_letter_hex_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "letter-hex-public-id-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "letter hex public id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/settings.json",
                            "public_id": "redacted-selected-context-deadbeef",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not look hash-derived",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_non_public_artifact_rejects_partial_source_token_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "partial-source-token-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "partial source token regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/secret-settings.json",
                            "public_id": "redacted-selected-context-secr",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_safe_manifest_metadata_is_not_emitted_verbatim(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "public-metadata-redaction-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "explain private/secret-settings.json",
                    "redaction_policy": {
                        "source": "private/secret-map.md",
                        "forbidden_content": ["private/secret-settings.json"],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)
            markdown = prototype.render_markdown(view)

        serialized_view = json.dumps(view)
        self.assertEqual(
            view["bundle_summary"]["purpose"],
            "public-safe manifest purpose retained in fixture",
        )
        self.assertEqual(
            view["bundle_summary"]["redaction_policy_source"],
            "public-safe redaction policy source retained in fixture",
        )
        self.assertEqual(
            view["sharing_boundary_summary"]["forbidden_content_categories"],
            ["public-safe forbidden content categories retained in fixture"],
        )
        self.assertNotIn("explain private/secret-settings.json", serialized_view)
        self.assertNotIn("private/secret-map.md", serialized_view)
        self.assertNotIn("private/secret-settings.json", serialized_view)
        self.assertNotIn("private/secret-settings.json", markdown)

    def test_public_safe_bundle_rejects_unsafe_fixture_id_without_public_bundle_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "private/secret-fixture",
                    "purpose": "unsafe fixture id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "fixture requires public_bundle_id",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_safe_bundle_rejects_source_derived_public_bundle_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "private-secret-settings-fixture",
                    "public_bundle_id": "private-secret-settings",
                    "purpose": "explain private/secret-settings.json",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["private/secret-settings.json"],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_bundle_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_safe_bundle_rejects_payload_derived_public_bundle_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"secret_label": "qubit"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "payload-derived-public-bundle-id-fixture",
                    "public_bundle_id": "qubit",
                    "purpose": "payload-derived bundle id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "public_bundle_id must not include source-derived text",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_public_safe_artifact_status_is_not_emitted_verbatim(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "status-redaction-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "status redaction regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "selected from private/secret-settings.json",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        self.assertEqual(
            view["artifact_role_inventory"][0]["status"],
            "public-safe",
        )
        self.assertNotIn("private/secret-settings.json", json.dumps(view))

    def test_non_public_bundle_requires_explicit_handle_even_for_slug_fixture_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "private-secret-settings-fixture",
                    "purpose": "sensitive slug fixture id regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "private/secret-settings.json",
                            "public_id": "redacted-selected-context-a",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "fixture requires public_bundle_id",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_follow_on_sharing_boundaries_are_rejected_by_prototype(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "follow-on-boundary-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "follow-on boundary regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "internal-safe",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                r"artifacts\[0\]\.sharing_boundary must be controlled vocabulary",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_role_prefix_does_not_count_as_source_derived_public_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "selected-context.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "role-prefix-overlap-fixture",
                    "public_bundle_id": "redacted-work-bundle-a",
                    "purpose": "role prefix overlap regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/selected-context.json",
                            "public_id": "redacted-selected-context-a",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        self.assertEqual(
            view["artifact_role_inventory"][0]["artifact_id"],
            "redacted-selected-context-a",
        )

    def test_public_artifact_public_id_cannot_reuse_bundle_id(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            manifest = {
                "fixture_id": "bundle-identity-collision-fixture",
                "public_bundle_id": "qa",
                "purpose": "bundle identity reuse regression",
                "redaction_policy": {
                    "source": "public-test-fixture",
                    "forbidden_content": [],
                },
                "artifacts": [
                    {
                        "path": "bundle.json",
                        "public_id": "qa",
                        "role": "anchor",
                        "status": "bundle seed",
                        "evidence_handling": "observed",
                        "sharing_boundary": "public-safe",
                    }
                ],
            }
            (fixture_path / "fixture-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                "artifact ID collides with public bundle ID",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_mixed_artifact_boundaries_promote_to_restrictive_bundle_boundary(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "bundle.json", {"id": "bundle"})
            write_json(fixture_path / "private" / "secret-settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "mixed-boundary-fixture",
                    "public_bundle_id": "redacted-work-bundle-a",
                    "purpose": "mixed boundary regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "bundle.json",
                            "public_id": "qa",
                            "role": "anchor",
                            "status": "bundle seed",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "private/secret-settings.json",
                            "public_id": "redacted-selected-context-a",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "redaction-sensitive",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        self.assertEqual(view["bundle_summary"]["sharing_boundary"], "redaction-sensitive")

    def test_manifest_rejects_uncontrolled_public_vocabulary(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "private" / "secret-settings.json", {"alpha": "selected"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "bad-vocabulary-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "controlled vocabulary regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": ["raw private paths"],
                    },
                    "artifacts": [
                        {
                            "path": "private/secret-settings.json",
                            "public_id": "redacted-selected-context-a",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "copied from private/secret-settings.json",
                            "sharing_boundary": "redaction-sensitive",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(
                prototype.EvidenceViewError,
                r"artifacts\[0\]\.evidence_handling must be controlled vocabulary",
            ):
                prototype.build_evidence_view(fixture_path)

    def test_fixture_authored_role_is_preserved(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "fixture" / "note.json", {"note": "authored for fixture"})
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "fixture-authored-role-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "fixture-authored role regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "fixture/note.json",
                            "public_id": "qa",
                            "role": "fixture-authored",
                            "status": "test-authored note",
                            "evidence_handling": "observed",
                            "sharing_boundary": "public-safe",
                        }
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        self.assertEqual(view["artifact_role_inventory"][0]["role"], "fixture-authored")

    def test_declared_dot_prefixed_source_is_observed(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            write_json(
                fixture_path / "setting" / "temp" / "derived.json",
                {"generated_from": "./setting/parameters.json", "alpha": "derived"},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "dot-prefixed-source-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "declared dot-prefixed source regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "setting/parameters.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/temp/derived.json",
                            "public_id": "vx",
                            "role": "generated sidecar",
                            "status": "generated candidate",
                            "evidence_handling": "generated",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        relation = relation_by_type_and_source(
            view,
            "generated-from",
            "vx",
        )
        self.assertEqual(relation["target_artifact"], "qa")
        self.assertEqual(relation["evidence_handling"], "observed")
        self.assertNotIn("declared-source-unlisted", relation["flags"])

    def test_declared_canonical_source_is_observed(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture_path = Path(fixture_dir)
            write_json(fixture_path / "setting" / "parameters.json", {"alpha": "selected"})
            write_json(
                fixture_path / "setting" / "temp" / "derived.json",
                {"generated_from": "setting/./parameters.json", "alpha": "derived"},
            )
            write_json(
                fixture_path / "fixture-manifest.json",
                {
                    "fixture_id": "canonical-source-fixture",
                    "public_bundle_id": "wb",
                    "purpose": "declared canonical source regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "setting/parameters.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/temp/derived.json",
                            "public_id": "vx",
                            "role": "generated sidecar",
                            "status": "generated candidate",
                            "evidence_handling": "generated",
                            "sharing_boundary": "public-safe",
                        },
                    ],
                },
            )

            view = prototype.build_evidence_view(fixture_path)

        relation = relation_by_type_and_source(
            view,
            "generated-from",
            "vx",
        )
        self.assertEqual(relation["target_artifact"], "qa")
        self.assertEqual(relation["evidence_handling"], "observed")
        self.assertNotIn("declared-source-unlisted", relation["flags"])

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
                    "public_bundle_id": "wb",
                    "purpose": "unlisted source regression",
                    "redaction_policy": {
                        "source": "public-test-fixture",
                        "forbidden_content": [],
                    },
                    "artifacts": [
                        {
                            "path": "setting/parameters.json",
                            "public_id": "qa",
                            "role": "selected context",
                            "status": "selected candidate",
                            "evidence_handling": "inferred",
                            "sharing_boundary": "public-safe",
                        },
                        {
                            "path": "setting/temp/derived.json",
                            "public_id": "vx",
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
        self.assertEqual(generated_relations[0]["target_artifact"], "wb")

    def test_cli_returns_clear_error_for_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as fixture_dir, tempfile.TemporaryDirectory() as out_dir:
            fixture_path = Path(fixture_dir)
            manifest = {
                "fixture_id": "bad-fixture",
                "public_bundle_id": "wb",
                "purpose": "invalid manifest fixture",
                "redaction_policy": {
                    "source": "public-test-fixture",
                    "forbidden_content": [],
                },
                "artifacts": [
                    {
                        "path": "missing.json",
                        "public_id": "qa",
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

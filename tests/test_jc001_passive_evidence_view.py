import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "jc001-braid-config"
PROTOTYPE = ROOT / "prototypes" / "jc001_passive_evidence_view.py"


def load_prototype():
    spec = importlib.util.spec_from_file_location("jc001_passive_evidence_view", PROTOTYPE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture_hashes():
    hashes = {}
    for path in sorted(FIXTURE.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(FIXTURE).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


class PassiveEvidenceViewTest(unittest.TestCase):
    def test_builds_expected_evidence_view_without_mutating_fixture(self):
        prototype = load_prototype()
        before = fixture_hashes()

        view = prototype.build_evidence_view(FIXTURE)

        self.assertEqual(before, fixture_hashes())
        self.assertEqual(view["bundle_summary"]["bundle_id"], "jc001-braid-config")
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
            self.assertEqual(view["bundle_summary"]["bundle_id"], "jc001-braid-config")
            self.assertIn("## Conflict And Missing-Fact Report", markdown)
            self.assertIn("not executed", markdown)

        self.assertEqual(before, fixture_hashes())


if __name__ == "__main__":
    unittest.main()

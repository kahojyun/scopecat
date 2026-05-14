import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "jc002-handoff-snapshot"
PROTOTYPE = ROOT / "prototypes" / "jc002_handoff_snapshot.py"


def load_prototype():
    spec = importlib.util.spec_from_file_location("jc002_handoff_snapshot", PROTOTYPE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture_hashes(fixture=FIXTURE):
    hashes = {}
    for path in sorted(fixture.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(fixture).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return hashes


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def artifact_by_id(manifest, artifact_id):
    return next(
        artifact for artifact in manifest["artifacts"] if artifact["artifact_id"] == artifact_id
    )


def refresh_artifact_integrity(snapshot_root, manifest, artifact_id):
    artifact = artifact_by_id(manifest, artifact_id)
    artifact_path = snapshot_root / artifact["path"]
    artifact["size_bytes"] = artifact_path.stat().st_size
    artifact["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()


def copy_fixture(tmp_dir):
    copied_snapshot = Path(tmp_dir) / "snapshot"
    shutil.copytree(FIXTURE, copied_snapshot)
    return copied_snapshot


class HandoffSnapshotPrototypeTest(unittest.TestCase):
    def test_summary_and_reader_cover_handoff_acceptance_without_mutating_fixture(self):
        prototype = load_prototype()
        before = fixture_hashes()

        snapshot = prototype.HandoffSnapshot.open(FIXTURE)
        summary = snapshot.summary()
        baseline = snapshot.load_run("run-baseline")
        group = snapshot.load_group()

        self.assertEqual(before, fixture_hashes())
        self.assertEqual(summary["identity"]["snapshot_id"], "handoff-fixture-a")
        self.assertEqual(summary["can_open"]["status"], "pass")
        self.assertEqual(summary["can_open"]["included_artifact_count"], 5)
        self.assertEqual(summary["can_open"]["required_sidecar_count"], 1)
        self.assertEqual(summary["selection"]["group_order"], ["run-baseline", "run-sample"])
        self.assertEqual(
            prototype.status_value(summary["selection"]["selected_reason"]),
            "baseline and sample runs selected for analysis handoff smoke testing",
        )

        run_ids = [run["run_id"] for run in summary["runs"]]
        self.assertEqual(run_ids, ["run-baseline", "run-sample"])
        for run in summary["runs"]:
            self.assertEqual(run["source_namespace"], "redacted-station-a")
            self.assertIn("sample_label:not_provided", run["warnings"])
            self.assertIn("important_parameters.temperature:unknown", run["warnings"])

        self.assertEqual(baseline["condition_label"], "baseline")
        self.assertEqual(baseline["shape"], [4, 2])
        self.assertEqual(baseline["axes"][0]["unit"], "Hz")
        self.assertEqual(baseline["values"][0]["unit"], "V")
        self.assertEqual(len(baseline["sidecars"]), 1)
        self.assertEqual(baseline["sidecars"][0]["sidecar_id"], "sidecar-baseline-columns")
        self.assertEqual(len(baseline["derived_inputs"]), 1)
        self.assertEqual(baseline["derived_inputs"][0]["artifact_id"], "derived-window-a")

        self.assertEqual(group["group_title"], "public handoff fixture group")
        self.assertEqual(group["run_order"], ["run-baseline", "run-sample"])
        self.assertEqual([run["condition_label"] for run in group["runs"]], ["baseline", "sample"])
        self.assertEqual(len(group["runs"][1]["sidecars"]), 0)
        self.assertEqual(len(group["derived_inputs"]), 1)

        included_roles = {artifact["role"] for artifact in summary["artifacts"]["included"]}
        self.assertGreaterEqual(
            included_roles,
            {
                "primary_data",
                "required_read_sidecar",
                "handoff_context",
                "user_attached_derived_input",
            },
        )
        excluded = {
            artifact["artifact_id"]: artifact for artifact in summary["artifacts"]["excluded"]
        }
        self.assertEqual(excluded["unknown-array-a"]["role"], "unknown")
        self.assertEqual(excluded["report-artifact-a"]["role"], "report_artifact")
        self.assertEqual(
            excluded["internal-verification-ref-a"]["role"],
            "internal_verification_reference",
        )

        derived = [
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_id"] == "derived-window-a"
        ][0]
        self.assertEqual(derived["role"], "user_attached_derived_input")
        self.assertEqual(derived["source_run_relation"], ["run-baseline", "run-sample"])
        self.assertEqual(derived["processed_status"], "processed-lossless-subset")
        self.assertTrue(derived["sha256"])
        self.assertGreater(derived["size_bytes"], 0)

        missing_paths = {field["path"]: field["status"] for field in summary["missing_fields"]}
        self.assertEqual(missing_paths["runs.run-baseline.sample_label"], "not_provided")
        self.assertEqual(
            missing_paths["runs.run-baseline.important_parameters.temperature"],
            "unknown",
        )
        self.assertEqual(missing_paths["runs.run-baseline.original_path_evidence"], "redacted")
        self.assertEqual(summary["redaction"]["status"], "pass")
        self.assertEqual(summary["shareability"]["status"], "public-safe")
        self.assertTrue(all(value is False for value in summary["safety_evidence"].values()))

    def test_copied_snapshot_opens_and_outputs_are_generated_outside_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = tmp_path / "copied" / "snapshot"
            shutil.copytree(FIXTURE, copied_snapshot)
            before = fixture_hashes(copied_snapshot)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            outputs = prototype.write_outputs(snapshot, tmp_path / "outputs")

            self.assertEqual(before, fixture_hashes(copied_snapshot))
            self.assertEqual(
                {path.name for path in outputs},
                {
                    "handoff-summary.json",
                    "handoff-summary.md",
                    "reader-group.json",
                    "single-run-plot.svg",
                    "group-sanity-plot.svg",
                },
            )
            for path in outputs:
                self.assertTrue(path.exists())
                self.assertNotIn(copied_snapshot, path.parents)

            summary = read_json(tmp_path / "outputs" / "handoff-summary.json")
            group = read_json(tmp_path / "outputs" / "reader-group.json")
            markdown = (tmp_path / "outputs" / "handoff-summary.md").read_text(encoding="utf-8")
            self.assertEqual(summary["redaction"]["status"], "pass")
            self.assertEqual(group["run_order"], ["run-baseline", "run-sample"])
            self.assertIn("## Missing And Redacted", markdown)
            self.assertIn("## Shareability", markdown)
            plot_svg = (tmp_path / "outputs" / "group-sanity-plot.svg").read_text()
            self.assertIn("<polyline", plot_svg)
            self.assertIn("frequency (Hz)", plot_svg)
            self.assertIn("response (V)", plot_svg)

    def test_rejects_outputs_inside_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output directory must be outside snapshot",
            ):
                prototype.write_outputs(snapshot, copied_snapshot / "outputs")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output directory must be outside snapshot",
            ):
                prototype.write_outputs(snapshot, copied_snapshot)

    def test_cli_writes_summary_reader_and_consumer_side_plots(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = subprocess.run(
                [sys.executable, str(PROTOTYPE), str(FIXTURE), "--out-dir", tmp_dir],
                check=True,
                capture_output=True,
                text=True,
            )

            output_dir = Path(tmp_dir)
            self.assertIn("handoff-summary.json", result.stdout)
            self.assertTrue((output_dir / "handoff-summary.json").exists())
            self.assertTrue((output_dir / "reader-group.json").exists())
            self.assertTrue((output_dir / "single-run-plot.svg").exists())
            self.assertTrue((output_dir / "group-sanity-plot.svg").exists())

    def test_redaction_audit_flags_private_path_leaks_in_copied_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["original_path_evidence"] = {
                "status": "provided",
                "value": "/Users/fixtureuser/private-lab/run-0001",
            }
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "fail")
            self.assertEqual(summary["shareability"]["status"], "blocked")
            self.assertIn(
                {"source": "snapshot-manifest.json", "kind": "private absolute path"},
                summary["redaction"]["findings"],
            )

    def test_rejects_artifact_path_traversal(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["path"] = "../outside.csv"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "must stay inside snapshot",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_missing_artifact_id_with_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["artifacts"][0]["artifact_id"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "artifact requires artifact_id",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_empty_run_group_at_load_time(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"] = []
            manifest["selection"]["group_order"] = []
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "snapshot requires at least one run",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_invalid_status_value_semantics(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["sample_label"] = {
                "status": "unknown",
                "value": "sample-should-not-travel",
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "status unknown must not carry value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_primary_data_shape_mismatch(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["shape"] = [99, 2]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "shape mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_unknown_source_run_relation(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "derived-window-a")["source_run_relation"] = [
                "run-baseline",
                "run-missing",
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "relation references unknown run",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_missing_condition_label_at_load_time(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["runs"][0]["condition_label"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires condition_label",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_redaction_audit_scans_included_context_artifacts(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            context_path = copied_snapshot / "context" / "readme-note.txt"
            context_path.write_text(
                "Public note accidentally mentions TCPIP::10.2.3.4::INSTR\n",
                encoding="utf-8",
            )
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "handoff-context-note")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "fail")
            self.assertIn(
                {"source": "context/readme-note.txt", "kind": "instrument address"},
                summary["redaction"]["findings"],
            )

    def test_redaction_audit_skips_non_utf8_included_artifacts(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            context_path = copied_snapshot / "context" / "readme-note.txt"
            context_path.write_bytes(b"\xff\xfe\x00\x00")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "handoff-context-note")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "pass")
            self.assertIn(
                "context/readme-note.txt",
                summary["redaction"]["skipped_binary_sources"],
            )

    def test_redaction_audit_flags_declared_sensitive_categories(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["device_label"] = {
                "status": "provided",
                "value": "device_id:alpha-private-001",
            }
            manifest["selection"]["selected_reason"] = {
                "status": "provided",
                "value": "Checked on control-pc-alpha. Do not share.",
            }
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "fail")
            self.assertIn(
                {"source": "snapshot-manifest.json", "kind": "machine name"},
                summary["redaction"]["findings"],
            )
            self.assertIn(
                {"source": "snapshot-manifest.json", "kind": "sample identifier"},
                summary["redaction"]["findings"],
            )
            self.assertIn(
                {"source": "snapshot-manifest.json", "kind": "lab-only note"},
                summary["redaction"]["findings"],
            )

    def test_plot_uses_manifest_declared_axis_and_value_metadata(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            for artifact_id in ("primary-baseline", "primary-sample"):
                artifact = artifact_by_id(manifest, artifact_id)
                artifact["axes"][0]["name"] = "declared detuning"
                artifact["axes"][0]["unit"] = "MHz"
                artifact["values"][0]["name"] = "declared signal"
                artifact["values"][0]["unit"] = "arb"
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            output_path = Path(tmp_dir) / "plot.svg"
            prototype.render_svg_plot(snapshot.load_group(), output_path)
            svg = output_path.read_text(encoding="utf-8")

            self.assertIn("declared detuning (MHz)", svg)
            self.assertIn("declared signal (arb)", svg)

    def test_plot_handles_constant_x_values(self):
        prototype = load_prototype()
        group = {
            "group_title": "constant x fixture",
            "runs": [
                {
                    "run_id": "run-constant-x",
                    "condition_label": "single-point",
                    "axes": [{"name": "frequency", "column": "frequency_hz", "unit": "Hz"}],
                    "values": [{"name": "response", "column": "response_v", "unit": "V"}],
                    "data": [{"frequency_hz": 1.0, "response_v": 0.2}],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "plot.svg"

            prototype.render_svg_plot(group, output_path)

            svg = output_path.read_text(encoding="utf-8")
            self.assertIn("<polyline", svg)
            self.assertIn("frequency (Hz)", svg)


if __name__ == "__main__":
    unittest.main()

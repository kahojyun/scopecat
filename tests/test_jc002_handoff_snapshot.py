import hashlib
import importlib.util
import json
import os
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
    def assert_redaction_status_matches_manifest(self, summary, manifest):
        self.assertEqual(summary["redaction_status"], manifest["redaction_status"])

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
            self.assertEqual(run["source_namespace"], "labrad-like-data-vault")
            self.assertIn("sample_label:not_provided", run["warnings"])
            self.assertIn("important_parameters.temperature:unknown", run["warnings"])

        self.assertEqual(baseline["condition_label"], "baseline")
        self.assertEqual(baseline["per_run_note"]["value"], "baseline condition")
        self.assertEqual(baseline["shape"], [4, 2])
        self.assertEqual(baseline["axes"][0]["unit"], "Hz")
        self.assertEqual(baseline["values"][0]["unit"], "V")
        self.assertEqual(len(baseline["sidecars"]), 1)
        self.assertEqual(baseline["sidecars"][0]["sidecar_id"], "sidecar-baseline-columns")
        self.assertEqual(len(baseline["derived_inputs"]), 1)
        self.assertEqual(baseline["derived_inputs"][0]["artifact_id"], "derived-window-a")

        self.assertEqual(group["group_title"], "public handoff fixture group")
        self.assertEqual(group["run_order"], ["run-baseline", "run-sample"])
        self.assertEqual(group["per_run_notes"]["run-sample"]["value"], "sample condition")
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
        included_by_id = {
            artifact["artifact_id"]: artifact for artifact in summary["artifacts"]["included"]
        }
        self.assertEqual(
            included_by_id["primary-baseline"]["source_run_relation"],
            ["run-baseline"],
        )
        self.assertEqual(
            included_by_id["primary-baseline"]["sha256"],
            artifact_by_id(read_json(FIXTURE / "snapshot-manifest.json"), "primary-baseline")[
                "sha256"
            ],
        )
        self.assertGreater(included_by_id["primary-baseline"]["size_bytes"], 0)
        self.assertEqual(
            included_by_id["derived-window-a"]["processed_status"],
            "processed-lossless-subset",
        )
        self.assertEqual(
            included_by_id["derived-window-a"]["human_production_note"],
            "Public fixture note: selected frequency window was attached before export.",
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
        referenced = {
            artifact["artifact_id"]: artifact for artifact in summary["artifacts"]["referenced"]
        }
        self.assertEqual(
            referenced["calibration-ref-a"]["reference"],
            "redacted-calibration-reference://calibration-a",
        )
        self.assertEqual(
            referenced["calibration-ref-a"]["warning"],
            "Reference retained; calibration artifact not copied by default.",
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
        self.assertEqual(missing_paths["source_system.station_id"], "redacted")
        self.assertEqual(missing_paths["source_system.control_computer"], "redacted")
        self.assertEqual(missing_paths["runs.run-baseline.sample_label"], "not_provided")
        self.assertEqual(
            missing_paths["runs.run-baseline.important_parameters.temperature"],
            "unknown",
        )
        self.assertEqual(missing_paths["runs.run-baseline.original_path_evidence"], "redacted")
        self.assert_redaction_status_matches_manifest(
            summary,
            read_json(FIXTURE / "snapshot-manifest.json"),
        )
        self.assertTrue(all(value is False for value in summary["safety_evidence"].values()))

    def test_copied_snapshot_opens_and_consumer_outputs_are_generated(self):
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

            summary = read_json(tmp_path / "outputs" / "handoff-summary.json")
            group = read_json(tmp_path / "outputs" / "reader-group.json")
            markdown = (tmp_path / "outputs" / "handoff-summary.md").read_text(encoding="utf-8")
            self.assert_redaction_status_matches_manifest(
                summary,
                read_json(copied_snapshot / "snapshot-manifest.json"),
            )
            self.assertEqual(group["run_order"], ["run-baseline", "run-sample"])
            self.assertIn("## Missing And Redacted", markdown)
            self.assertIn(r"derived\-window\-a", markdown)
            self.assertIn(r"processed\-lossless\-subset", markdown)
            self.assertIn("Reference retained", markdown)
            plot_svg = (tmp_path / "outputs" / "group-sanity-plot.svg").read_text()
            self.assertIn("<polyline", plot_svg)
            self.assertIn("frequency (Hz)", plot_svg)
            self.assertIn("response (V)", plot_svg)

    def test_cli_writes_summary_reader_and_mock_plotter_outputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = subprocess.run(
                [sys.executable, str(PROTOTYPE), str(FIXTURE), "--out-dir", tmp_dir],
                check=True,
                capture_output=True,
                text=True,
            )

            output_dir = Path(tmp_dir)
            self.assertIn("handoff-summary.json", result.stdout)
            self.assertNotIn(tmp_dir, result.stdout)
            self.assertTrue((output_dir / "handoff-summary.json").exists())
            self.assertTrue((output_dir / "reader-group.json").exists())
            self.assertTrue((output_dir / "single-run-plot.svg").exists())
            self.assertTrue((output_dir / "group-sanity-plot.svg").exists())

    def test_rejects_invalid_manifest_json_with_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            (copied_snapshot / "snapshot-manifest.json").write_text("{not-json", encoding="utf-8")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "could not be read as JSON",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_json_read_errors_do_not_expose_absolute_paths(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest_path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(prototype.HandoffSnapshotError) as context:
                prototype.HandoffSnapshot.open(copied_snapshot)

            self.assertIn(
                "snapshot-manifest.json could not be read as JSON",
                str(context.exception),
            )
            self.assertNotIn(str(copied_snapshot), str(context.exception))

    def test_rejects_non_standard_json_constants(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            text = manifest_path.read_text(encoding="utf-8")
            text = text.replace(
                '"baseline and sample runs selected for analysis handoff smoke testing"',
                "NaN",
            )
            manifest_path.write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "snapshot-manifest.json could not be read as JSON",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_symlinked_manifest(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            external_manifest = tmp_path / "external-manifest.json"
            (copied_snapshot / "snapshot-manifest.json").replace(external_manifest)
            (copied_snapshot / "snapshot-manifest.json").symlink_to(external_manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "snapshot-manifest.json must not be a symlink",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_invalid_identity_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["snapshot_id"] = ""
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "snapshot_id must be a non-empty string",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["created_at"] = None
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "created_at requires timestamp",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["producer"] = "bad"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "producer must be an object",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["producer"]["version"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "producer requires version",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["producer"]["extra"] = "unexpected"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "producer has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_invalid_timestamps(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["created_at"] = "not-a-timestamp"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "created_at requires timestamp",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["created_at"] = "2026-05-14"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "created_at requires timestamp",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["acquisition_time"]["value"] = "2026-05-13T10:00:00"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "acquisition_time requires timestamp",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["acquisition_time"]["value"] = "not-a-timestamp"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "acquisition_time requires timestamp",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_summary_uses_export_redaction_status_input(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["redaction_status"] = {
                "status": "export_declared_internal_only",
                "keyword_table": {
                    "status": "export-owned",
                    "entry_count": 2,
                },
            }
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()
            markdown = prototype.render_markdown(summary)

            self.assert_redaction_status_matches_manifest(summary, manifest)
            self.assertIn("## Redaction Status", markdown)
            self.assertIn("keyword\\_table", markdown)

    def test_markdown_summary_escapes_active_markdown_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["group_title"] = "![x](https://example.test/pixel)"
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            markdown = prototype.render_markdown(snapshot.summary())

            self.assertIn(r"\!\[x\]\(https://example\.test/pixel\)", markdown)
            self.assertNotIn("![x](https://example.test/pixel)", markdown)

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

    def test_rejects_windows_drive_relative_artifact_paths(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            drive_relative_path = copied_snapshot / "C:baseline.csv"
            shutil.copyfile(copied_snapshot / "data" / "baseline.csv", drive_relative_path)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact = artifact_by_id(manifest, "primary-baseline")
            artifact["path"] = "C:baseline.csv"
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "must not use Windows drive path",
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

    def test_rejects_malformed_run_artifact_ids_with_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][1]["primary_artifact_id"] = {}
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires primary_artifact_id",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["required_sidecar_artifact_ids"] = [{}]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "required sidecars must use IDs",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_reader_outputs_do_not_alias_validated_manifest(self):
        prototype = load_prototype()
        snapshot = prototype.HandoffSnapshot.open(FIXTURE)

        run = snapshot.load_run("run-baseline")
        group = snapshot.load_group()
        summary = snapshot.summary()

        run["axes"][0]["unit"] = "mutated"
        run["source_id"]["namespace"] = "mutated"
        run["per_run_note"]["value"] = "mutated"
        group["run_order"].append("mutated")
        group["per_run_notes"]["run-baseline"]["value"] = "mutated"
        summary["selection"]["group_order"].append("mutated")
        summary["identity"]["source_system"]["station_id"]["status"] = "mutated"

        fresh_run = snapshot.load_run("run-baseline")
        fresh_group = snapshot.load_group()
        fresh_summary = snapshot.summary()

        self.assertEqual(fresh_run["axes"][0]["unit"], "Hz")
        self.assertEqual(fresh_run["source_id"]["namespace"], "labrad-like-data-vault")
        self.assertEqual(fresh_run["per_run_note"]["value"], "baseline condition")
        self.assertEqual(fresh_group["run_order"], ["run-baseline", "run-sample"])
        self.assertEqual(
            fresh_group["per_run_notes"]["run-baseline"]["value"],
            "baseline condition",
        )
        self.assertEqual(
            fresh_summary["selection"]["group_order"],
            ["run-baseline", "run-sample"],
        )
        self.assertEqual(
            fresh_summary["identity"]["source_system"]["station_id"]["status"],
            "redacted",
        )

    def test_relative_snapshot_root_is_anchored_after_open(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copy_fixture(tmp_path)
            original_cwd = Path.cwd()
            try:
                os.chdir(tmp_path)
                snapshot = prototype.HandoffSnapshot.open("snapshot")
                os.chdir("/")

                baseline = snapshot.load_run("run-baseline")
            finally:
                os.chdir(original_cwd)

            self.assertEqual(baseline["shape"], [4, 2])

    def test_reader_rechecks_artifact_integrity_after_open(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text("frequency_hz,response_v\n1.0,0.1\n", encoding="utf-8")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "checksum mismatch|size mismatch",
            ):
                snapshot.load_run("run-baseline")

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text("frequency_hz,response_v\n1.0,0.1\n", encoding="utf-8")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "checksum mismatch|size mismatch",
            ):
                snapshot.summary()

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            derived_path = copied_snapshot / "derived" / "selected-window.json"
            derived_path.write_text("changed derived input\n", encoding="utf-8")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "checksum mismatch|size mismatch",
            ):
                snapshot.load_run("run-baseline")

    def test_group_order_can_differ_from_manifest_run_order(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["group_order"] = ["run-sample", "run-baseline"]
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            group = snapshot.load_group()
            summary = snapshot.summary()
            markdown = prototype.render_markdown(summary)

            self.assertEqual(group["run_order"], ["run-sample", "run-baseline"])
            self.assertEqual(
                [run["run_id"] for run in group["runs"]],
                ["run-sample", "run-baseline"],
            )
            self.assertEqual(
                [run["run_id"] for run in summary["runs"]],
                ["run-sample", "run-baseline"],
            )
            self.assertLess(markdown.index("run\\-sample"), markdown.index("run\\-baseline"))

    def test_rejects_duplicate_group_order_entries(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["group_order"] = ["run-baseline", "run-baseline"]
            manifest["selection"]["per_run_notes"].pop("run-sample")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selection.group_order must not contain duplicates",
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

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["measurement_label"] = {
                "status": "redacted",
                "value": "withheld measurement label",
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "status redacted must not carry value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["important_parameters"][0] = {
                "name": "drive_power",
                "status": "redacted",
                "value": "withheld-drive-power",
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "status redacted must not carry value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["sample_label"] = {
                "status": "not_provided",
                "value": None,
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "status not_provided must not carry value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["device_label"] = {
                "status": "provided",
                "value": None,
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "status provided requires value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_status_value_hides_redacted_payloads(self):
        prototype = load_prototype()

        self.assertIsNone(prototype.status_value({"status": "redacted", "value": "withheld"}))

    def test_rejects_non_text_status_values_for_context_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["measurement_label"] = {
                "status": "provided",
                "value": {"label": "bad"},
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "measurement_label requires text value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["selected_reason"] = {
                "status": "provided",
                "value": ["bad"],
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selection.selected_reason requires text value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["source_system"]["station_id"] = {
                "status": "redacted",
                "value": {"station": "bad"},
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_system.station_id status redacted must not carry value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_source_namespace_mismatch_when_station_is_known(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["source_id"]["namespace"] = "unscoped-foreign-system"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_id namespace mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["source_id"]["namespace"] = {
                "status": "provided",
                "value": "unscoped-foreign-system",
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_id namespace mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_source_namespace_can_use_source_system_type(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["source_id"]["namespace"] = "labrad-like-data-vault"
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)

            self.assertEqual(
                snapshot.summary()["runs"][0]["source_namespace"],
                "labrad-like-data-vault",
            )

    def test_source_id_can_use_explicit_missing_statuses(self):
        prototype = load_prototype()
        for key, status in (("namespace", "not_provided"), ("local_id", "not_applicable")):
            with tempfile.TemporaryDirectory() as tmp_dir:
                copied_snapshot = copy_fixture(tmp_dir)
                manifest_path = copied_snapshot / "snapshot-manifest.json"
                manifest = read_json(manifest_path)
                manifest["runs"][0]["source_id"][key] = {"status": status}
                write_json(manifest_path, manifest)

                snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
                summary = snapshot.summary()
                missing_paths = {
                    field["path"]: field["status"] for field in summary["missing_fields"]
                }

                self.assertEqual(missing_paths[f"runs.run-baseline.source_id.{key}"], status)

    def test_rejects_status_objects_with_unknown_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["measurement_label"]["extra"] = "unexpected"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "measurement_label has unknown fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["source_system"]["unexpected_host"] = "host-a"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_system has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["unexpected_field"] = "unexpected"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selection has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["source_id"]["unexpected_path"] = "unexpected"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_id has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["unexpected_field"] = "unexpected"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "run run-baseline has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["unexpected_manifest_field"] = "unexpected"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "manifest has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_non_object_important_parameter(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["important_parameters"] = ["bad"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "run run-baseline parameter must be an object",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_malformed_important_parameter_metadata(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["important_parameters"][0]["unit"] = ["dBm"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "unit mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["important_parameters"][0]["value"] = {"bad": "value"}
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires scalar value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["important_parameters"][1]["name"] = "drive_power"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "parameter names must be unique",
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

    def test_rejects_malformed_integrity_and_shape_types(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["size_bytes"] = 60.0
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "size mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["sha256"] = "not-a-sha"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires sha256",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["shape"] = [4.0, 2.0]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "shape mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_empty_primary_data(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text("frequency_hz,response_v\n", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            artifact_by_id(manifest, "primary-baseline")["shape"] = [0, 2]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires data rows",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_malformed_scopecat_primary_data_value(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text("frequency_hz,response_v\n1.0,not-a-number\n", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            artifact_by_id(manifest, "primary-baseline")["shape"] = [1, 2]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "must be numeric",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_missing_sidecar_file_raises_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            (copied_snapshot / "sidecars" / "baseline-columns.json").unlink()

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "included artifact sidecar-baseline-columns is missing",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_sidecar_payload_id_mismatch(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["sidecar_id"] = "different-sidecar"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns ID mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_sidecar_column_metadata_mismatch(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["unit"] = "GHz"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "column unit mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["axis"] = "y"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "column axis mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["quantity"] = "detuning"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "column quantity mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_duplicate_sidecar_columns(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"].insert(
                0,
                {
                    "name": "frequency_hz",
                    "quantity": "drive_frequency",
                    "unit": "GHz",
                    "axis": "y",
                },
            )
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "duplicate columns",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_extra_sidecar_columns(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"].append(
                {
                    "name": "not_in_primary",
                    "quantity": "extra",
                    "unit": "arb",
                    "axis": "y",
                }
            )
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns column mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_extra_sidecar_schema_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["extra"] = "unexpected"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns schema mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["extra"] = "unexpected"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns column schema mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["quantity"] = ""
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns column quantity mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_malformed_primary_metadata_raises_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del artifact_by_id(manifest, "primary-baseline")["axes"][0]["column"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "axis column mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-sample")["values"][0]["unit"] = {"unit": "V"}
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "value requires unit",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["axes"][0]["unexpected_field"] = (
                "unexpected"
            )
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "axis has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact = artifact_by_id(manifest, "primary-sample")
            artifact["values"][0]["column"] = artifact["axes"][0]["column"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "column mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact = artifact_by_id(manifest, "primary-sample")
            artifact["values"].append(dict(artifact["values"][0]))
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires one axis and one value",
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

    def test_rejects_primary_artifact_relation_overclaiming_runs(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-sample")["source_run_relation"] = [
                "run-sample",
                "run-baseline",
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "primary artifact relation mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_selected_runs_sharing_primary_artifact(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][1]["primary_artifact_id"] = "primary-baseline"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selected runs must use distinct primary artifacts",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_unselected_included_primary_data(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            orphan_path = copied_snapshot / "data" / "orphan.csv"
            shutil.copyfile(copied_snapshot / "data" / "baseline.csv", orphan_path)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact = json.loads(json.dumps(artifact_by_id(manifest, "primary-baseline")))
            artifact["artifact_id"] = "primary-orphan"
            artifact["path"] = "data/orphan.csv"
            artifact["source_run_relation"] = ["run-baseline"]
            manifest["artifacts"].append(artifact)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-orphan")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "primary artifact primary-orphan is not selected by any run",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_derived_input_payload_is_not_parsed_by_reader(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            derived_path = copied_snapshot / "derived" / "selected-window.json"
            derived_path.write_text("not-json-but-user-attached\n", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "derived-window-a")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            baseline = snapshot.load_run("run-baseline")

            self.assertEqual(baseline["derived_inputs"][0]["artifact_id"], "derived-window-a")
            self.assertEqual(
                baseline["derived_inputs"][0]["processed_status"],
                "processed-lossless-subset",
            )
            self.assertEqual(
                baseline["derived_inputs"][0]["source_run_relation"],
                ["run-baseline", "run-sample"],
            )
            self.assertEqual(baseline["derived_inputs"][0]["path"], "derived/selected-window.json")

    def test_rejects_malformed_derived_input_metadata(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "derived-window-a")["processed_status"] = {
                "status": "processed"
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires processed_status",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "derived-window-a")["human_production_note"] = ["manual"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires human_production_note",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_non_string_source_run_relation(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "derived-window-a")["source_run_relation"] = [{}]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_run_relation must use run IDs",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_duplicate_relation_ids(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "derived-window-a")["source_run_relation"] = [
                "run-baseline",
                "run-baseline",
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_run_relation has duplicates",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["required_sidecar_artifact_ids"] = [
                "sidecar-baseline-columns",
                "sidecar-baseline-columns",
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "required sidecars has duplicates",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_sidecar_relation_that_omits_requiring_run(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "sidecar-baseline-columns")["source_run_relation"] = [
                "run-sample"
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns relation mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_malformed_artifact_text_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "sidecar-baseline-columns")["applies_to_artifact_id"] = {}
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "applies_to_artifact_id must be text",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "unknown-array-a")["exclusion_reason"] = ["not text"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "reason must be text",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "calibration-ref-a")["reference"] = {"not": "text"}
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "reference must be text",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_role_incompatible_artifact_fields(self):
        prototype = load_prototype()
        for artifact_id, key, value in (
            ("primary-baseline", "reference", "role-incompatible-reference://baseline"),
            ("primary-baseline", "applies_to_artifact_id", "unexpected-artifact-id"),
            ("derived-window-a", "reference", "role-incompatible-reference://derived"),
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                copied_snapshot = copy_fixture(tmp_dir)
                manifest_path = copied_snapshot / "snapshot-manifest.json"
                manifest = read_json(manifest_path)
                artifact_by_id(manifest, artifact_id)[key] = value
                write_json(manifest_path, manifest)

                with self.assertRaisesRegex(
                    prototype.HandoffSnapshotError,
                    f"artifact {artifact_id} has invalid fields",
                ):
                    prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            calibration_path = copied_snapshot / "calibration-reference.txt"
            calibration_path.write_text("synthetic calibration payload\n", encoding="utf-8")
            calibration = artifact_by_id(manifest, "calibration-ref-a")
            calibration["handling"] = "included"
            calibration["path"] = "calibration-reference.txt"
            refresh_artifact_integrity(copied_snapshot, manifest, "calibration-ref-a")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "artifact calibration-ref-a has invalid fields",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_payload_fields_on_non_included_artifacts(self):
        prototype = load_prototype()
        for artifact_id, key, value in (
            ("calibration-ref-a", "path", "calibration/local-only.json"),
            ("unknown-array-a", "size_bytes", 123),
            ("report-artifact-a", "sha256", "0" * 64),
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                copied_snapshot = copy_fixture(tmp_dir)
                manifest_path = copied_snapshot / "snapshot-manifest.json"
                manifest = read_json(manifest_path)
                artifact_by_id(manifest, artifact_id)[key] = value
                write_json(manifest_path, manifest)

                with self.assertRaisesRegex(
                    prototype.HandoffSnapshotError,
                    f"artifact {artifact_id} {key} requires inclusion",
                ):
                    prototype.HandoffSnapshot.open(copied_snapshot)

    def test_allows_explicitly_included_advanced_artifact_with_warning(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            calibration_path = copied_snapshot / "calibration-reference.txt"
            calibration_path.write_text("synthetic calibration payload\n", encoding="utf-8")
            calibration = artifact_by_id(manifest, "calibration-ref-a")
            calibration["handling"] = "included"
            calibration["path"] = "calibration-reference.txt"
            calibration.pop("reference")
            refresh_artifact_integrity(copied_snapshot, manifest, "calibration-ref-a")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            included = {
                artifact["artifact_id"]: artifact
                for artifact in snapshot.summary()["artifacts"]["included"]
            }

            self.assertIn("calibration-ref-a", included)
            self.assertEqual(
                included["calibration-ref-a"]["warning"],
                "Reference retained; calibration artifact not copied by default.",
            )

    def test_rejects_included_advanced_artifact_without_warning(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            calibration_path = copied_snapshot / "calibration-reference.txt"
            calibration_path.write_text("synthetic calibration payload\n", encoding="utf-8")
            calibration = artifact_by_id(manifest, "calibration-ref-a")
            calibration["handling"] = "included"
            calibration["path"] = "calibration-reference.txt"
            calibration.pop("reference")
            calibration.pop("warning")
            refresh_artifact_integrity(copied_snapshot, manifest, "calibration-ref-a")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "artifact calibration-ref-a requires warning",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_malformed_primary_relation_before_artifact_order_matters(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            primary = artifact_by_id(manifest, "primary-baseline")
            sidecar = artifact_by_id(manifest, "sidecar-baseline-columns")
            primary["source_run_relation"] = [{}]
            manifest["artifacts"].remove(sidecar)
            manifest["artifacts"].insert(0, sidecar)
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "artifact primary-baseline source_run_relation must use run IDs",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_unrequired_required_sidecar_artifact(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["required_sidecar_artifact_ids"] = []
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns is not required by run-baseline",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_missing_required_nested_manifest_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["source_system"]["type"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_system requires type",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["redaction_status"] = ["bad"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "redaction_status must be an object",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_partial_safety_evidence(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["safety_evidence"]["network_or_cloud_dependency"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "missing safety evidence",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_unknown_safety_evidence(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["safety_evidence"]["extra_flag"] = False
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "unknown safety evidence",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_missing_per_run_notes_appear_in_summary_warnings(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["per_run_notes"]["run-baseline"] = {"status": "not_provided"}
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()
            missing_paths = {field["path"]: field["status"] for field in summary["missing_fields"]}

            self.assertEqual(
                missing_paths["selection.per_run_notes.run-baseline"],
                "not_provided",
            )

    def test_source_id_can_be_explicitly_unknown(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][1]["source_id"]["local_id"] = {"status": "unknown"}
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()
            missing_paths = {field["path"]: field["status"] for field in summary["missing_fields"]}

            self.assertIsNone(summary["runs"][1]["source_local_id"])
            self.assertEqual(missing_paths["runs.run-sample.source_id.local_id"], "unknown")

    def test_rejects_duplicate_concrete_source_ids(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][1]["source_id"]["local_id"] = "dataset-0001"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selected runs must use distinct source IDs",
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

    def test_rejects_missing_group_title_at_load_time(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["selection"]["group_title"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selection requires group_title",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_plot_spec_uses_manifest_declared_axis_and_value_metadata(self):
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
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["quantity"] = "declared detuning"
            sidecar["columns"][0]["unit"] = "MHz"
            sidecar["columns"][1]["quantity"] = "declared signal"
            sidecar["columns"][1]["unit"] = "arb"
            write_json(sidecar_path, sidecar)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            plot_spec = prototype.build_plot_spec(snapshot.load_group())

            self.assertEqual(plot_spec["title"], "public handoff fixture group")
            self.assertEqual(plot_spec["x_label"], "declared detuning (MHz)")
            self.assertEqual(plot_spec["y_label"], "declared signal (arb)")
            self.assertEqual(
                [series["label"] for series in plot_spec["series"]],
                ["baseline", "sample"],
            )

    def test_plot_spec_handles_different_run_column_names(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sample_data = copied_snapshot / "data" / "sample.csv"
            sample_data.write_text(
                "sample_frequency_hz,sample_response_v\n1.0,0.13\n2.0,0.29\n",
                encoding="utf-8",
            )
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            sample_artifact = artifact_by_id(manifest, "primary-sample")
            sample_artifact["axes"][0]["column"] = "sample_frequency_hz"
            sample_artifact["values"][0]["column"] = "sample_response_v"
            sample_artifact["shape"] = [2, 2]
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-sample")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            plot_spec = prototype.build_plot_spec(snapshot.load_group())

            sample_series = plot_spec["series"][1]
            self.assertEqual(sample_series["x"], [1.0, 2.0])
            self.assertEqual(sample_series["y"], [0.13, 0.29])

    def test_plot_spec_rejects_mixed_units_under_one_label(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            sample_artifact = artifact_by_id(manifest, "primary-sample")
            sample_artifact["axes"][0]["unit"] = "MHz"
            sample_artifact["values"][0]["unit"] = "mV"
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "matching axis and value metadata",
            ):
                prototype.build_plot_spec(snapshot.load_group())

    def test_mock_plotter_consumes_reader_plot_spec(self):
        prototype = load_prototype()
        plot_spec = {
            "title": "mock plot",
            "x_label": "frequency (Hz)",
            "y_label": "response (V)",
            "series": [{"label": "baseline", "x": [1.0, 2.0], "y": [0.1, 0.2]}],
        }

        svg = prototype.mock_plotter_svg(plot_spec)

        self.assertIn("<polyline", svg)
        self.assertIn("frequency (Hz)", svg)
        self.assertIn("response (V)", svg)

    def test_mock_plotter_rejects_mismatched_x_y_pairs(self):
        prototype = load_prototype()
        plot_spec = {
            "title": "mock plot",
            "x_label": "frequency (Hz)",
            "y_label": "response (V)",
            "series": [{"label": "baseline", "x": [1.0, 2.0], "y": [0.1]}],
        }

        with self.assertRaisesRegex(
            prototype.HandoffSnapshotError,
            "x and y lengths must match",
        ):
            prototype.mock_plotter_svg(plot_spec)


if __name__ == "__main__":
    unittest.main()

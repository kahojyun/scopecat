from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from implementation_candidates.handoff_package_contents_preview import (
    build_handoff_package_contents_preview_summary,
)
from implementation_candidates.handoff_package_writer import summary as writer_module
from implementation_candidates.handoff_package_writer import write_handoff_package

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "handoff_package_writer" / "basic_package"
STORAGE_ROOT = FIXTURE / "storage"


def _load_input() -> dict:
    return json.loads((FIXTURE / "package-writer-input.json").read_text(encoding="utf-8"))


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _package_tree(package_dir: Path) -> list[str]:
    return sorted(path.relative_to(package_dir).as_posix() for path in package_dir.rglob("*"))


class HandoffPackageWriterCandidateTest(unittest.TestCase):
    def assertRejected(self, source: dict, pattern: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, pattern):
                write_handoff_package(
                    source,
                    storage_root=STORAGE_ROOT,
                    package_root=Path(temp_dir),
                )

    def test_writes_expected_package_directory_without_source_paths_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            summary = write_handoff_package(
                _load_input(),
                storage_root=STORAGE_ROOT,
                package_root=package_root,
            )
            expected = json.loads(
                (FIXTURE / "expected-package-writer-summary.json").read_text(encoding="utf-8")
            )["candidate_summary"]

            self.assertEqual(summary, expected)
            package_dir = package_root / "handoff-package-legacy-rabi-001"
            self.assertEqual(
                _package_tree(package_dir),
                [
                    "measurements",
                    "measurements/legacy-rabi-001",
                    "measurements/legacy-rabi-001/primary.csv",
                    "package-manifest.json",
                ],
            )
            primary = package_dir / "measurements" / "legacy-rabi-001" / "primary.csv"
            manifest = package_dir / "package-manifest.json"
            self.assertEqual(
                primary.read_text(encoding="utf-8"),
                (STORAGE_ROOT / "records" / "legacy-rabi-001" / "primary.csv").read_text(
                    encoding="utf-8"
                ),
            )
            manifest_bytes = manifest.read_bytes()
            expected_manifest_bytes = (FIXTURE / "expected-package-manifest.json").read_bytes()
            self.assertEqual(manifest_bytes, expected_manifest_bytes)
            manifest_data = json.loads(manifest_bytes)
            expected_manifest = json.loads(expected_manifest_bytes)
            self.assertEqual(manifest_data, expected_manifest)
            write_results = {item["path"]: item for item in summary["write_results"]}
            for relative_path, expected_kind in (
                (
                    "handoff-package-legacy-rabi-001/measurements/legacy-rabi-001/primary.csv",
                    "primary_data",
                ),
                ("handoff-package-legacy-rabi-001/package-manifest.json", "package_manifest"),
            ):
                content = (package_root / relative_path).read_bytes()
                self.assertEqual(write_results[relative_path]["kind"], expected_kind)
                self.assertEqual(write_results[relative_path]["bytes_written"], len(content))
                self.assertEqual(write_results[relative_path]["digest"], _sha256_digest(content))
            self.assertNotIn("source_path", json.dumps(manifest_data, sort_keys=True))
            self.assertNotIn("display_path", manifest_data["package_identity"])
            preview_summary = build_handoff_package_contents_preview_summary(manifest_data)
            self.assertEqual(
                preview_summary["package"]["package_id"],
                "handoff-package-legacy-rabi-001",
            )
            self.assertEqual(
                preview_summary["package_preview_policy"]["preview_authority"],
                "scopecat_export_manifest_only",
            )
            self.assertEqual(
                manifest_data["selected_measurements"][0]["primary_data"]["package_path"],
                "measurements/legacy-rabi-001/primary.csv",
            )
            self.assertTrue(manifest_data["package_identity"]["local_path_redacted"])
            self.assertEqual(summary["artifact_posture"], "local_write_receipt")

    def test_writes_multiple_selected_measurements(self) -> None:
        source = _load_input()
        first_record = source["selected_measurements"][0]
        second_record = copy.deepcopy(first_record)
        second_content = b"drive_frequency,signal\n4.90,0.12\n4.95,0.44\n"
        second_id = "legacy-rabi-002"
        second_record["measurement_record_id"] = second_id
        second_record["legacy_data_id"] = 1002
        second_record["label"] = "Second Rabi calibration follow-up"
        second_record["primary_data"]["source_path"] = f"records/{second_id}/primary.csv"
        second_record["primary_data"]["expected_digest"] = _sha256_digest(second_content)
        second_record["primary_data"]["expected_size_bytes"] = len(second_content)
        second_record["primary_data"]["package_path"] = f"measurements/{second_id}/primary.csv"
        second_record["declared_preview_metadata"]["plot_candidates"][0]["source"] = (
            f"measurements/{second_id}/primary.csv"
        )
        second_record["default_bundle"][0]["item_id"] = f"{second_id}-primary"
        second_record["default_bundle"][0]["package_path"] = f"measurements/{second_id}/primary.csv"
        source["selected_measurements"].append(second_record)
        source["linked_context"][0]["linked_measurement_record_ids"].append(second_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            first_source = storage_root / "records" / "legacy-rabi-001" / "primary.csv"
            first_source.parent.mkdir(parents=True)
            first_content = (
                STORAGE_ROOT / "records" / "legacy-rabi-001" / "primary.csv"
            ).read_bytes()
            first_source.write_bytes(first_content)
            second_source = storage_root / "records" / second_id / "primary.csv"
            second_source.parent.mkdir(parents=True)
            second_source.write_bytes(second_content)
            package_root = temp_root / "packages"
            package_root.mkdir()

            summary = write_handoff_package(
                source,
                storage_root=storage_root,
                package_root=package_root,
            )

            package_dir = package_root / "handoff-package-legacy-rabi-001"
            self.assertEqual(
                _package_tree(package_dir),
                [
                    "measurements",
                    "measurements/legacy-rabi-001",
                    "measurements/legacy-rabi-001/primary.csv",
                    "measurements/legacy-rabi-002",
                    "measurements/legacy-rabi-002/primary.csv",
                    "package-manifest.json",
                ],
            )
            manifest_data = json.loads((package_dir / "package-manifest.json").read_bytes())
            self.assertEqual(len(manifest_data["selected_measurements"]), 2)
            self.assertEqual(len(summary["selected_measurements"]), 2)
            second_primary = package_dir / "measurements" / second_id / "primary.csv"
            self.assertEqual(second_primary.read_bytes(), second_content)
            second_manifest = manifest_data["selected_measurements"][1]
            self.assertEqual(second_manifest["measurement_record_id"], second_id)
            self.assertEqual(
                second_manifest["primary_data"]["package_path"],
                f"measurements/{second_id}/primary.csv",
            )
            self.assertEqual(
                second_manifest["primary_data"]["digest"],
                _sha256_digest(second_content),
            )
            self.assertEqual(second_manifest["primary_data"]["size_bytes"], len(second_content))
            self.assertEqual(
                manifest_data["linked_context"][0]["linked_measurement_record_ids"],
                ["legacy-rabi-001", second_id],
            )
            write_results = {item["path"]: item for item in summary["write_results"]}
            self.assertEqual(len(write_results), 3)
            self.assertEqual(
                [(item["path"], item["kind"]) for item in summary["write_results"]],
                [
                    (
                        "handoff-package-legacy-rabi-001/measurements/legacy-rabi-001/primary.csv",
                        "primary_data",
                    ),
                    (
                        "handoff-package-legacy-rabi-001/measurements/legacy-rabi-002/primary.csv",
                        "primary_data",
                    ),
                    ("handoff-package-legacy-rabi-001/package-manifest.json", "package_manifest"),
                ],
            )
            self.assertEqual(
                write_results[
                    "handoff-package-legacy-rabi-001/measurements/legacy-rabi-001/primary.csv"
                ]["bytes_written"],
                len(first_content),
            )
            self.assertEqual(
                write_results[
                    "handoff-package-legacy-rabi-001/measurements/legacy-rabi-001/primary.csv"
                ]["digest"],
                _sha256_digest(first_content),
            )
            self.assertEqual(
                write_results[
                    "handoff-package-legacy-rabi-001/measurements/legacy-rabi-002/primary.csv"
                ]["bytes_written"],
                len(second_content),
            )
            self.assertEqual(
                write_results[
                    "handoff-package-legacy-rabi-001/measurements/legacy-rabi-002/primary.csv"
                ]["digest"],
                _sha256_digest(second_content),
            )
            manifest_content = (package_dir / "package-manifest.json").read_bytes()
            self.assertEqual(
                write_results["handoff-package-legacy-rabi-001/package-manifest.json"][
                    "bytes_written"
                ],
                len(manifest_content),
            )
            self.assertEqual(
                write_results["handoff-package-legacy-rabi-001/package-manifest.json"]["digest"],
                _sha256_digest(manifest_content),
            )

    def test_write_requires_approval_and_no_overwrite_policy(self) -> None:
        source = _load_input()
        source["package_write_request"]["approval_state"] = "proposed"
        self.assertRejected(source, "must be approved")

        source = _load_input()
        source["package_write_request"]["collision_policy"] = "overwrite"
        self.assertRejected(source, "collision_policy")

    def test_package_directory_and_manifest_path_are_generated_topology(self) -> None:
        source = _load_input()
        source["package_write_request"]["package_dir"] = (
            "Users/lab/private/handoff-package-legacy-rabi-001"
        )
        source["package_write_request"]["manifest_path"] = (
            "Users/lab/private/handoff-package-legacy-rabi-001/package-manifest.json"
        )
        self.assertRejected(source, "package_dir must match package_id")

        source = _load_input()
        source["package_write_request"]["manifest_path"] = (
            "handoff-package-legacy-rabi-001/private-manifest.json"
        )
        self.assertRejected(source, "manifest_path must be package_id/package-manifest.json")

        source = _load_input()
        source["package_write_request"]["manifest_path"] = (
            "handoff-package-legacy-rabi-001/nested/package-manifest.json"
        )
        self.assertRejected(source, "manifest_path must be package_id/package-manifest.json")

    def test_existing_package_dir_is_refused_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            existing = package_root / "handoff-package-legacy-rabi-001"
            existing.mkdir()

            with self.assertRaisesRegex(ValueError, "target already exists"):
                write_handoff_package(
                    _load_input(),
                    storage_root=STORAGE_ROOT,
                    package_root=package_root,
                )

            self.assertEqual(list(existing.iterdir()), [])

    def test_source_digest_must_match_before_any_write(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["expected_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "digest does not match"):
                write_handoff_package(
                    source,
                    storage_root=STORAGE_ROOT,
                    package_root=package_root,
                )
            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())

    def test_source_size_must_match_before_any_write(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["expected_size_bytes"] = 999

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "size does not match"):
                write_handoff_package(
                    source,
                    storage_root=STORAGE_ROOT,
                    package_root=package_root,
                )
            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())

    def test_package_paths_must_stay_in_selected_measurement_namespace(self) -> None:
        for package_path in (
            "/private/package/primary.csv",
            "context/legacy-rabi-001/primary.csv",
            "measurements/other-record/primary.csv",
            "measurements/legacy-rabi-001/Users/lab/private-primary.csv",
            "measurements/legacy-rabi-001/raw/primary.csv",
            "measurements/legacy-rabi-001/primary-copy.csv",
        ):
            with self.subTest(package_path=package_path):
                source = _load_input()
                primary = source["selected_measurements"][0]["primary_data"]
                primary["package_path"] = package_path
                source["selected_measurements"][0]["default_bundle"][0]["package_path"] = (
                    package_path
                )
                source["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][
                    0
                ]["source"] = package_path
                self.assertRejected(source, "primary_data package_path")

    def test_linked_context_remains_reference_only(self) -> None:
        source = _load_input()
        source["linked_context"][0]["package_path"] = "context/parameter-snapshot.json"
        source["linked_context"][0]["package_state"] = "packaged"
        source["linked_context"][0]["reason"] = None

        self.assertRejected(source, "reference-only")

    def test_duplicate_measurement_ids_are_rejected(self) -> None:
        source = _load_input()
        source["selected_measurements"].append(copy.deepcopy(source["selected_measurements"][0]))
        self.assertRejected(source, "duplicate measurement_record_id")

    def test_default_bundle_path_must_match_primary_data(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["default_bundle"][0]["package_path"] = (
            "measurements/legacy-rabi-001/primary-copy.csv"
        )
        self.assertRejected(source, "default bundle")

    def test_plot_source_must_match_primary_data(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["declared_preview_metadata"]["plot_candidates"][0][
            "source"
        ] = "measurements/legacy-rabi-001/primary-copy.csv"
        self.assertRejected(source, "plot candidate source")

    def test_selected_measurements_must_not_be_empty(self) -> None:
        source = _load_input()
        source["selected_measurements"] = []
        source["linked_context"] = []
        self.assertRejected(source, "requires selected_measurements")

    def test_linked_measurement_targets_must_be_unique(self) -> None:
        source = _load_input()
        source["linked_context"][0]["linked_measurement_record_ids"] = [
            "legacy-rabi-001",
            "legacy-rabi-001",
        ]
        self.assertRejected(source, "targets must be unique")

    def test_linked_measurement_targets_must_be_a_list(self) -> None:
        source = _load_input()
        source["linked_context"][0]["linked_measurement_record_ids"] = {"legacy-rabi-001"}
        self.assertRejected(source, "targets must be a list")

        source = _load_input()
        source["linked_context"][0]["linked_measurement_record_ids"] = [
            {"measurement_record_id": "legacy-rabi-001"}
        ]
        self.assertRejected(source, "measurement target")

    def test_policy_keeps_archive_and_package_acceptance_out_of_scope(self) -> None:
        source = _load_input()
        source["package_write_policy"]["archive_creation"] = "performed"
        self.assertRejected(source, "archive_creation")

        source = _load_input()
        source["package_write_policy"]["package_acceptance"] = "performed"
        self.assertRejected(source, "package_acceptance")

        source = _load_input()
        source["package_write_policy"]["package_import"] = "available"
        self.assertRejected(source, "expected shape")

    def test_display_path_must_stay_redacted(self) -> None:
        source = _load_input()
        source["package_identity"]["display_path"] = (
            "HANDOFF_PACKAGE:/Users/lab/private/legacy-rabi-001"
        )

        self.assertRejected(source, "display_path")

        source = _load_input()
        source["package_identity"]["display_path"] = "HANDOFF_PACKAGE:/redacted/C:/lab-package"

        self.assertRejected(source, "display_path")

    def test_managed_identifiers_use_tight_public_grammar(self) -> None:
        source = _load_input()
        source["package_identity"]["package_id"] = "handoff-package-legacy-rabi-001\nsecret"
        source["package_write_request"]["package_dir"] = "handoff-package-legacy-rabi-001\nsecret"
        source["package_write_request"]["manifest_path"] = (
            "handoff-package-legacy-rabi-001\nsecret/package-manifest.json"
        )

        self.assertRejected(source, "package_id")

        source = _load_input()
        source["package_identity"]["package_id"] = "a" * 129
        source["package_write_request"]["package_dir"] = "a" * 129
        source["package_write_request"]["manifest_path"] = f"{'a' * 129}/package-manifest.json"
        self.assertRejected(source, "package_id")

        source = _load_input()
        source["selected_measurements"][0]["measurement_record_id"] = {
            "measurement_record_id": "legacy-rabi-001"
        }
        self.assertRejected(source, "measurement_record_id")

    def test_managed_linked_context_relation_must_be_public_identifier(self) -> None:
        source = _load_input()
        source["linked_context"][0]["relation"] = "/Users/lab/private/relation"

        self.assertRejected(source, "relation")

    def test_portable_manifest_schema_identifiers_must_be_public_safe(self) -> None:
        cases = [
            (
                "legacy_data_id",
                lambda source: source["selected_measurements"][0].update(
                    {"legacy_data_id": {"source_path": "/Users/lab/private/raw-id"}}
                ),
            ),
            (
                "data_shape kind",
                lambda source: source["selected_measurements"][0]["declared_preview_metadata"][
                    "data_shape"
                ].update({"kind": "/Users/lab/private/shape"}),
            ),
            (
                "column name",
                lambda source: source["selected_measurements"][0]["declared_preview_metadata"][
                    "declared_columns"
                ][0].update({"name": "/Users/lab/private/drive"}),
            ),
            (
                "column role",
                lambda source: source["selected_measurements"][0]["declared_preview_metadata"][
                    "declared_columns"
                ][0].update({"role": "/Users/lab/private/role"}),
            ),
            (
                "column unit",
                lambda source: source["selected_measurements"][0]["declared_preview_metadata"][
                    "declared_columns"
                ][0].update({"unit": "/Users/lab/private/unit"}),
            ),
            (
                "axis_order entry",
                lambda source: source["selected_measurements"][0]["declared_preview_metadata"][
                    "data_shape"
                ].update({"axis_order": ["/Users/lab/private/drive", "signal"]}),
            ),
            (
                "plot x",
                lambda source: source["selected_measurements"][0]["declared_preview_metadata"][
                    "plot_candidates"
                ][0].update({"x": "/Users/lab/private/drive"}),
            ),
            (
                "plot y",
                lambda source: source["selected_measurements"][0]["declared_preview_metadata"][
                    "plot_candidates"
                ][0].update({"y": "/Users/lab/private/signal"}),
            ),
        ]

        for expected_error, mutate in cases:
            with self.subTest(expected_error=expected_error):
                source = _load_input()
                mutate(source)
                self.assertRejected(source, expected_error)

    def test_portable_manifest_allows_reviewed_free_text_labels_and_reasons(self) -> None:
        source = _load_input()
        source["package_identity"]["display_name"] = "Reviewed /Users-looking label"
        source["selected_measurements"][0]["label"] = "Reviewed /Users-looking measurement label"
        source["selected_measurements"][0]["primary_data"]["label"] = (
            "Reviewed /Users-looking primary label"
        )
        source["selected_measurements"][0]["default_bundle"][0]["label"] = (
            "Reviewed /Users-looking primary label"
        )
        source["selected_measurements"][0]["declared_preview_metadata"]["declared_columns"][0][
            "label"
        ] = "Reviewed /Users-looking column label"
        source["linked_context"][0]["label"] = "Reviewed /Users-looking context label"
        source["linked_context"][0]["reason"] = "Reviewed /Users-looking context reason"

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            write_handoff_package(
                source,
                storage_root=STORAGE_ROOT,
                package_root=package_root,
            )
            manifest = json.loads(
                (
                    package_root / "handoff-package-legacy-rabi-001" / "package-manifest.json"
                ).read_bytes()
            )

        measurement = manifest["selected_measurements"][0]
        self.assertEqual(
            manifest["package_identity"]["display_name"],
            "Reviewed /Users-looking label",
        )
        self.assertEqual(measurement["label"], "Reviewed /Users-looking measurement label")
        self.assertEqual(
            measurement["primary_data"]["label"],
            "Reviewed /Users-looking primary label",
        )
        self.assertEqual(
            measurement["default_bundle"][0]["label"],
            "Reviewed /Users-looking primary label",
        )
        self.assertEqual(
            measurement["declared_preview_metadata"]["declared_columns"][0]["label"],
            "Reviewed /Users-looking column label",
        )
        self.assertEqual(
            manifest["linked_context"][0]["label"],
            "Reviewed /Users-looking context label",
        )
        self.assertEqual(
            manifest["linked_context"][0]["reason"],
            "Reviewed /Users-looking context reason",
        )

    def test_portable_manifest_projects_allowlisted_fields_only(self) -> None:
        source = _load_input()
        record = source["selected_measurements"][0]
        record["declared_preview_metadata"]["source_path"] = "/Users/lab/private/preview.json"
        record["declared_preview_metadata"]["declared_columns"][0]["internal_note"] = (
            "/Users/lab/private/column-note"
        )
        record["declared_preview_metadata"]["plot_candidates"][0]["debug_source"] = (
            "/Users/lab/private/plot.json"
        )
        record["default_bundle"][0]["source_path"] = "/Users/lab/private/bundle.csv"
        source["linked_context"][0]["source_path"] = "/Users/lab/private/context.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            write_handoff_package(source, storage_root=STORAGE_ROOT, package_root=package_root)

            manifest = package_root / "handoff-package-legacy-rabi-001" / "package-manifest.json"
            manifest_text = manifest.read_text(encoding="utf-8")
            self.assertNotIn("source_path", manifest_text)
            self.assertNotIn("internal_note", manifest_text)
            self.assertNotIn("debug_source", manifest_text)
            self.assertNotIn("/Users/lab/private", manifest_text)

    def test_symlink_package_root_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "package-root"
            escape_root = Path(temp_dir) / "escape"
            escape_root.mkdir()
            package_root.symlink_to(escape_root, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "package root must not be a symlink"):
                write_handoff_package(
                    _load_input(),
                    storage_root=STORAGE_ROOT,
                    package_root=package_root,
                )
            self.assertEqual(list(escape_root.iterdir()), [])

    def test_package_root_must_not_overlap_storage_root(self) -> None:
        source = _load_input()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            source_file = storage_root / "records" / "legacy-rabi-001" / "primary.csv"
            source_file.parent.mkdir(parents=True)
            source_file.write_bytes(
                (STORAGE_ROOT / "records" / "legacy-rabi-001" / "primary.csv").read_bytes()
            )

            with self.assertRaisesRegex(ValueError, "outside measurement storage"):
                write_handoff_package(
                    source,
                    storage_root=storage_root,
                    package_root=storage_root,
                )
            self.assertFalse((storage_root / "handoff-package-legacy-rabi-001").exists())

            package_root = storage_root / "packages"
            package_root.mkdir()

            with self.assertRaisesRegex(ValueError, "outside measurement storage"):
                write_handoff_package(
                    source,
                    storage_root=storage_root,
                    package_root=package_root,
                )

            self.assertEqual(list(package_root.iterdir()), [])

    def test_missing_source_parent_is_reported_as_unavailable_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            package_root = temp_root / "packages"
            package_root.mkdir()

            with self.assertRaisesRegex(ValueError, "source file is unavailable"):
                write_handoff_package(
                    _load_input(),
                    storage_root=storage_root,
                    package_root=package_root,
                )
            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())

    def test_source_symlink_file_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            source_dir = storage_root / "records" / "legacy-rabi-001"
            source_dir.mkdir(parents=True)
            (source_dir / "primary.csv").symlink_to(
                STORAGE_ROOT / "records" / "legacy-rabi-001" / "primary.csv"
            )

            package_root = Path(temp_dir) / "packages"
            package_root.mkdir()
            with self.assertRaisesRegex(ValueError, "source file is unavailable"):
                write_handoff_package(
                    _load_input(),
                    storage_root=storage_root,
                    package_root=package_root,
                )
            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())

    def test_source_symlink_parent_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            real_records = temp_root / "real-records"
            real_records.mkdir(parents=True)
            storage_root.mkdir()
            (storage_root / "records").symlink_to(real_records, target_is_directory=True)

            package_root = temp_root / "packages"
            package_root.mkdir()
            with self.assertRaisesRegex(ValueError, "source parent is a symlink"):
                write_handoff_package(
                    _load_input(),
                    storage_root=storage_root,
                    package_root=package_root,
                )
            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            records_dir = storage_root / "records"
            real_record = temp_root / "real-record"
            records_dir.mkdir(parents=True)
            real_record.mkdir()
            (records_dir / "legacy-rabi-001").symlink_to(
                real_record,
                target_is_directory=True,
            )

            package_root = temp_root / "packages"
            package_root.mkdir()
            with self.assertRaisesRegex(ValueError, "source parent is a symlink"):
                write_handoff_package(
                    _load_input(),
                    storage_root=storage_root,
                    package_root=package_root,
                )
            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())

    def test_late_write_failure_rolls_back_partial_package(self) -> None:
        real_write = writer_module._write_new_file
        calls = 0

        def fail_on_manifest(package_root: Path, relative_path: str, content: bytes) -> list[str]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated manifest write failure")
            return real_write(package_root, relative_path, content)

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            with mock.patch.object(writer_module, "_write_new_file", side_effect=fail_on_manifest):
                with self.assertRaisesRegex(RuntimeError, "simulated manifest write failure"):
                    write_handoff_package(
                        _load_input(),
                        storage_root=STORAGE_ROOT,
                        package_root=package_root,
                    )

            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())


if __name__ == "__main__":
    unittest.main()

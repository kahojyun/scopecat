from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import open_package, write_package

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "handoff"
    / "handoff_engineering_prototype_writer"
    / "basic_package"
)
SOURCE_ROOT = FIXTURE / "source"
LEGACY_CANDIDATE_FIXTURE = ROOT / "tests" / "fixtures" / "handoff_package_writer" / "basic_package"


def _load_input() -> dict:
    return json.loads((FIXTURE / "package-writer-input.json").read_text(encoding="utf-8"))


def _load_storage_named_input() -> dict:
    return json.loads(
        (LEGACY_CANDIDATE_FIXTURE / "package-writer-input.json").read_text(encoding="utf-8")
    )


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _package_tree(package_dir: Path) -> list[str]:
    return sorted(path.relative_to(package_dir).as_posix() for path in package_dir.rglob("*"))


class HandoffEngineeringPrototypeWriterTest(unittest.TestCase):
    def assertRejected(self, source: dict, pattern: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, pattern):
                write_package(
                    source,
                    source_root=SOURCE_ROOT,
                    package_root=Path(temp_dir),
                )

    def test_writes_package_from_declared_source_root_and_opens_with_reader(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            receipt = write_package(
                _load_input(),
                source_root=SOURCE_ROOT,
                package_root=package_root,
            )
            package_dir = package_root / "handoff-package-legacy-rabi-001"
            package = open_package(package_dir)
            package_tree = _package_tree(package_dir)
            manifest_bytes = (package_dir / "package-manifest.json").read_bytes()
            receipt_summary = receipt.to_dict()

        self.assertEqual(
            package_tree,
            [
                "measurements",
                "measurements/legacy-rabi-001",
                "measurements/legacy-rabi-001/primary.csv",
                "package-manifest.json",
            ],
        )
        self.assertEqual(package.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(package.measurement_ids, ("legacy-rabi-001",))
        measurement = package.measurement("legacy-rabi-001")
        self.assertEqual(measurement.primary_table.row_count, 5)
        self.assertEqual(
            [
                (series.x_name, series.y_name, len(series.points))
                for series in measurement.plot_series
            ],
            [("drive_frequency", "signal", 5)],
        )

        self.assertEqual(manifest_bytes, (FIXTURE / "expected-package-manifest.json").read_bytes())
        self.assertEqual(receipt_summary["artifact_posture"], "local_write_receipt")
        self.assertEqual(
            receipt_summary["package_write_policy"]["source_authority"],
            "caller_provided_source_root_plus_declared_relative_paths",
        )
        self.assertEqual(
            receipt_summary["package_write_policy"]["source_mutation"], "not_performed"
        )
        self.assertNotIn("storage_root", json.dumps(receipt_summary, sort_keys=True))
        self.assertEqual(
            receipt_summary["write_results"][1]["digest"],
            _sha256_digest(manifest_bytes),
        )

    def test_storage_named_policy_is_rejected_at_promoted_boundary(self) -> None:
        self.assertRejected(_load_storage_named_input(), "expected shape")

    def test_rejects_unsupported_raw_writer_fields(self) -> None:
        cases = [
            ("top_level", ("storage_root",)),
            ("package_write_request", ("package_write_request", "destination_record_id")),
            ("package_identity", ("package_identity", "local_path")),
            ("selected_measurement", ("selected_measurements", 0, "storage_record")),
            ("primary_data", ("selected_measurements", 0, "primary_data", "local_path")),
            (
                "preview_metadata",
                ("selected_measurements", 0, "declared_preview_metadata", "schema_inference"),
            ),
            (
                "default_bundle",
                ("selected_measurements", 0, "default_bundle", 0, "payload_path"),
            ),
            ("linked_context", ("linked_context", 0, "payload")),
        ]

        for label, path in cases:
            with self.subTest(label=label):
                source = _load_input()
                target = source
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = "unsupported"
                self.assertRejected(source, "fields are unsupported")

    def test_source_digest_must_match_before_any_write(self) -> None:
        source = _load_input()
        source["selected_measurements"][0]["primary_data"]["expected_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "digest does not match"):
                write_package(source, source_root=SOURCE_ROOT, package_root=package_root)
            self.assertFalse((package_root / "handoff-package-legacy-rabi-001").exists())

    def test_package_root_must_not_overlap_source_root(self) -> None:
        source = _load_input()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "source"
            source_file = source_root / "records" / "legacy-rabi-001" / "primary.csv"
            source_file.parent.mkdir(parents=True)
            source_file.write_bytes(
                (SOURCE_ROOT / "records" / "legacy-rabi-001" / "primary.csv").read_bytes()
            )
            with self.assertRaisesRegex(ValueError, "outside source root"):
                write_package(source, source_root=source_root, package_root=source_root)

            package_root = source_root / "packages"
            package_root.mkdir()
            with self.assertRaisesRegex(ValueError, "outside source root"):
                write_package(source, source_root=source_root, package_root=package_root)
            self.assertEqual(list(package_root.iterdir()), [])

            package_parent = temp_root
            with self.assertRaisesRegex(ValueError, "outside package root"):
                write_package(source, source_root=source_root, package_root=package_parent)
            self.assertEqual(list(package_parent.iterdir()), [source_root])

    def test_multiple_selected_measurements_round_trip_through_reader(self) -> None:
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
            source_root = temp_root / "source"
            first_source = source_root / "records" / "legacy-rabi-001" / "primary.csv"
            first_source.parent.mkdir(parents=True)
            first_source.write_bytes(
                (SOURCE_ROOT / "records" / "legacy-rabi-001" / "primary.csv").read_bytes()
            )
            second_source = source_root / "records" / second_id / "primary.csv"
            second_source.parent.mkdir(parents=True)
            second_source.write_bytes(second_content)
            package_root = temp_root / "packages"
            package_root.mkdir()

            write_package(source, source_root=source_root, package_root=package_root)
            package = open_package(package_root / "handoff-package-legacy-rabi-001")

        self.assertEqual(package.measurement_ids, ("legacy-rabi-001", "legacy-rabi-002"))
        self.assertEqual(package.measurement("legacy-rabi-002").primary_table.row_count, 2)

    def test_linked_context_reference_metadata_round_trips_without_payload(self) -> None:
        source = _load_input()
        source["linked_context"][0]["context_reference"] = {
            "reference_id": "parameter-state-rabi-001",
            "reference_kind": "parameter_state",
            "reference_family": "parameter_state",
            "materialization": "reference_only",
            "payload_import": "not_performed",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            write_package(
                source,
                source_root=SOURCE_ROOT,
                package_root=package_root,
            )
            package = open_package(package_root / "handoff-package-legacy-rabi-001")

        context = package.linked_context[0].to_dict()
        self.assertEqual(
            context["context_reference"],
            {
                "reference_id": "parameter-state-rabi-001",
                "reference_kind": "parameter_state",
                "reference_family": "parameter_state",
                "materialization": "reference_only",
                "payload_import": "not_performed",
            },
        )
        self.assertEqual(context["materialization"], "reference_only")

    def test_linked_context_reference_metadata_cannot_claim_payload_import(self) -> None:
        source = _load_input()
        source["linked_context"][0]["context_reference"] = {
            "reference_id": "parameter-state-rabi-001",
            "reference_kind": "parameter_state",
            "reference_family": "parameter_state",
            "materialization": "reference_only",
            "payload_import": "copy_payload",
        }

        self.assertRejected(source, "payload_import")

    def test_prepared_run_context_reference_family_requires_prepared_run_kind(self) -> None:
        source = _load_input()
        source["linked_context"][0]["context_reference"] = {
            "reference_id": "prepared-run-context-rabi-001",
            "reference_kind": "parameter_state",
            "reference_family": "prepared_run",
            "materialization": "reference_only",
            "payload_import": "not_performed",
        }

        self.assertRejected(source, "prepared_run references")


if __name__ == "__main__":
    unittest.main()

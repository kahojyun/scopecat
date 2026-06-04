from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scopecat.parameter_state import (
    build_adapter_parameter_import_review_commit_summary,
    read_parameter_state_storage_view,
    read_source_agnostic_parameter_state_view,
    write_parameter_state_storage,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "prototypes" / "parameter_state"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ParameterStateEngineeringPrototypeTest(unittest.TestCase):
    def test_adapter_import_review_commit_accepts_reviewed_entries(self) -> None:
        fixture = FIXTURES / "adapter_parameter_import_review_commit" / "basic_review_commit"

        summary = build_adapter_parameter_import_review_commit_summary(
            _load(fixture / "review-commit-input.json")
        )

        self.assertEqual(
            summary["preview_summary"]["classification"],
            "preview_ready_with_findings",
        )
        self.assertEqual(
            summary["managed_parameter_state"]["state_id"],
            "param-state-imported-0001",
        )
        self.assertEqual(len(summary["managed_parameter_state"]["entries"]), 2)
        self.assertEqual(summary["review"]["review_status"], "accepted")

    def test_storage_writer_and_read_view_round_trip_declared_files(self) -> None:
        writer_fixture = FIXTURES / "parameter_state_storage_writer" / "basic_write"
        read_fixture = FIXTURES / "parameter_state_storage_read_view" / "basic_read"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            write_summary = write_parameter_state_storage(
                _load(writer_fixture / "storage-writer-input.json"),
                storage_root=storage_root,
            )
            read_input = _load(read_fixture / "read-view-input.json")
            for result in write_summary["write_results"]:
                if result["kind"] == "parameter_state_manifest":
                    read_input["read_request"]["expected_manifest_digest"] = result["digest"]
                    read_input["read_request"]["expected_manifest_size_bytes"] = result[
                        "bytes_written"
                    ]
                elif result["kind"] == "write_receipt":
                    read_input["read_request"]["expected_receipt_digest"] = result["digest"]
                    read_input["read_request"]["expected_receipt_size_bytes"] = result[
                        "bytes_written"
                    ]

            read_summary = read_parameter_state_storage_view(read_input, storage_root=storage_root)

        self.assertEqual(read_summary["classification"], "stored_parameter_state_read_view_ready")
        self.assertEqual(
            read_summary["parameter_state"]["state_id"],
            write_summary["parameter_state"]["state_id"],
        )
        self.assertEqual(read_summary["review_findings"], [])

    def test_source_agnostic_read_view_projects_adapter_state(self) -> None:
        read_fixture = FIXTURES / "source_agnostic_parameter_state_read_view" / "basic_read"
        storage_fixture = FIXTURES / "parameter_state_storage_read_view" / "basic_read"
        read_input = _load(read_fixture / "read-view-input.json")
        read_input["read_requests"] = read_input["read_requests"][:1]

        summary = read_source_agnostic_parameter_state_view(
            read_input,
            storage_root=storage_fixture / "storage",
        )

        self.assertEqual(summary["classification"], "all_explicit_parameter_states_ready")
        stored_state = summary["stored_states"][0]
        self.assertEqual(stored_state["source_kind"], "adapter_import")
        self.assertEqual(
            stored_state["parameter_state"]["state_id"],
            "param-state-imported-0001",
        )
        self.assertEqual(
            set(stored_state["typed_provenance"]),
            {"source_kind", "payload", "source_review"},
        )

    def test_storage_writer_requires_approval_before_mutation(self) -> None:
        writer_fixture = FIXTURES / "parameter_state_storage_writer" / "basic_write"
        source = _load(writer_fixture / "storage-writer-input.json")
        source["storage_request"]["approval"]["approval_state"] = "proposed"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "must be approved"):
                write_parameter_state_storage(source, storage_root=storage_root)

            self.assertEqual(list(storage_root.iterdir()), [])

    def test_storage_writer_rejects_collision_and_malformed_paths_before_write(self) -> None:
        writer_fixture = FIXTURES / "parameter_state_storage_writer" / "basic_write"

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state_dir = storage_root / "parameter-states" / "param-state-imported-0001"
            state_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "target already exists"):
                write_parameter_state_storage(
                    _load(writer_fixture / "storage-writer-input.json"),
                    storage_root=storage_root,
                )

            self.assertFalse((state_dir / "parameter-state.json").exists())

        source = _load(writer_fixture / "storage-writer-input.json")
        source["storage_request"]["manifest_path"] = "../parameter-state.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "manifest_path path"):
                write_parameter_state_storage(source, storage_root=storage_root)

            self.assertEqual(list(storage_root.iterdir()), [])

    def test_storage_read_view_reports_digest_mismatch_without_mutation(self) -> None:
        read_fixture = FIXTURES / "parameter_state_storage_read_view" / "basic_read"
        source = _load(read_fixture / "read-view-input.json")
        source["read_request"]["expected_manifest_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        manifest_path = read_fixture / "storage" / source["read_request"]["manifest_path"]
        before = manifest_path.read_bytes()

        summary = read_parameter_state_storage_view(source, storage_root=read_fixture / "storage")

        self.assertEqual(
            summary["classification"],
            "stored_parameter_state_observed_with_mismatch",
        )
        self.assertIn(
            "manifest_digest_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_adapter_import_review_rejects_missing_source_reference(self) -> None:
        fixture = FIXTURES / "adapter_parameter_import_review_commit" / "basic_review_commit"
        source = _load(fixture / "review-commit-input.json")
        source["managed_parameter_state"]["entries"][0]["source_ids"] = [
            "legacy-xlsx-parameter-table-001"
        ]

        with self.assertRaisesRegex(ValueError, "sources must come from preview"):
            build_adapter_parameter_import_review_commit_summary(source)


if __name__ == "__main__":
    unittest.main()

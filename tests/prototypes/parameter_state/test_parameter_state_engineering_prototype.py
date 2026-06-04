from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.parameter_state import (
    build_adapter_parameter_import_review_commit_summary,
    build_parameter_state_selection_summary,
    build_prepared_run_source_agnostic_parameter_state_consumption_summary,
    build_prepared_run_source_agnostic_parameter_state_review_chain_summary,
    read_parameter_state_storage_view,
    read_source_agnostic_parameter_state_view,
    write_parameter_state_storage,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "prototypes" / "parameter_state"
ADAPTER_STORAGE_FIXTURE = FIXTURES / "parameter_state_storage_read_view" / "basic_read"


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

    def test_source_agnostic_read_view_and_prepared_run_chain_match_contracts(self) -> None:
        read_fixture = FIXTURES / "source_agnostic_parameter_state_read_view" / "basic_read"
        consumption_fixture = (
            FIXTURES
            / "prepared_run_source_agnostic_parameter_state_consumption"
            / "basic_consumption"
        )
        chain_fixture = (
            FIXTURES / "prepared_run_source_agnostic_parameter_state_review_chain" / "basic_chain"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            shutil.copytree(ADAPTER_STORAGE_FIXTURE / "storage", storage_root)
            read_input = _load(read_fixture / "read-view-input.json")
            read_input["read_requests"] = read_input["read_requests"][:1]
            read_summary = read_source_agnostic_parameter_state_view(
                read_input,
                storage_root=storage_root,
            )

        consumption_input = _load(consumption_fixture / "consumption-input.json")
        consumption_summary = (
            build_prepared_run_source_agnostic_parameter_state_consumption_summary(
                consumption_input
            )
        )
        chain_input = _load(chain_fixture / "review-chain-input.json")
        chain_input["source_agnostic_consumption_summary"] = consumption_summary
        chain_input["gate_input"]["parameter_state_consumption_summary"] = consumption_summary
        chain_input["scope_alignment_input"]["parameter_state_consumption_summary"] = (
            consumption_summary
        )
        chain_summary = build_prepared_run_source_agnostic_parameter_state_review_chain_summary(
            chain_input
        )

        self.assertEqual(read_summary["classification"], "all_explicit_parameter_states_ready")
        self.assertEqual(
            consumption_summary["classification"], "prepared_run_parameter_state_ready"
        )
        self.assertEqual(
            chain_summary["classification"],
            "parameter_review_chain_needs_review",
        )
        self.assertIn(
            "parameter_lineage_partial_target_coverage",
            {finding["code"] for finding in chain_summary["review_findings"]},
        )

    def test_adapter_imported_state_reaches_prepared_run_review_chain(self) -> None:
        read_fixture = FIXTURES / "source_agnostic_parameter_state_read_view" / "basic_read"
        consumption_fixture = (
            FIXTURES
            / "prepared_run_source_agnostic_parameter_state_consumption"
            / "basic_consumption"
        )
        chain_fixture = (
            FIXTURES / "prepared_run_source_agnostic_parameter_state_review_chain" / "basic_chain"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            shutil.copytree(ADAPTER_STORAGE_FIXTURE / "storage", storage_root)
            read_input = _load(read_fixture / "read-view-input.json")
            read_input["read_requests"] = read_input["read_requests"][:1]
            read_summary = read_source_agnostic_parameter_state_view(
                read_input,
                storage_root=storage_root,
            )

        adapter_state_id = "param-state-imported-0001"
        consumption_input = _load(consumption_fixture / "consumption-input.json")
        consumption_input["source_agnostic_read_view_summary"] = read_summary
        consumption_input["consumption_request"]["expected_state_id"] = adapter_state_id
        consumption_input["consumption_request"]["parameter_context_id"] = adapter_state_id
        for context_ref in consumption_input["prepared_run_context_summary"][
            "selected_context_refs"
        ]:
            if context_ref["family"] == "parameter_state":
                context_ref["context_id"] = adapter_state_id
                context_ref["context_label"] = "qA default bias imported seed"
                context_ref["record_status"] = "trusted_for_declared_scope"

        consumption_summary = (
            build_prepared_run_source_agnostic_parameter_state_consumption_summary(
                consumption_input
            )
        )
        chain_input = _load(chain_fixture / "review-chain-input.json")
        chain_input["source_agnostic_consumption_summary"] = consumption_summary
        chain_input["gate_input"]["parameter_state_consumption_summary"] = consumption_summary
        chain_input["gate_input"]["gate_request"]["expected_state_id"] = adapter_state_id
        chain_input["scope_alignment_input"]["parameter_state_consumption_summary"] = (
            consumption_summary
        )

        chain_summary = build_prepared_run_source_agnostic_parameter_state_review_chain_summary(
            chain_input
        )

        self.assertEqual(consumption_summary["parameter_state"]["source_kind"], "adapter_import")
        self.assertEqual(chain_summary["selected_parameter_state"]["source_kind"], "adapter_import")
        self.assertEqual(chain_summary["classification"], "parameter_review_chain_needs_review")

    def test_selection_context_reports_ready_future_context(self) -> None:
        fixture = FIXTURES / "parameter_state_selection_context" / "known_good_future_context"

        summary = build_parameter_state_selection_summary(
            _load(fixture / "parameter-state-selection-input.json")
        )

        selection = summary["parameter_state_selections"][0]
        self.assertEqual(selection["selection_status"], "selected_for_context")
        self.assertEqual(
            selection["selected_state_id"],
            "param-state-0002",
        )
        self.assertEqual(selection["selected_state_trust_status"], "trusted_for_declared_scope")
        self.assertEqual(
            {finding["kind"] for finding in summary["review_findings"]},
            {
                "context_requirement_satisfied",
                "intent_label_is_scenario_semantics",
            },
        )


if __name__ == "__main__":
    unittest.main()

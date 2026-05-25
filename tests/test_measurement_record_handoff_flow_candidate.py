from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.measurement_record_handoff_flow import (
    build_measurement_record_handoff_flow_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurement_record_handoff_flow" / "basic_flow"
STORAGE_ROOT = FIXTURE / "storage"
WRITE_RESULT_KEYS = {"path", "kind", "result", "bytes_written", "digest", "does_not_claim"}
PREVIEW_COLUMN_KEYS = {"name", "role", "label", "unit"}
ACCEPTED_LINKED_CONTEXT_KEYS = {
    "link_id",
    "kind",
    "role",
    "label",
    "reference",
    "authority",
    "reference_state",
    "reason",
}
EXPORT_LINKED_CONTEXT_KEYS = {
    "kind",
    "label",
    "path",
    "include_status",
    "relation",
    "authority",
    "linked_legacy_data_ids",
}
PACKAGE_CONTENT_KEYS = {
    "owner_type",
    "owner_id",
    "item_id",
    "kind",
    "label",
    "package_path",
    "include_status",
    "relation",
    "authority",
    "package_state",
    "reason",
}
PACKAGE_PRIMARY_DATA_KEYS = {
    "kind",
    "label",
    "package_path",
    "include_status",
    "relation",
    "authority",
    "format",
    "package_state",
    "reason",
}


def _load_input() -> dict:
    return json.loads((FIXTURE / "flow-input.json").read_text(encoding="utf-8"))


def _walk_json(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)
    else:
        yield value


def _add_operator_note_context_ref(source: dict, *, path: str | None = None) -> None:
    extra_context = copy.deepcopy(source["accepted_record"]["linked_context"][0])
    extra_context["link_id"] = "legacy-001-run-note"
    extra_context["kind"] = "run_note"
    extra_context["role"] = "operator_note"
    extra_context["label"] = "Operator note"
    extra_context["reference"] = "legacy-record-001 operator note"
    source["accepted_record"]["linked_context"].append(extra_context)

    extra_ref = copy.deepcopy(source["linked_context_export_refs"][0])
    extra_ref["source_link_id"] = "legacy-001-run-note"
    extra_ref["relation"] = "operator_note"
    if path is not None:
        extra_ref["path"] = path
    source["linked_context_export_refs"].append(extra_ref)


class MeasurementRecordHandoffFlowCandidateTest(unittest.TestCase):
    def assertRejected(self, source: dict, pattern: str) -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_builds_expected_flow_summary(self) -> None:
        summary = build_measurement_record_handoff_flow_summary(
            _load_input(),
            storage_root=STORAGE_ROOT,
        )
        expected = json.loads((FIXTURE / "expected-flow-summary.json").read_text(encoding="utf-8"))[
            "candidate_summary"
        ]

        self.assertEqual(summary, expected)

    def test_flow_is_side_effect_free_and_does_not_accept_imports(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as storage_dir:
            storage_root = Path(storage_dir)
            records_dir = storage_root / "records"

            summary = build_measurement_record_handoff_flow_summary(
                source,
                storage_root=storage_root,
            )

            self.assertFalse(records_dir.exists())
            self.assertEqual(summary["flow"]["storage_mutation"], "not_performed")
            self.assertEqual(
                summary["flow"]["classification"],
                "handoff_package_needs_source_observation_review",
            )
            self.assertEqual(
                summary["source_observation"]["measurement_record"]["classification"],
                "source_unavailable_for_review",
            )
            self.assertEqual(
                summary["source_observation"]["review_findings"][0]["code"],
                "primary_data_unavailable",
            )

    def test_source_observation_findings_drive_flow_review_classification(self) -> None:
        source = _load_input()
        source["accepted_record"]["write_results"][0]["digest"] = f"sha256:{'0' * 64}"

        summary = build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )

        self.assertEqual(
            summary["flow"]["classification"],
            "handoff_package_needs_source_observation_review",
        )
        self.assertEqual(
            summary["source_observation"]["measurement_record"]["classification"],
            "source_observed_with_mismatch",
        )
        self.assertEqual(
            summary["source_observation"]["review_findings"][0]["code"],
            "primary_data_digest_mismatch",
        )

    def test_identity_and_preview_metadata_survive_slice_handoffs(self) -> None:
        summary = build_measurement_record_handoff_flow_summary(
            _load_input(),
            storage_root=STORAGE_ROOT,
        )

        trace = summary["identity_trace"]
        self.assertEqual(trace["measurement_record_id"], "legacy-rabi-001")
        self.assertEqual(trace["legacy_data_id"], 1001)
        self.assertEqual(trace["external_record_id"], "legacy-record-001")
        self.assertEqual(trace["stored_primary_data_path"], "records/legacy-rabi-001/primary.csv")
        self.assertEqual(
            trace["package_primary_data_path"],
            "measurements/legacy-rabi-001/primary.csv",
        )

        exported = summary["selected_measurement_export"]["measurements"][0]
        packaged = summary["handoff_package_preview"]["selected_measurements"][0]
        self.assertEqual(exported["preview"]["status"], "preview_ready")
        self.assertEqual(exported["preview"]["axis_order"], ["drive_frequency", "signal"])
        self.assertEqual(packaged["preview"]["axis_order"], ["drive_frequency", "signal"])
        self.assertEqual(
            packaged["preview"]["plot_candidates"][0]["source"],
            "measurements/legacy-rabi-001/primary.csv",
        )

    def test_linked_context_export_path_must_stay_in_context_namespace(self) -> None:
        source = _load_input()
        source["linked_context_export_refs"][0]["path"] = "/Users/lab/private/params.json"

        with self.assertRaisesRegex(ValueError, "linked context export ref"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["linked_context_export_refs"][0]["path"] = (
            "measurements/legacy-rabi-001/params.reference.json"
        )
        self.assertRejected(source, "linked context export ref")

        source = _load_input()
        source["linked_context_export_refs"][0]["path"] = (
            "context/private/customer-params.reference.json"
        )
        summary = build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )
        self.assertEqual(
            summary["selected_measurement_export"]["linked_context"][0]["path"],
            "context/private/customer-params.reference.json",
        )

    def test_linked_context_export_paths_are_unique_managed_refs(self) -> None:
        source = _load_input()
        _add_operator_note_context_ref(source)
        self.assertRejected(source, "duplicate linked context export path")

        source = _load_input()
        _add_operator_note_context_ref(
            source,
            path="context/legacy-001-parameter-snapshot.reference.json/nested",
        )
        self.assertRejected(source, "overlapping linked context export path")

    def test_package_manifest_is_explicit_input_not_synthesized(self) -> None:
        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["primary_data"][
            "package_path"
        ] = "measurements/legacy-rabi-001/custom-primary.csv"
        source["handoff_package_manifest"]["selected_measurements"][0]["default_bundle"][0][
            "package_path"
        ] = "measurements/legacy-rabi-001/custom-primary.csv"
        source["handoff_package_manifest"]["selected_measurements"][0]["declared_preview_metadata"][
            "plot_candidates"
        ][0]["source"] = "measurements/legacy-rabi-001/custom-primary.csv"

        summary = build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )

        self.assertEqual(
            summary["identity_trace"]["package_primary_data_path"],
            "measurements/legacy-rabi-001/custom-primary.csv",
        )
        packaged_record = summary["handoff_package_preview"]["selected_measurements"][0]
        self.assertEqual(
            packaged_record["primary_data"]["package_path"],
            "measurements/legacy-rabi-001/custom-primary.csv",
        )
        self.assertEqual(
            packaged_record["preview"]["plot_candidates"][0]["source"],
            "measurements/legacy-rabi-001/custom-primary.csv",
        )
        self.assertEqual(
            summary["handoff_package_preview"]["package_contents"][0]["package_path"],
            "measurements/legacy-rabi-001/custom-primary.csv",
        )

    def test_package_manifest_must_match_accepted_record_identity(self) -> None:
        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["measurement_record_id"] = (
            "legacy-rabi-002"
        )

        with self.assertRaisesRegex(ValueError, "measurement_record_id"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_accepted_record_must_be_approved_and_imported_ready(self) -> None:
        source = _load_input()
        source["accepted_record"]["acceptance_request"]["approval_state"] = "pending_review"

        with self.assertRaisesRegex(ValueError, "approval_state"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["measurement_record"]["classification"] = "blocked_pending_review"

        with self.assertRaisesRegex(ValueError, "classification"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["measurement_record"]["source_kind"] = "reference_only_import"

        with self.assertRaisesRegex(ValueError, "source_kind"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["reviewed_manifest_classification"] = (
            "blocked_by_adapter_finding"
        )

        with self.assertRaisesRegex(ValueError, "reviewed manifest"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["collision_policy"] = "overwrite"

        with self.assertRaisesRegex(ValueError, "collision_policy"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_accepted_record_storage_paths_must_stay_inside_record_dir(self) -> None:
        source = _load_input()
        source["accepted_record"]["acceptance_request"]["manifest_path"] = (
            "records/other-record/record-manifest.json"
        )

        with self.assertRaisesRegex(ValueError, "manifest_path"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["primary_data_path"] = (
            "/Users/lab/private/primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "primary_data_path"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["primary_data_path"] = (
            "records/legacy-rabi-001"
        )
        source["accepted_record"]["write_results"][0]["path"] = "records/legacy-rabi-001"

        with self.assertRaisesRegex(ValueError, "primary_data_path"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["record_dir"] = "/Users/lab/private"

        with self.assertRaisesRegex(ValueError, "record_dir"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["manifest_path"] = "records/legacy-rabi-001"
        source["accepted_record"]["write_results"][1]["path"] = "records/legacy-rabi-001"

        with self.assertRaisesRegex(ValueError, "manifest_path"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["manifest_path"] = (
            "records/legacy-rabi-001/primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "must not overlap"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["manifest_path"] = (
            "records/legacy-rabi-001/manifest-dir"
        )
        source["accepted_record"]["acceptance_request"]["primary_data_path"] = (
            "records/legacy-rabi-001/manifest-dir/primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "must not overlap"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["acceptance_request"]["primary_data_path"] = (
            "records/legacy-rabi-001/primary-dir"
        )
        source["accepted_record"]["acceptance_request"]["manifest_path"] = (
            "records/legacy-rabi-001/primary-dir/record-manifest.json"
        )

        with self.assertRaisesRegex(ValueError, "must not overlap"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_accepted_record_materialization_must_match_flow_boundary(self) -> None:
        source = _load_input()
        source["accepted_record"]["acceptance_request"]["materialization"]["linked_context"] = (
            "copy_into_storage"
        )

        with self.assertRaisesRegex(ValueError, "materialization"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_primary_write_result_must_match_acceptance_request_path(self) -> None:
        source = _load_input()
        source["accepted_record"]["write_results"][0]["path"] = (
            "records/legacy-rabi-001/other-primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "write result path"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_primary_write_result_contract_is_validated(self) -> None:
        source = _load_input()
        source["accepted_record"]["write_results"] = []
        self.assertRejected(source, "primary data and manifest")

        source = _load_input()
        source["accepted_record"]["write_results"].append(
            copy.deepcopy(source["accepted_record"]["write_results"][0])
        )
        self.assertRejected(source, "duplicate kind")

        for field, value, pattern in (
            ("result", "skipped", "must be written"),
            ("digest", "not-a-digest", "digest"),
            ("bytes_written", 0, "bytes_written"),
            ("does_not_claim", "unexpected_claim_boundary", "does_not_claim"),
        ):
            with self.subTest(field=field):
                source = _load_input()
                source["accepted_record"]["write_results"][0][field] = value
                self.assertRejected(source, pattern)

        source = _load_input()
        source["accepted_record"]["write_results"] = [source["accepted_record"]["write_results"][0]]
        self.assertRejected(source, "primary data and manifest")

        source = _load_input()
        source["accepted_record"]["write_results"][1]["path"] = (
            "/Users/lab/private/record-manifest.json"
        )
        self.assertRejected(source, "write result path")

    def test_package_preview_metadata_must_match_accepted_record(self) -> None:
        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["declared_preview_metadata"][
            "data_shape"
        ]["axis_order"] = ["signal", "drive_frequency"]

        with self.assertRaisesRegex(ValueError, "axis order"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["accepted_record"]["preview"]["plot_candidates"][0]["source"] = (
            "records/other-record/primary.csv"
        )
        self.assertRejected(source, "accepted primary_data_path")

    def test_accepted_preview_authority_must_match_adapter_contract(self) -> None:
        source = _load_input()
        source["accepted_record"]["preview"]["metadata_authority"] = "untrusted"

        with self.assertRaisesRegex(ValueError, "metadata_authority"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_managed_request_and_package_identity_fields_are_validated(self) -> None:
        invalid_cases = (
            (("flow_request", "flow_id"), "/Users/lab/private/flow", "flow_id"),
            (("flow_request", "target"), "/Users/lab/private/qA", "target"),
            (
                ("flow_request", "source_observation_request_id"),
                "/Users/lab/private/observe",
                "source_observation_request_id",
            ),
            (
                ("accepted_record", "acceptance_request", "request_id"),
                "/Users/lab/private/accept",
                "request_id",
            ),
            (
                ("accepted_record", "preview", "shape_kind"),
                "/Users/lab/private/shape",
                "shape_kind",
            ),
            (
                ("handoff_package_manifest", "package_identity", "package_id"),
                "/Users/lab/private/package",
                "package_id",
            ),
            (
                (
                    "handoff_package_manifest",
                    "package_identity",
                    "source_export_summary_id",
                ),
                "/Users/lab/private/export",
                "source_export_summary_id",
            ),
            (
                ("handoff_package_manifest", "package_identity", "display_name"),
                {"text": "Legacy Rabi selected measurement handoff"},
                "display_name",
            ),
            (
                ("handoff_package_manifest", "package_identity", "created_by"),
                "user_export_tool",
                "created_by",
            ),
            (
                ("handoff_package_manifest", "package_identity", "display_path"),
                "HANDOFF_PACKAGE:/Users/lab/private/legacy-rabi-001",
                "display_path",
            ),
            (
                ("handoff_package_manifest", "package_identity", "local_path_redacted"),
                False,
                "local path",
            ),
        )
        for path, value, pattern in invalid_cases:
            with self.subTest(path=path):
                source = _load_input()
                target = source
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                if path == ("accepted_record", "preview", "shape_kind"):
                    source["handoff_package_manifest"]["selected_measurements"][0][
                        "declared_preview_metadata"
                    ]["data_shape"]["kind"] = value
                self.assertRejected(source, pattern)

    def test_package_source_export_summary_id_is_package_declared_metadata(self) -> None:
        source = _load_input()
        source["handoff_package_manifest"]["package_identity"]["source_export_summary_id"] = (
            "export-summary-explicit-package-preview"
        )

        summary = build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )

        self.assertEqual(
            summary["handoff_package_preview"]["package"]["source_export_summary_id"],
            "export-summary-explicit-package-preview",
        )

    def test_measurement_identity_fields_are_typed_contract_fields(self) -> None:
        source = _load_input()
        source["accepted_record"]["measurement_record"]["label"] = {
            "text": "Rabi calibration follow-up"
        }
        source["handoff_package_manifest"]["selected_measurements"][0]["label"] = {
            "text": "Rabi calibration follow-up"
        }
        self.assertRejected(source, "label")

        source = _load_input()
        source["accepted_record"]["measurement_record"]["experiment_type"] = {"name": "rabi"}
        source["handoff_package_manifest"]["selected_measurements"][0]["experiment_type"] = {
            "name": "rabi"
        }
        self.assertRejected(source, "experiment_type")

    def test_preview_columns_are_typed_projected_contract_fields(self) -> None:
        for side, field in (
            ("accepted_record", "role"),
            ("accepted_record", "label"),
            ("accepted_record", "unit"),
            ("handoff_package_manifest", "label"),
            ("handoff_package_manifest", "unit"),
        ):
            with self.subTest(side=side, field=field):
                source = _load_input()
                if side == "accepted_record":
                    source["accepted_record"]["preview"]["declared_roles"][0][field] = {
                        "value": "invalid"
                    }
                else:
                    source["handoff_package_manifest"]["selected_measurements"][0][
                        "declared_preview_metadata"
                    ]["declared_columns"][0][field] = {"value": "invalid"}
                self.assertRejected(source, field)

        source = _load_input()
        source["accepted_record"]["preview"]["declared_roles"][0]["debug_path"] = (
            "/Users/lab/private/accepted-column-debug"
        )
        source["handoff_package_manifest"]["selected_measurements"][0]["declared_preview_metadata"][
            "declared_columns"
        ][0]["debug_path"] = "/Users/lab/private/package-column-debug"

        summary = build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )

        accepted_column = summary["accepted_record_summary"]["preview"]["declared_roles"][0]
        packaged_column = summary["handoff_package_preview"]["selected_measurements"][0]["preview"][
            "declared_roles"
        ][0]
        self.assertEqual(set(accepted_column), PREVIEW_COLUMN_KEYS)
        self.assertEqual(set(packaged_column), PREVIEW_COLUMN_KEYS)

    def test_managed_source_identity_fields_are_validated(self) -> None:
        source = _load_input()
        source["accepted_record"]["source_identity"]["external_record_id"] = (
            "/Users/lab/private/legacy-record-001"
        )
        self.assertRejected(source, "external_record_id")

        source = _load_input()
        source["accepted_record"]["source_identity"]["external_root_label"] = "private/share"
        self.assertRejected(source, "external_root_label")

        source = _load_input()
        source["accepted_record"]["source_identity"]["external_root_label"] = "lab-share"
        self.assertRejected(source, "external_root_label")

    def test_managed_display_refs_must_use_redacted_displays(self) -> None:
        source = _load_input()
        source["flow_request"]["export_source_display"] = (
            "SCOPECAT_STORAGE:/Users/lab/private/records/legacy-rabi-001/primary.csv"
        )

        with self.assertRaisesRegex(ValueError, "export_source_display"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["flow_request"]["export_source_display"] = (
            "SCOPECAT_STORAGE:/redacted/records/other-record/primary.csv"
        )
        self.assertRejected(source, "export_source_display")

        source = _load_input()
        source["accepted_record"]["source_identity"]["local_path_redacted"] = False

        with self.assertRaisesRegex(ValueError, "local path"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_legacy_source_display_must_match_accepted_source_identity(self) -> None:
        source = _load_input()
        source["accepted_record"]["source_identity"]["original_path_display"] = (
            "LEGACY_SOURCE:/redacted/other-record"
        )

        self.assertRejected(source, "original_path_display")

    def test_linked_context_export_refs_must_exactly_match_accepted_context(self) -> None:
        source = _load_input()
        extra_ref = copy.deepcopy(source["linked_context_export_refs"][0])
        extra_ref["source_link_id"] = "unexpected-link"
        extra_ref["path"] = "context/unexpected-link.reference.json"
        source["linked_context_export_refs"].append(extra_ref)

        with self.assertRaisesRegex(ValueError, "unexpected linked context export ref"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["linked_context_export_refs"][0]["relation"] = "documents"

        with self.assertRaisesRegex(ValueError, "relation"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        source = _load_input()
        source["linked_context_export_refs"] = []
        self.assertRejected(source, "missing linked context export ref")

        source = _load_input()
        source["linked_context_export_refs"].append(
            copy.deepcopy(source["linked_context_export_refs"][0])
        )
        self.assertRejected(source, "duplicate linked context export ref")

        source = _load_input()
        source["linked_context_export_refs"][0]["include_status"] = "included_by_default"
        self.assertRejected(source, "include_status")

        source = _load_input()
        source["linked_context_export_refs"][0]["authority"] = "user_declared"
        self.assertRejected(source, "authority")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["authority"] = "user_declared"
        source["linked_context_export_refs"][0]["authority"] = "user_declared"
        self.assertRejected(source, "authority")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["role"] = "/Users/lab/private/role"
        source["linked_context_export_refs"][0]["relation"] = "/Users/lab/private/role"
        self.assertRejected(source, "role")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["link_id"] = "/Users/lab/private/link"
        source["linked_context_export_refs"][0]["source_link_id"] = "/Users/lab/private/link"
        source["handoff_package_manifest"]["linked_context"][0]["link_id"] = (
            "package-/Users/lab/private/link"
        )
        self.assertRejected(source, "link_id")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["kind"] = "/Users/lab/private/kind"
        source["handoff_package_manifest"]["linked_context"][0]["kind"] = "/Users/lab/private/kind"
        self.assertRejected(source, "kind")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["reference_state"] = (
            "adapter_declared_missing"
        )
        self.assertRejected(source, "adapter_declared_available")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["reason"] = "missing payload"
        self.assertRejected(source, "must not carry reason")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["reference"] = None
        self.assertRejected(source, "reference")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["reference"] = "   "
        self.assertRejected(source, "non-empty")

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["reference"] = "private/customer/params"
        summary = build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )
        self.assertEqual(
            summary["accepted_record_summary"]["linked_context"][0]["reference"],
            "private/customer/params",
        )

        source = _load_input()
        source["accepted_record"]["linked_context"][0]["label"] = {
            "text": "Run-local parameter snapshot"
        }
        source["handoff_package_manifest"]["linked_context"][0]["label"] = {
            "text": "Run-local parameter snapshot"
        }
        self.assertRejected(source, "label")

        source = _load_input()
        source["handoff_package_manifest"]["linked_context"][0]["reason"] = {
            "text": "The accepted legacy import preserved this linked context as a reference-only fact."
        }
        self.assertRejected(source, "reason")

    def test_package_primary_data_semantics_must_match_selected_export_contract(self) -> None:
        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["primary_data"]["kind"] = (
            "artifact"
        )
        self.assertRejected(source, "primary_data kind")

        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["primary_data"][
            "relation"
        ] = "derived_artifact"
        self.assertRejected(source, "primary_data relation")

        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["default_bundle"] = []
        self.assertRejected(source, "default_bundle")

        for field, value in (
            ("label", "Other primary data"),
            ("include_status", "visible_excluded"),
            ("authority", "user_declared"),
            ("format", "json"),
            ("package_state", "missing_from_package"),
            ("reason", "not included"),
        ):
            source = _load_input()
            source["handoff_package_manifest"]["selected_measurements"][0]["primary_data"][
                field
            ] = value
            self.assertRejected(source, f"primary_data {field}")

        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["primary_data"][
            "package_path"
        ] = "/Users/lab/private/primary.csv"
        self.assertRejected(source, "primary_data")

        for package_path in (
            "context/legacy-rabi-001-primary.csv",
            "measurements/other-record/primary.csv",
        ):
            source = _load_input()
            package_record = source["handoff_package_manifest"]["selected_measurements"][0]
            package_record["primary_data"]["package_path"] = package_path
            package_record["default_bundle"][0]["package_path"] = package_path
            package_record["declared_preview_metadata"]["plot_candidates"][0]["source"] = (
                package_path
            )
            self.assertRejected(source, "primary_data")

        for field, value in (
            ("kind", "artifact"),
            ("label", "Other primary data"),
            ("include_status", "visible_excluded"),
            ("relation", "derived_artifact"),
            ("authority", "user_declared"),
            ("package_state", "missing_from_package"),
            ("reason", "not included"),
        ):
            source = _load_input()
            source["handoff_package_manifest"]["selected_measurements"][0]["default_bundle"][0][
                field
            ] = value
            self.assertRejected(source, f"default bundle primary_data {field}")

        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["default_bundle"][0][
            "item_id"
        ] = "wrong-primary"
        self.assertRejected(source, "item_id")

        source = _load_input()
        source["handoff_package_manifest"]["selected_measurements"][0]["default_bundle"][0][
            "package_path"
        ] = "measurements/legacy-rabi-001/other.csv"
        self.assertRejected(source, "primary path")

    def test_package_linked_context_must_match_accepted_reference_context(self) -> None:
        source = _load_input()
        source["handoff_package_manifest"]["linked_context"][0]["package_state"] = "packaged"
        source["handoff_package_manifest"]["linked_context"][0]["package_path"] = (
            "context/legacy-001-parameter-snapshot.json"
        )
        source["handoff_package_manifest"]["linked_context"][0]["reason"] = None

        with self.assertRaisesRegex(ValueError, "linked context"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

        for linked_ids in (
            ["other-record"],
            ["legacy-rabi-001", "other-record"],
            [],
        ):
            with self.subTest(linked_ids=linked_ids):
                source = _load_input()
                source["handoff_package_manifest"]["linked_context"][0][
                    "linked_measurement_record_ids"
                ] = linked_ids
                with self.assertRaisesRegex(ValueError, "linked context"):
                    build_measurement_record_handoff_flow_summary(
                        source,
                        storage_root=STORAGE_ROOT,
                    )

        source = _load_input()
        source["handoff_package_manifest"]["linked_context"][0]["link_id"] = (
            "unrelated-package-link"
        )

        with self.assertRaisesRegex(ValueError, "linked context"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_flow_rejects_positive_package_writing_claim(self) -> None:
        source = _load_input()
        source["flow_policy"]["package_writing"] = "performed"

        with self.assertRaisesRegex(ValueError, "package_writing"):
            build_measurement_record_handoff_flow_summary(
                source,
                storage_root=STORAGE_ROOT,
            )

    def test_input_is_not_mutated(self) -> None:
        source = _load_input()
        original = copy.deepcopy(source)

        build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )

        self.assertEqual(source, original)

    def test_review_summary_is_repository_safe_projection(self) -> None:
        source = _load_input()
        source["accepted_record"]["debug_note"] = "UNPROJECTED_ACCEPTED_DEBUG"
        source["accepted_record"]["write_results"][0]["debug_note"] = "UNPROJECTED_WRITE_DEBUG"
        source["accepted_record"]["write_results"][1]["debug_note"] = "UNPROJECTED_MANIFEST_DEBUG"
        source["accepted_record"]["preview"]["declared_roles"][0]["debug_note"] = (
            "UNPROJECTED_COLUMN_DEBUG"
        )
        source["handoff_package_manifest"]["selected_measurements"][0]["declared_preview_metadata"][
            "declared_columns"
        ][0]["debug_note"] = "UNPROJECTED_PACKAGE_COLUMN_DEBUG"
        source["handoff_package_manifest"]["selected_measurements"][0]["primary_data"][
            "debug_note"
        ] = "UNPROJECTED_PACKAGE_DEBUG"
        source["handoff_package_manifest"]["selected_measurements"][0]["primary_data"][
            "item_id"
        ] = "unexpected-primary-item"
        source["accepted_record"]["linked_context"][0]["debug_note"] = (
            "UNPROJECTED_ACCEPTED_CONTEXT_DEBUG"
        )
        source["linked_context_export_refs"][0]["debug_note"] = (
            "UNPROJECTED_CONTEXT_EXPORT_REF_DEBUG"
        )
        source["handoff_package_manifest"]["linked_context"][0]["debug_note"] = (
            "UNPROJECTED_PACKAGE_CONTEXT_DEBUG"
        )
        injected_values = {
            value
            for value in _walk_json(source)
            if isinstance(value, str) and value.startswith("UNPROJECTED_")
        }
        summary = build_measurement_record_handoff_flow_summary(
            source,
            storage_root=STORAGE_ROOT,
        )

        self.assertNotIn("accepted_record", summary)
        self.assertIn("accepted_record_summary", summary)
        self.assertEqual(summary["flow"]["summary_posture"], "review_summary")
        self.assertNotIn(
            source["legacy_source_location"]["local_path"],
            json.dumps(summary, sort_keys=True),
        )
        summary_values = set(_walk_json(summary))
        self.assertNotIn("debug_note", summary_values)
        self.assertTrue(injected_values.isdisjoint(summary_values))
        for result in summary["accepted_record_summary"]["write_results"]:
            self.assertEqual(set(result), WRITE_RESULT_KEYS)

        for item in summary["accepted_record_summary"]["linked_context"]:
            self.assertEqual(set(item), ACCEPTED_LINKED_CONTEXT_KEYS)
        for item in summary["selected_measurement_export"]["linked_context"]:
            self.assertEqual(set(item), EXPORT_LINKED_CONTEXT_KEYS)
        linked_context_contents = [
            item
            for item in summary["handoff_package_preview"]["package_contents"]
            if item["owner_type"] == "linked_context"
        ]
        self.assertEqual(len(linked_context_contents), 1)
        self.assertEqual(set(linked_context_contents[0]), PACKAGE_CONTENT_KEYS)
        self.assertEqual(
            linked_context_contents[0]["owner_id"],
            "package-legacy-001-parameter-snapshot",
        )
        linked_context_findings = [
            finding
            for finding in summary["handoff_package_preview"]["preview_findings"]
            if finding["subject_type"] == "linked_context"
        ]
        self.assertEqual(len(linked_context_findings), 1)
        self.assertEqual(
            linked_context_findings[0]["measurement_record_id"],
            "legacy-rabi-001",
        )

        accepted_preview = summary["accepted_record_summary"]["preview"]
        observed_preview = summary["source_observation"]["preview"]
        exported_preview = summary["selected_measurement_export"]["measurements"][0]["preview"]
        packaged_record = summary["handoff_package_preview"]["selected_measurements"][0]
        packaged_preview = packaged_record["preview"]
        for column in accepted_preview["declared_roles"]:
            self.assertEqual(set(column), PREVIEW_COLUMN_KEYS)
        for column in observed_preview["declared_roles"]:
            self.assertEqual(set(column), PREVIEW_COLUMN_KEYS)
        for column in exported_preview["declared_roles"]:
            self.assertEqual(set(column), PREVIEW_COLUMN_KEYS)
        for column in packaged_preview["declared_roles"]:
            self.assertEqual(set(column), PREVIEW_COLUMN_KEYS)
        self.assertEqual(set(packaged_record["primary_data"]), PACKAGE_PRIMARY_DATA_KEYS)
        self.assertEqual(summary["accepted_record_summary"]["preview"]["warnings"], [])

    def test_preview_ready_accepted_record_does_not_passthrough_warning_payloads(self) -> None:
        source = _load_input()
        source["accepted_record"]["preview"]["warnings"] = [
            {
                "code": "debug_warning",
                "debug_note": "UNPROJECTED_WARNING_DEBUG",
            }
        ]

        self.assertRejected(source, "warning payloads")


if __name__ == "__main__":
    unittest.main()

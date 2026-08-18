from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from scopecat_testkit.records import assert_model_round_trip

from scopecat.automation import (
    CalibrationCohort,
    CalibrationCohortCreateCommand,
    CalibrationCohortCreateReceipt,
    CalibrationCohortGetQuery,
    CalibrationCohortGetReceipt,
    CalibrationCohortListQuery,
    CalibrationCohortMember,
    CalibrationCohortMemberListQuery,
    CalibrationCohortMemberPage,
    CalibrationCohortMemberSpec,
    CalibrationCohortPage,
    CalibrationCohortSpec,
    CalibrationCohortSummary,
    CalibrationConfigSourceRef,
    CalibrationDefinitionRef,
    CalibrationMissingSuccessDueReason,
    CalibrationStatus,
    CalibrationStatusQuery,
    CalibrationStatusReceipt,
    CalibrationStatusSnapshot,
    CalibrationTargetRef,
    ProcedureDefinitionRef,
    calibration_cohort_member_request_key,
    calibration_cohort_spec_hash,
    calibration_freshness_fingerprint,
    calibration_key,
)
from scopecat.records.run import ConfigRegistryRunConfigSource

_HASH_1 = "sha256:" + "1" * 64
_HASH_2 = "sha256:" + "2" * 64
_HASH_3 = "sha256:" + "3" * 64
_EVALUATED = datetime(2026, 8, 18, 8, tzinfo=UTC)
_CREATED = _EVALUATED + timedelta(seconds=1)


def _fixture() -> tuple[
    CalibrationCohort,
    CalibrationCohortMember,
    CalibrationStatusSnapshot,
]:
    definition = CalibrationDefinitionRef(
        id="drag",
        version="2",
        fingerprint=_HASH_1,
    )
    target = CalibrationTargetRef(kind="qubit", id="q0")
    procedure = ProcedureDefinitionRef(
        id="calibrate-drag",
        version="4",
        fingerprint=_HASH_2,
    )
    key = calibration_key(definition.id, target)
    status = CalibrationStatus(calibration_key=key)
    freshness = calibration_freshness_fingerprint(
        definition=definition,
        target=target,
        procedure=procedure,
        input_fingerprint=_HASH_3,
        dependencies=(),
    )
    member_spec = CalibrationCohortMemberSpec(
        member_id="member-q0",
        calibration_key=key,
        definition=definition,
        target=target,
        procedure=procedure,
        intent={"target_id": "q0"},
        input_fingerprint=_HASH_3,
        dependencies=(),
        freshness_fingerprint=freshness,
        due_reasons=(CalibrationMissingSuccessDueReason(),),
    )
    spec = CalibrationCohortSpec(
        planner=definition,
        config_source=CalibrationConfigSourceRef.from_run_config_source(
            ConfigRegistryRunConfigSource(
                selector="active",
                entry_id="config-17",
                config_ref="configs/17",
                content_hash=_HASH_3,
                registry_generation=23,
            )
        ),
        fanout_scope="chip-alpha",
        max_in_flight=2,
        observed_fanout_active_count=0,
        evaluated_at=_EVALUATED,
        observations=(status,),
        members=(member_spec,),
    )
    cohort = CalibrationCohort(
        cohort_id="cohort-18",
        spec=spec,
        spec_hash=calibration_cohort_spec_hash(spec),
        created_at=_CREATED,
    )
    member = CalibrationCohortMember(
        cohort_id=cohort.cohort_id,
        index=0,
        spec=member_spec,
        procedure_run_id="procedure-18-q0",
        request_key=calibration_cohort_member_request_key(
            cohort.cohort_id,
            member_spec,
        ),
        admitted_at=_CREATED,
    )
    snapshot = CalibrationStatusSnapshot(
        observed_at=_EVALUATED,
        fanout_scope=spec.fanout_scope,
        fanout_active_count=spec.observed_fanout_active_count,
        statuses=spec.observations,
    )
    return cohort, member, snapshot


def test_status_query_and_receipt_are_bounded_and_round_trip() -> None:
    cohort, _, snapshot = _fixture()
    key = cohort.spec.members[0].calibration_key
    query = CalibrationStatusQuery(
        calibration_keys=(key,),
        fanout_scope="chip-alpha",
    )
    receipt = CalibrationStatusReceipt(snapshot=snapshot)

    assert assert_model_round_trip(query) == query
    assert assert_model_round_trip(receipt) == receipt
    with pytest.raises(ValidationError, match="unique"):
        CalibrationStatusQuery(
            calibration_keys=(key, key),
            fanout_scope="chip-alpha",
        )
    with pytest.raises(ValidationError):
        CalibrationStatusQuery(
            calibration_keys=tuple(str(index) for index in range(201)),
            fanout_scope="chip-alpha",
        )


def test_create_command_exposes_hash_and_receipt_requires_exact_members() -> None:
    cohort, member, _ = _fixture()
    command = CalibrationCohortCreateCommand(
        cohort_id=cohort.cohort_id,
        spec=cohort.spec,
    )
    receipt = CalibrationCohortCreateReceipt(
        cohort=cohort,
        members=(member,),
    )

    assert command.spec_hash == cohort.spec_hash
    assert assert_model_round_trip(command) == command
    assert assert_model_round_trip(receipt) == receipt

    wrong_member = CalibrationCohortMember(
        cohort_id="other",
        index=member.index,
        spec=member.spec,
        procedure_run_id=member.procedure_run_id,
        request_key=calibration_cohort_member_request_key("other", member.spec),
        admitted_at=member.admitted_at,
    )
    with pytest.raises(ValidationError, match="match its cohort"):
        CalibrationCohortCreateReceipt(
            cohort=cohort,
            members=(wrong_member,),
        )


def test_get_list_and_member_pages_use_compact_exact_projections() -> None:
    cohort, member, _ = _fixture()
    summary = CalibrationCohortSummary.from_cohort(cohort)
    get_query = CalibrationCohortGetQuery(cohort_id=cohort.cohort_id)
    get_receipt = CalibrationCohortGetReceipt(cohort=cohort)
    list_query = CalibrationCohortListQuery(
        limit=20,
        fanout_scope=cohort.spec.fanout_scope,
    )
    page = CalibrationCohortPage(items=(summary,), next_cursor=7)
    member_query = CalibrationCohortMemberListQuery(
        cohort_id=cohort.cohort_id,
        limit=20,
    )
    member_page = CalibrationCohortMemberPage(
        cohort_id=cohort.cohort_id,
        items=(member,),
    )

    assert summary.member_count == 1
    assert assert_model_round_trip(get_query) == get_query
    assert assert_model_round_trip(get_receipt) == get_receipt
    assert assert_model_round_trip(list_query) == list_query
    assert assert_model_round_trip(page) == page
    assert assert_model_round_trip(member_query) == member_query
    assert assert_model_round_trip(member_page) == member_page

    with pytest.raises(ValidationError, match="match its cohort"):
        CalibrationCohortMemberPage(
            cohort_id="other",
            items=(member,),
        )


def test_wire_models_forbid_unknown_fields_and_are_frozen() -> None:
    cohort, _, _ = _fixture()
    command = CalibrationCohortCreateCommand(
        cohort_id=cohort.cohort_id,
        spec=cohort.spec,
    )

    with pytest.raises(ValidationError):
        CalibrationCohortCreateCommand.model_validate(
            {
                **command.model_dump(),
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        command.cohort_id = "other"

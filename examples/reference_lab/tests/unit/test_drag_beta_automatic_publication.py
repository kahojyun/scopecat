from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import cast

import pytest
from scopecat.api.calibration_finalizer import (
    CalibrationPublicationCandidate,
    CalibrationPublicationPlanningContext,
)
from scopecat.api.calibration_publication import CalibrationCohortPublicationPlan
from scopecat.api.lab import LabClient
from scopecat.automation.calibration_wire import CalibrationCohortMemberPage
from scopecat.automation.calibrations import CalibrationCohort
from scopecat.daemon.wire import CalibrationCohortMergeRevisionSource

from reference_lab.application import create_application
from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.workflows import drag_beta_automatic_publication
from reference_lab.workflows.drag_beta_automatic_publication import (
    DRAG_BETA_PUBLICATION_POLICY_FINGERPRINT,
    DRAG_BETA_PUBLICATION_POLICY_ID,
    DRAG_BETA_PUBLICATION_POLICY_REF,
    DRAG_BETA_PUBLICATION_POLICY_REGISTRY,
    DRAG_BETA_PUBLICATION_POLICY_VERSION,
    prepare_drag_beta_automatic_publication,
)
from reference_lab.workflows.drag_beta_freshness import (
    DRAG_BETA_CALIBRATION_VERSION,
    drag_beta_freshness_calibration,
)
from reference_lab.workflows.drag_beta_publication import (
    DRAG_BETA_COMPOSITION_POLICY_REF,
    DRAG_BETA_PUBLICATION_ACTOR,
    DRAG_BETA_PUBLICATION_NOTE,
    DragBetaCohortPublication,
)


def test_drag_beta_automatic_policy_binds_its_exact_contract() -> None:
    policy = prepare_drag_beta_automatic_publication

    assert policy.id == DRAG_BETA_PUBLICATION_POLICY_ID
    assert policy.version == DRAG_BETA_PUBLICATION_POLICY_VERSION
    assert policy.fingerprint == DRAG_BETA_PUBLICATION_POLICY_FINGERPRINT
    assert policy.ref == DRAG_BETA_PUBLICATION_POLICY_REF
    assert policy.calibration == drag_beta_freshness_calibration.ref
    assert policy.calibration.version == DRAG_BETA_CALIBRATION_VERSION == "2"
    assert policy.composition_policy == DRAG_BETA_COMPOSITION_POLICY_REF
    assert policy.actor == DRAG_BETA_PUBLICATION_ACTOR
    assert policy.note == DRAG_BETA_PUBLICATION_NOTE
    assert DRAG_BETA_PUBLICATION_POLICY_REGISTRY.refs == (policy.ref,)
    assert DRAG_BETA_PUBLICATION_POLICY_REGISTRY.resolve(policy.ref) is policy
    assert (
        DRAG_BETA_PUBLICATION_POLICY_REGISTRY.for_calibration(policy.calibration)
        is policy
    )


def test_drag_beta_automatic_policy_fingerprint_covers_every_boundary() -> None:
    policy = prepare_drag_beta_automatic_publication
    actor_changed = replace(policy, actor="another-finalizer")
    note_changed = replace(policy, note="another publication note")
    callback_changed = replace(policy, _prepare=_changed_prepare)
    composition_changed = replace(
        policy,
        composition_policy=policy.composition_policy.model_copy(
            update={"version": "changed"}
        ),
    )

    assert (
        len(
            {
                policy.fingerprint,
                actor_changed.fingerprint,
                note_changed.fingerprint,
                callback_changed.fingerprint,
                composition_changed.fingerprint,
            }
        )
        == 5
    )


def test_drag_beta_automatic_adapter_reuses_phase7_plan_without_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cohort = cast(
        "CalibrationCohort",
        cast("object", SimpleNamespace(cohort_id="cohort-exact")),
    )
    member_page = cast(
        "CalibrationCohortMemberPage",
        cast("object", SimpleNamespace(items=(object(),))),
    )
    candidate = cast(
        "CalibrationPublicationCandidate",
        cast(
            "object",
            SimpleNamespace(
                cohort=cohort,
                member_page=member_page,
                finalization=SimpleNamespace(revision=7),
            ),
        ),
    )
    plan = cast("CalibrationCohortPublicationPlan", object())
    planning = _PlanningContext(plan)
    context = cast(
        "CalibrationPublicationPlanningContext",
        cast("object", planning),
    )
    source = cast("CalibrationCohortMergeRevisionSource", object())

    def fake_prepare(
        lab: LabClient,
        cohort_id: str,
        *,
        actor: str,
        note: str,
    ) -> DragBetaCohortPublication:
        assert cohort_id == cohort.cohort_id
        assert actor == DRAG_BETA_PUBLICATION_ACTOR
        assert note == DRAG_BETA_PUBLICATION_NOTE
        assert lab.calibrations.get(cohort_id) is cohort
        assert lab.calibrations.members(cohort_id, limit=2) is member_page
        assert lab.calibrations.publication_plan(source, actor=actor, note=note) is plan
        assert not hasattr(lab.calibrations, "publish")
        assert not hasattr(lab.config, "publish")
        return cast(
            "DragBetaCohortPublication",
            cast("object", SimpleNamespace(plan=plan)),
        )

    monkeypatch.setattr(
        drag_beta_automatic_publication,
        "prepare_drag_beta_cohort_publication",
        fake_prepare,
    )

    assert (
        prepare_drag_beta_automatic_publication.__wrapped__(context, candidate) is plan
    )
    assert planning.finalization_revisions == [7]


def test_reference_application_registers_drag_beta_automatic_publication() -> None:
    application = create_application(EXAMPLE_ROOT)

    assert application.calibration_publications is (
        DRAG_BETA_PUBLICATION_POLICY_REGISTRY
    )
    assert (
        application.calibration_publications.for_calibration(
            drag_beta_freshness_calibration.ref
        )
        is prepare_drag_beta_automatic_publication
    )


def _changed_prepare(
    context: CalibrationPublicationPlanningContext,
    candidate: CalibrationPublicationCandidate,
) -> CalibrationCohortPublicationPlan:
    return prepare_drag_beta_automatic_publication.__wrapped__(context, candidate)


@dataclass(slots=True)
class _PlanningContext:
    plan: CalibrationCohortPublicationPlan
    finalization_revisions: list[int] = field(default_factory=list)

    def publication_plan(
        self,
        _source: CalibrationCohortMergeRevisionSource,
        *,
        actor: str,
        note: str = "",
        expected_calibration_finalization_revision: int,
    ) -> CalibrationCohortPublicationPlan:
        assert actor == DRAG_BETA_PUBLICATION_ACTOR
        assert note == DRAG_BETA_PUBLICATION_NOTE
        self.finalization_revisions.append(expected_calibration_finalization_revision)
        return self.plan

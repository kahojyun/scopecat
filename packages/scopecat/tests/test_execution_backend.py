from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pytest

from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    link_program,
)
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    TypedProgram,
    product_output,
    record_product,
    set_state_field,
)
from scopecat._point_domain_algebra import point_rows
from scopecat._relation_verification import RelationTypeBindings, RowType
from scopecat._relations import lit, literal_rows, point_col
from scopecat._workflows.preview import build_execution_plan_preview
from scopecat.domain_execution import (
    DomainExecutionCapabilities,
    DomainExecutionRequest,
    PreparedDomainExecution,
    erase_prepared_domain_execution,
)
from scopecat.domain_invocation import (
    AdapterEntryResults,
    ClosedDomainInvocation,
    ClosedDomainOutputValues,
    DomainInvocationIntent,
    EntryPointBinding,
    ResultUseBinding,
    close_domain_invocation,
    seal_domain_result_mapping,
    select_domain_measurement_outputs,
)
from scopecat.domain_runtime import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainReconcileReceipt,
    DomainSubmissionId,
    DomainSubmitReceipt,
)
from scopecat.errors import CheckFailed
from scopecat.execution_backend import ExecutionBackend
from scopecat.execution_coverage import (
    ExecutionResourceClaim,
    ExecutionTask,
)
from scopecat.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from scopecat.measurement_projection import (
    bind_measurement_projection,
    select_measurement_projection,
)
from scopecat.measurement_values import (
    ProductValueFragmentDef,
    bind_domain_output_fragment,
    select_measurement_value_assembly,
)
from scopecat.models.parameter import Quantity
from scopecat.problems import ProblemPhase
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, String, Table, TableColumn
from tests.support.authoring import load_config
from tests.support.relation_plans import scalar_value_expr, table_value_expr
from tests.support.signal_instruments import TestSignalInstrumentProvider


class _EffectProbeRuntime:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.fetch_calls = 0
        self.reconcile_calls = 0

    def submit(
        self,
        submission_id: DomainSubmissionId,
        invocation: ClosedDomainInvocation[str, str, dict[str, str]],
    ) -> DomainSubmitReceipt:
        _ = submission_id, invocation
        self.submit_calls += 1
        raise AssertionError("planning must not submit a domain invocation")

    def fetch(
        self,
        submission_id: DomainSubmissionId,
        intent: DomainInvocationIntent,
        job_id: str,
    ) -> DomainFetchCandidate[dict[str, str]]:
        _ = submission_id, intent, job_id
        self.fetch_calls += 1
        raise AssertionError("planning must not fetch a domain invocation")

    def reconcile(
        self,
        submission_id: DomainSubmissionId,
        intent: DomainInvocationIntent,
    ) -> DomainReconcileReceipt:
        _ = submission_id, intent
        self.reconcile_calls += 1
        raise AssertionError("planning must not reconcile a domain invocation")


@dataclass
class _DomainAdapter:
    adapter_id: str
    product_indices: tuple[int, ...] = (0,)
    claimed_tasks: tuple[ExecutionTask, ...] = ()
    resource_claims: tuple[ExecutionResourceClaim, ...] = ()
    max_points_per_batch: int = 100
    runtime: _EffectProbeRuntime = field(default_factory=_EffectProbeRuntime)
    capabilities_calls: int = 0
    prepare_calls: int = 0

    def capabilities(
        self,
        linked_points: MaterializedLinkedPoints,
    ) -> DomainExecutionCapabilities:
        self.capabilities_calls += 1
        selected_use_ids = tuple(
            linked_points.linked_plan.product_uses[index].id
            for index in self.product_indices
        )
        return DomainExecutionCapabilities(
            product_use_ids=selected_use_ids,
            domain_product_use_ids=selected_use_ids,
            claimed_tasks=self.claimed_tasks,
            max_points_per_batch=self.max_points_per_batch,
        )

    def prepare(self, request: DomainExecutionRequest) -> PreparedDomainExecution:
        self.prepare_calls += 1
        linked_points = request.batch
        selected_uses = tuple(
            linked_points.linked_plan.product_uses[index]
            for index in self.product_indices
        )
        selected_use_ids = tuple(use.id for use in selected_uses)
        points = linked_points.point_domain.points
        entries = tuple(
            AdapterEntryResults(
                f"{self.adapter_id}.entry.{point.logical_ordinal}",
                tuple(
                    f"{self.adapter_id}.result.{point.logical_ordinal}.{use_index}"
                    for use_index in range(len(selected_uses))
                ),
            )
            for point in points
        )
        mapping = seal_domain_result_mapping(
            linked_points,
            selected_use_ids,
            entries,
            tuple(
                EntryPointBinding(entry.entry_address, point.logical_id)
                for entry, point in zip(entries, points, strict=True)
            ),
            tuple(
                ResultUseBinding(
                    entry.entry_address,
                    result_address,
                    selected_uses[use_index].id,
                )
                for entry in entries
                for use_index, result_address in enumerate(entry.result_addresses)
            ),
        )
        domain_outputs = select_domain_measurement_outputs(mapping)
        fragment_id = f"{self.adapter_id}.source"
        assembly = select_measurement_value_assembly(
            linked_points,
            required_product_use_ids=selected_use_ids,
            fragment_defs=(ProductValueFragmentDef(fragment_id, selected_use_ids),),
        )
        source_fragment = bind_domain_output_fragment(
            assembly,
            fragment_id,
            domain_outputs,
        )
        selected_use_set = set(selected_use_ids)
        record_ids = tuple(
            record.id
            for record in linked_points.linked_plan.record_uses
            if record.product_use_id in selected_use_set
        )
        projection = bind_measurement_projection(
            select_measurement_projection(
                linked_points,
                record_ids=record_ids,
            ),
            assembly,
        )
        invocation = close_domain_invocation(
            mapping,
            invocation_id=(
                f"{self.adapter_id}.invocation.batch-{request.batch_ordinal}"
            ),
            target_id=f"{self.adapter_id}.target",
            compiler_id=f"{self.adapter_id}.compiler",
            capability_fingerprint=f"{self.adapter_id}.capabilities",
            artifact_id=f"{self.adapter_id}.artifact.batch-{request.batch_ordinal}",
            artifact_fingerprint=f"{self.adapter_id}.artifact-fingerprint",
            adapter_intent={
                "adapter_id": self.adapter_id,
                "batch_ordinal": str(request.batch_ordinal),
            },
            payload={
                "adapter_id": self.adapter_id,
                "batch_ordinal": str(request.batch_ordinal),
            },
        )
        return erase_prepared_domain_execution(
            adapter_id=self.adapter_id,
            semantic_operation_id=f"{self.adapter_id}.execute",
            linked_points=linked_points,
            invocation=invocation,
            runtime=self.runtime,
            realize=_reject_realization,
            source_fragment=source_fragment,
            projection=projection,
            claimed_tasks=self.claimed_tasks,
            resource_claims=self.resource_claims,
        )


@dataclass
class _TrackingProvider:
    delegate: TestSignalInstrumentProvider = field(
        default_factory=TestSignalInstrumentProvider
    )
    describe_calls: int = 0
    provide_calls: int = 0

    @property
    def provider_id(self) -> str:
        return self.delegate.provider_id

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        self.describe_calls += 1
        return self.delegate.describe(context)

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        self.provide_calls += 1
        raise AssertionError("planning must not request effect-capable drivers")


def _reject_realization(
    _fetched: CorrelatedDomainFetch[dict[str, str]],
) -> ClosedDomainOutputValues[str, str]:
    raise AssertionError("planning must not realize domain results")


def _linked_program(
    *,
    product_count: int = 1,
    state_mode: Literal["none", "constant", "varying"] = "none",
    point_count: Literal[0, 2] = 2,
) -> LinkedPlan:
    point_type = Table(
        columns=(
            TableColumn(
                "frequency",
                Scalar(QuantityType(unit="GHz")),
            ),
        ),
        min_rows=point_count,
        max_rows=point_count,
    )
    points = PointDomain(
        root=point_rows(
            table_value_expr(
                literal_rows(
                    (
                        {"frequency": Quantity(value=4.9, unit="GHz")},
                        {"frequency": Quantity(value=5.1, unit="GHz")},
                    )
                    if point_count
                    else ()
                ),
                expected_type=point_type,
            )
        )
    )
    products = tuple(
        product_output(f"signal-{index}", unit="ratio")
        for index in range(product_count)
    )
    selections = tuple(
        record_product(product, record_id=f"record-{index}")
        for index, product in enumerate(products)
    )
    bindings = RelationTypeBindings(point_row=RowType.from_table(point_type))
    state_value = {
        "none": None,
        "constant": scalar_value_expr(
            lit(Quantity(value=5.0, unit="GHz")),
            expected_type=Scalar(QuantityType(unit="GHz")),
        ),
        "varying": scalar_value_expr(
            point_col("frequency"),
            bindings=bindings,
            expected_type=Scalar(QuantityType(unit="GHz")),
        ),
    }[state_mode]
    state = (
        (
            set_state_field(
                scalar_value_expr(
                    lit("source-0"),
                    expected_type=Scalar(String()),
                ),
                capability_id="set_frequency",
                field_path="frequency",
                value=state_value,
            ),
        )
        if state_value is not None
        else ()
    )
    program = TypedProgram(
        id="unified-backend-contract",
        kind="compiler_test",
        point_domain=points,
        state=state,
        product_defs=products,
        product_uses=tuple(use for use, _record in selections),
        record_uses=tuple(record for _use, record in selections),
    )
    return link_program(
        program,
        validate_config_environment(load_config()),
    )


def _problem_codes(error: CheckFailed) -> set[str]:
    return {problem.code for problem in error.problems}


def _assert_no_domain_effects(*adapters: _DomainAdapter) -> None:
    assert all(adapter.runtime.submit_calls == 0 for adapter in adapters)
    assert all(adapter.runtime.fetch_calls == 0 for adapter in adapters)
    assert all(adapter.runtime.reconcile_calls == 0 for adapter in adapters)


def test_unified_planning_rejects_missing_task_claim_before_effects() -> None:
    linked = _linked_program(state_mode="varying")
    adapter = _DomainAdapter("tests.missing-claim")

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(domain_adapters=(adapter,)).prepare(
            linked,
            config=load_config(),
        )

    assert _problem_codes(captured.value) == {"execution_task_claim_missing"}
    assert captured.value.problems[0].details == {
        "task_kind": "state",
        "task_id": "0",
    }
    assert all(
        problem.phase is ProblemPhase.PLANNING for problem in captured.value.problems
    )
    assert adapter.capabilities_calls == 1
    assert adapter.prepare_calls == 0
    _assert_no_domain_effects(adapter)


def test_unified_planning_rejects_foreign_task_claim_before_effects() -> None:
    linked = _linked_program()
    adapter = _DomainAdapter(
        "tests.foreign-claim",
        claimed_tasks=(ExecutionTask("compute", "foreign-compute"),),
    )

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(domain_adapters=(adapter,)).prepare(
            linked,
            config=load_config(),
        )

    assert _problem_codes(captured.value) == {"execution_task_claim_foreign"}
    assert adapter.capabilities_calls == 1
    assert adapter.prepare_calls == 0
    _assert_no_domain_effects(adapter)


def test_unified_planning_rejects_overlapping_task_claim_before_effects() -> None:
    linked = _linked_program()
    first = _DomainAdapter("tests.overlap.first")
    second = _DomainAdapter("tests.overlap.second")
    backend = ExecutionBackend(
        domain_adapters=(first, second),
    )

    with pytest.raises(CheckFailed) as captured:
        backend.prepare(linked, config=load_config())

    assert _problem_codes(captured.value) == {"execution_task_claim_overlap"}
    assert first.capabilities_calls == 1
    assert second.capabilities_calls == 1
    assert first.prepare_calls == 0
    assert second.prepare_calls == 0
    _assert_no_domain_effects(first, second)


def test_unified_planning_rejects_overlapping_resources_before_effects() -> None:
    linked = _linked_program(product_count=2)
    shared = (ExecutionResourceClaim("instrument", "shared-instrument"),)
    first = _DomainAdapter(
        "tests.resource.first",
        product_indices=(0,),
        resource_claims=shared,
    )
    second = _DomainAdapter(
        "tests.resource.second",
        product_indices=(1,),
        resource_claims=shared,
    )
    backend = ExecutionBackend(
        domain_adapters=(first, second),
    )

    with pytest.raises(CheckFailed) as captured:
        backend.prepare(linked, config=load_config())

    assert _problem_codes(captured.value) == {"execution_resource_claim_overlap"}
    assert first.capabilities_calls == 1
    assert second.capabilities_calls == 1
    assert first.prepare_calls == 1
    assert second.prepare_calls == 1
    _assert_no_domain_effects(first, second)


def test_varying_local_state_splits_automatic_domain_batches() -> None:
    linked = _linked_program(state_mode="varying")
    adapter = _DomainAdapter("tests.fused-domain")
    provider = _TrackingProvider()
    backend = ExecutionBackend(
        provider=provider,
        domain_adapters=(adapter,),
    )

    plan = backend.prepare(linked, config=load_config())

    assert tuple(segment.point_indices for segment in plan.segments) == ((0,), (1,))
    assert tuple(job.point_indices for job in plan.domain_jobs) == ((0,), (1,))
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert adapter.capabilities_calls == 1
    assert adapter.prepare_calls == 2
    _assert_no_domain_effects(adapter)


def test_constant_local_state_is_automatically_fused() -> None:
    linked = _linked_program(state_mode="constant")
    adapter = _DomainAdapter("tests.constant-peripheral")
    provider = _TrackingProvider()
    backend = ExecutionBackend(
        provider=provider,
        domain_adapters=(adapter,),
    )

    plan = backend.prepare(linked, config=load_config())

    assert tuple(unit.id for unit in plan.units) == (
        "point-instrument",
        "domain-program-0-tests.constant-peripheral",
    )
    assert tuple(segment.point_indices for segment in plan.segments) == ((0, 1),)
    assert tuple(job.point_indices for job in plan.domain_jobs) == ((0, 1),)
    assert plan.point_unit is not None
    assert plan.point_unit.product_use_ids == ()
    assert len(plan.domain_units) == 1
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert adapter.capabilities_calls == 1
    assert adapter.prepare_calls == 1
    _assert_no_domain_effects(adapter)


def test_mixed_plan_preview_combines_domain_records_with_local_runtime() -> None:
    linked = _linked_program(state_mode="constant")
    adapter = _DomainAdapter("tests.preview-domain")
    provider = _TrackingProvider()
    plan = ExecutionBackend(
        provider=provider,
        domain_adapters=(adapter,),
    ).prepare(linked, config=load_config())

    preview = build_execution_plan_preview(plan)

    assert [record.producer_kind for record in preview.records] == ["domain"]
    assert preview.state_changes
    assert preview.state_fields
    assert preview.runtime.state_field_count == len(preview.state_fields)
    _assert_no_domain_effects(adapter)


def test_multiple_adapters_batch_independently_within_state_segment() -> None:
    linked = _linked_program(product_count=2)
    pointwise = _DomainAdapter(
        "tests.pointwise-target",
        product_indices=(0,),
        max_points_per_batch=1,
    )
    list_mode = _DomainAdapter(
        "tests.list-target",
        product_indices=(1,),
        max_points_per_batch=100,
    )

    plan = ExecutionBackend(domain_adapters=(pointwise, list_mode)).prepare(
        linked,
        config=load_config(),
    )

    assert tuple(segment.point_indices for segment in plan.segments) == ((0, 1),)
    assert plan.resolved_max_points_per_batch is None
    assert tuple(
        tuple(job.point_indices for job in unit.jobs) for unit in plan.domain_units
    ) == (((0,), (1,)), ((0, 1),))
    assert pointwise.prepare_calls == 2
    assert list_mode.prepare_calls == 1


def test_zero_point_domain_plan_retains_direct_product_ownership() -> None:
    linked = _linked_program(point_count=0)
    adapter = _DomainAdapter("tests.zero-point")

    plan = ExecutionBackend(domain_adapters=(adapter,)).prepare(
        linked,
        config=load_config(),
    )
    record = plan.run_plan_record()

    assert plan.segments == ()
    assert plan.domain_jobs == ()
    assert adapter.capabilities_calls == 1
    assert adapter.prepare_calls == 0
    assert record.point_count == 0
    assert record.records[0].producer_kind == "domain"
    [domain] = record.execution_units
    assert domain.kind == "domain_program"
    assert domain.batches == []

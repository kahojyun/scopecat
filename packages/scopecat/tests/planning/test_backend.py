from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    link_program,
)
from scopecat.compiler.relations.model import (
    lit,
    literal_rows,
    param,
    point_col,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT, point_rows
from scopecat.compiler.relations.verification import (
    ParameterLookupSignature,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    DomainInputPortDef,
    DomainProgramId,
    DomainResultPortDef,
    MeasurementTransformId,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    DomainProductProducer,
    MeasurementTransformProductProducer,
)
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
    TypedProgram,
    ValueInput,
    instrument_product_producer,
    product_output,
    record_product,
    set_state_field,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductProducerId,
    product_producer_id,
    product_use,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String, Table, TableColumn
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.planning.backend import ExecutionBackend
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import (
    ParameterDefinition,
    Quantity,
    TableParameterValue,
)
from scopecat.sdk.domain.context import (
    DomainBatchContext,
    DomainExecutionOffer,
)
from scopecat.sdk.domain.execution import (
    PreparedDomainExecution,
)
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResourceClaim,
    DomainResultValue,
    DomainTargetArtifactIdentity,
)
from scopecat.sdk.domain.preparation import (
    DomainEntryPointBinding,
    DomainResultUseBinding,
    DomainTargetEntry,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchRequest,
    DomainReconcileReceipt,
    DomainReconcileRequest,
    DomainSubmitReceipt,
    DomainSubmitRequest,
)
from scopecat.sdk.domain.view import DomainBatchView
from scopecat.sdk.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import scalar_value_expr, table_value_expr
from tests.testkit.signal_instruments import TestSignalInstrumentProvider


class _EffectProbeRuntime:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.fetch_calls = 0
        self.reconcile_calls = 0

    def submit(
        self,
        request: DomainSubmitRequest[dict[str, str]],
    ) -> DomainSubmitReceipt:
        _ = request
        self.submit_calls += 1
        raise AssertionError("planning must not submit a domain invocation")

    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[dict[str, str]]:
        _ = request
        self.fetch_calls += 1
        raise AssertionError("planning must not fetch a domain invocation")

    def reconcile(
        self,
        request: DomainReconcileRequest,
    ) -> DomainReconcileReceipt:
        _ = request
        self.reconcile_calls += 1
        raise AssertionError("planning must not reconcile a domain invocation")


@dataclass
class _DomainAdapter:
    adapter_id: str
    resource_claims: tuple[DomainResourceClaim, ...] = ()
    max_points_per_batch: int = 100
    runtime: _EffectProbeRuntime = field(default_factory=_EffectProbeRuntime)
    select_calls: int = 0
    prepare_calls: int = 0

    def select(
        self,
        view: DomainBatchView,
    ) -> DomainExecutionOffer:
        self.select_calls += 1
        if view.execution is None:
            raise ValueError("expected a domain execution")
        return DomainExecutionOffer(
            max_points_per_batch=self.max_points_per_batch,
        )

    def prepare(self, context: DomainBatchContext) -> PreparedDomainExecution:
        self.prepare_calls += 1
        preparation = context.new_preparation()
        product_uses = context.direct_product_uses
        entries = tuple(
            DomainTargetEntry(
                f"{self.adapter_id}.entry.{point.ordinal}",
                tuple(
                    f"{self.adapter_id}.result.{point.ordinal}.{use_index}"
                    for use_index in range(len(product_uses))
                ),
            )
            for point in context.points
        )
        mapping = preparation.map_measurements(
            entries=entries,
            entry_points=tuple(
                DomainEntryPointBinding(entry.entry_address, point)
                for entry, point in zip(entries, context.points, strict=True)
            ),
            results=tuple(
                DomainResultUseBinding(
                    entry.entry_address,
                    result_address,
                    product_uses[use_index],
                )
                for entry in entries
                for use_index, result_address in enumerate(entry.result_addresses)
            ),
        )
        measurements = preparation.measurement_plan(mapping)
        invocation = DomainInvocationSpec(
            invocation_id=(
                f"{self.adapter_id}.invocation.batch-{context.batch_ordinal}"
            ),
            target=DomainTargetArtifactIdentity(
                target_id=f"{self.adapter_id}.target",
                compiler_id=f"{self.adapter_id}.compiler",
                capability_fingerprint=f"{self.adapter_id}.capabilities",
                artifact_id=(
                    f"{self.adapter_id}.artifact.batch-{context.batch_ordinal}"
                ),
                artifact_fingerprint=f"{self.adapter_id}.artifact-fingerprint",
            ),
            adapter_intent={
                "adapter_id": self.adapter_id,
                "batch_ordinal": str(context.batch_ordinal),
            },
            payload={
                "adapter_id": self.adapter_id,
                "batch_ordinal": str(context.batch_ordinal),
            },
        )
        return preparation.build(
            measurements=measurements,
            invocation=invocation,
            runtime=self.runtime,
            realize=_reject_realization,
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
) -> Sequence[DomainResultValue[str]]:
    raise AssertionError("planning must not realize domain results")


def _linked_program(
    *,
    product_count: int = 1,
    domain_product_count: int | None = None,
    state_mode: Literal["none", "constant", "varying"] = "none",
    point_count: Literal[0, 2] = 2,
    domain_input: ValueInput | None = None,
    config: ConfigProfileSnapshot | None = None,
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
    selected_domain_product_count = (
        product_count if domain_product_count is None else domain_product_count
    )
    domain_execution: TypedDomainExecution | None = None
    domain_product_producers: list[DomainProductProducer] = []
    if selected_domain_product_count:
        program_id = DomainProgramId(SymbolId(local_id="program"))
        selected = tuple(
            zip(products[:selected_domain_product_count], selections, strict=True)
        )
        result_bindings: list[TypedDomainResultBinding] = []
        for index, (product, (use, _record)) in enumerate(selected):
            result_id = f"result-{index}"
            producer_id = product_producer_id(f"domain-result-{index}")
            result_bindings.append(
                TypedDomainResultBinding(
                    id=result_id,
                    product_id=product.id,
                    producer_id=producer_id,
                    product_use_ids=(use.id,),
                )
            )
            domain_product_producers.append(
                DomainProductProducer(
                    id=producer_id,
                    product_id=product.id,
                    result_id=result_id,
                )
            )
        domain_program = TypedDomainProgram(
            id=program_id,
            dialect_id="tests.domain",
            dialect_version="1",
            body=("test-program",),
            input_ports=(
                (DomainInputPortDef("drive_frequency", domain_input.value_type),)
                if domain_input is not None
                else ()
            ),
            result_ports=tuple(
                DomainResultPortDef(binding.id) for binding in result_bindings
            ),
        )
        domain_execution = TypedDomainExecution(
            program=domain_program,
            inputs=(
                {"drive_frequency": domain_input} if domain_input is not None else {}
            ),
            results=tuple(result_bindings),
        )
    instrument_product_producers = tuple(
        instrument_product_producer(product)
        for product in products[selected_domain_product_count:]
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
        domain_execution=domain_execution,
        product_defs=products,
        instrument_product_producers=instrument_product_producers,
        domain_product_producers=tuple(domain_product_producers),
        product_uses=tuple(use for use, _record in selections),
        record_uses=tuple(record for _use, record in selections),
    )
    return link_program(
        program,
        validate_config_environment(load_config() if config is None else config),
    )


def _config_with_domain_lookup() -> ConfigProfileSnapshot:
    config = load_config()
    table_type = Table(
        columns=(
            TableColumn("device", Scalar(String())),
            TableColumn(
                "drive_frequency",
                Scalar(QuantityType(unit="GHz")),
            ),
        ),
        primary_key=("device",),
        min_rows=1,
        max_rows=1,
    )
    definition = ParameterDefinition(
        id="drive_calibration",
        value_type=table_type,
    )
    value = TableParameterValue(
        id="drive_calibration",
        rows=(
            {
                "device": "q0",
                "drive_frequency": Quantity(value=5.25, unit="GHz"),
            },
        ),
    )
    catalog = config.parameter_catalog.model_copy(
        update={"definitions": (*config.parameter_catalog.definitions, definition)}
    )
    system = config.system.model_copy(update={"parameter_catalog": catalog})
    snapshot = config.parameter_snapshot.model_copy(
        update={"values": (*config.parameter_snapshot.values, value)}
    )
    return config.model_copy(update={"system": system, "parameter_snapshot": snapshot})


def _domain_lookup_input(*, transformed: bool) -> ValueInput:
    result_type = Scalar(QuantityType(unit="GHz"))
    signature = ParameterLookupSignature(
        table_id="drive_calibration",
        key_input_types=(("device", Scalar(String())),),
        column_id="drive_frequency",
        result_type=result_type,
    )
    lookup = param(
        "drive_calibration",
        key={"device": "q0"},
        column="drive_frequency",
    )
    expression = lookup + Quantity(value=0.1, unit="GHz") if transformed else lookup
    return ValueInput(
        scalar_value_expr(
            expression,
            bindings=RelationTypeBindings(parameter_lookups=(signature,)),
            expected_type=result_type,
        )
    )


def _linked_instrument_fed_transform_program() -> LinkedPlan:
    source = product_output("source", unit="ratio")
    derived = product_output("derived", unit="ratio")
    source_use = product_use(source.id)
    derived_use, derived_record = record_product(derived)
    transform_id = MeasurementTransformId(SymbolId(local_id="normalize"))
    producer_id = ProductProducerId(derived.id.symbol)
    transform = TypedMeasurementTransform(
        id=transform_id,
        semantic=MeasurementTransformSemanticContract(
            id="tests.normalize",
            version="1",
            portability="host_only",
        ),
        rate="point",
        inputs=(
            TypedMeasurementTransformInput(
                id="source",
                product_id=source.id,
                product_use_id=source_use.id,
            ),
        ),
        outputs=(
            TypedMeasurementTransformOutput(
                id="result",
                product_id=derived.id,
                producer_id=producer_id,
                product_use_ids=(derived_use.id,),
            ),
        ),
    )
    program = TypedProgram(
        id="unplaced-instrument-transform",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        measurement_transforms=(transform,),
        product_defs=(source, derived),
        instrument_product_producers=(
            instrument_product_producer(
                source,
                provider_key="signal",
            ),
        ),
        measurement_transform_product_producers=(
            MeasurementTransformProductProducer(
                id=producer_id,
                product_id=derived.id,
                transform_id=transform_id,
                output_id="result",
            ),
        ),
        product_uses=(source_use, derived_use),
        record_uses=(derived_record,),
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
    assert adapter.select_calls == 1
    assert adapter.prepare_calls == 0
    _assert_no_domain_effects(adapter)


def test_execution_config_must_match_linked_snapshot_before_adapter_effects() -> None:
    linked = _linked_program()
    adapter = _DomainAdapter("tests.config-mismatch")
    different_config = load_config().model_copy(update={"id": "different-config"})

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(domain_adapters=(adapter,)).prepare(
            linked,
            config=different_config,
        )

    assert _problem_codes(captured.value) == {"execution_config_snapshot_mismatch"}
    assert adapter.select_calls == 0
    assert adapter.prepare_calls == 0
    _assert_no_domain_effects(adapter)


def test_planning_reports_unplaced_transform_as_a_capability_boundary() -> None:
    linked = _linked_instrument_fed_transform_program()
    [transform] = linked.program.measurement_transforms
    [output_use_id] = transform.outputs[0].product_use_ids

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(provider=TestSignalInstrumentProvider()).prepare(
            linked,
            config=load_config(),
        )

    assert _problem_codes(captured.value) == {"measurement_transform_placement_missing"}
    assert captured.value.problems[0].details == {
        "transform_id": "normalize",
        "input_product_ids": ("source",),
        "output_product_use_ids": (output_use_id.value,),
    }
    assert captured.value.problems[0].phase is ProblemPhase.PLANNING


def test_unified_planning_rejects_ambiguous_domain_adapter_before_effects() -> None:
    linked = _linked_program()
    first = _DomainAdapter("tests.overlap.first")
    second = _DomainAdapter("tests.overlap.second")
    backend = ExecutionBackend(
        domain_adapters=(first, second),
    )

    with pytest.raises(CheckFailed) as captured:
        backend.prepare(linked, config=load_config())

    assert _problem_codes(captured.value) == {"domain_adapter_selection_ambiguous"}
    assert first.select_calls == 1
    assert second.select_calls == 1
    assert first.prepare_calls == 0
    assert second.prepare_calls == 0
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
    assert plan.domain_unit is not None
    assert tuple(job.point_indices for job in plan.domain_unit.jobs) == ((0,), (1,))
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert adapter.select_calls == 1
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
    assert plan.point_unit is not None
    assert plan.domain_unit is not None
    assert (plan.point_unit.id, plan.domain_unit.id) == (
        "point-instrument",
        "domain-tests.constant-peripheral",
    )
    assert tuple(segment.point_indices for segment in plan.segments) == ((0, 1),)
    assert tuple(job.point_indices for job in plan.domain_unit.jobs) == ((0, 1),)
    assert plan.point_unit.product_use_ids == ()
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert adapter.select_calls == 1
    assert adapter.prepare_calls == 1
    assert [job.prepared.semantic_operation_id for job in plan.domain_unit.jobs] == [
        "domain"
    ]
    _assert_no_domain_effects(adapter)


def test_materialized_domain_execution_retains_direct_config_lookup_bindings() -> None:
    config = _config_with_domain_lookup()
    adapter = _DomainAdapter("tests.config-provenance")
    prepared = ExecutionBackend(domain_adapters=(adapter,)).prepare(
        _linked_program(
            domain_input=_domain_lookup_input(transformed=False),
            config=config,
        ),
        config=config,
    )

    execution = prepared.linked_points.domain_execution
    assert execution is not None
    assert [
        (
            point.logical_ordinal,
            binding.input_id,
            binding.table_id,
            dict(binding.key),
            binding.column_id,
            binding.resolved_value,
        )
        for point in execution.points
        for binding in point.config_input_bindings
    ] == [
        (
            point_index,
            "drive_frequency",
            "drive_calibration",
            {"device": "q0"},
            "drive_frequency",
            Quantity(value=5.25, unit="GHz"),
        )
        for point_index in range(2)
    ]


def test_materialized_domain_execution_omits_transformed_direct_lookup() -> None:
    config = _config_with_domain_lookup()
    adapter = _DomainAdapter("tests.transformed-config-input")
    prepared = ExecutionBackend(domain_adapters=(adapter,)).prepare(
        _linked_program(
            domain_input=_domain_lookup_input(transformed=True),
            config=config,
        ),
        config=config,
    )

    execution = prepared.linked_points.domain_execution
    assert execution is not None
    assert all(not point.config_input_bindings for point in execution.points)


def test_mixed_plan_preview_combines_domain_records_with_local_runtime() -> None:
    linked = _linked_program(state_mode="constant")
    adapter = _DomainAdapter("tests.preview-domain")
    provider = _TrackingProvider()
    plan = ExecutionBackend(
        provider=provider,
        domain_adapters=(adapter,),
    ).prepare(linked, config=load_config())

    assert [record.id for record in plan.projection.projection.records] == ["record-0"]
    assert plan.point_unit is not None
    assert plan.point_unit.bound_plan.state_changes
    assert any(
        state.fields
        for point in plan.point_unit.bound_plan.points
        for state in point.desired_state
    )
    _assert_no_domain_effects(adapter)


def test_zero_point_domain_plan_retains_direct_product_ownership() -> None:
    linked = _linked_program(point_count=0)
    adapter = _DomainAdapter("tests.zero-point")

    plan = ExecutionBackend(domain_adapters=(adapter,)).prepare(
        linked,
        config=load_config(),
    )
    assert plan.segments == ()
    assert plan.domain_unit is not None
    assert plan.domain_unit.jobs == ()
    assert adapter.select_calls == 1
    assert adapter.prepare_calls == 0
    assert len(plan.linked_points.point_domain.points) == 0

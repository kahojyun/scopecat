from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

import pytest

import scopecat.compiler.linking.materialization as local_materialization
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
)
from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.model import (
    lit,
    literal_rows,
    param,
    point_col,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT, point_rows
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    DomainInputPortDef,
    DomainProgramId,
    DomainResultPortDef,
    MeasurementTransformId,
)
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    DomainProductProducer,
    MeasurementTransformProductProducer,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
    ValueInput,
    product_output,
    record_product,
    set_state_field,
)
from scopecat.execution.local.program import ApplyStateStage
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.execution.program import run_local_effects, run_point_regions
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
    Quantity,
)
from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiledJob,
    DomainCompileRequest,
    compiled_jobs,
)
from scopecat.sdk.domain.context import (
    DomainBatchContext,
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
from scopecat.sdk.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from tests.testkit.authoring import load_config
from tests.testkit.parameter_fixtures import (
    PARAMETER_TYPES,
)
from tests.testkit.parameter_fixtures import (
    parameters as parameter_fixture_data,
)
from tests.testkit.relation_plans import scalar_value_expr, table_value_expr
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.typed_program import (
    instrument_product_producer,
    link_program,
    overlay_parameter_cell,
)


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
class _DomainCompiler:
    compiler_id: str
    resource_claims: tuple[DomainResourceClaim, ...] = ()
    max_points_per_job: int = 100
    runtime: _EffectProbeRuntime = field(default_factory=_EffectProbeRuntime)
    compile_calls: int = 0
    prepare_calls: int = 0
    prepared_inputs: list[tuple[object, ...]] = field(default_factory=list)

    @property
    def target_id(self) -> str:
        return f"{self.compiler_id}.target"

    def compile(
        self,
        request: DomainCompileRequest,
    ) -> DomainCompilation:
        self.compile_calls += 1
        return compiled_jobs(
            request,
            compiler_id=self.compiler_id,
            target_id=self.target_id,
            max_points=self.max_points_per_job,
        )

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        _ = job
        self.prepare_calls += 1
        if context.execution.program.inputs:
            self.prepared_inputs.append(
                context.execution.input_values(
                    context.execution.program.inputs[0].id,
                )
            )
        preparation = context.new_preparation()
        product_uses = context.direct_product_uses
        entries = tuple(
            DomainTargetEntry(
                f"{self.compiler_id}.entry.{point.ordinal}",
                tuple(
                    f"{self.compiler_id}.result.{point.ordinal}.{use_index}"
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
                f"{self.compiler_id}.invocation.batch-{context.batch_ordinal}"
            ),
            target=DomainTargetArtifactIdentity(
                target_id=self.target_id,
                compiler_id=self.compiler_id,
                capability_fingerprint=f"{self.compiler_id}.capabilities",
                artifact_id=(
                    f"{self.compiler_id}.artifact.batch-{context.batch_ordinal}"
                ),
                artifact_fingerprint=f"{self.compiler_id}.artifact-fingerprint",
            ),
            target_intent={
                "compiler_id": self.compiler_id,
                "batch_ordinal": str(context.batch_ordinal),
            },
            payload={
                "compiler_id": self.compiler_id,
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
    domain_call_count: int = 1,
    state_mode: Literal["none", "constant", "varying"] = "none",
    point_count: Literal[0, 2] = 2,
    domain_input: ValueInput | None = None,
    parameter_overlays: Sequence[PointParameterOverlay] = (),
    parameter_data: ParameterRelationData | None = None,
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
    domain_executions: tuple[TypedDomainExecution, ...] = ()
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
        if not 1 <= domain_call_count <= len(result_bindings):
            raise ValueError(
                "domain call count must cover at least one result per call"
            )
        execution_ids = (
            ("domain",)
            if domain_call_count == 1
            else tuple(f"domain-{index}" for index in range(domain_call_count))
        )
        result_groups = tuple(
            tuple(
                binding
                for index, binding in enumerate(result_bindings)
                if index % domain_call_count == call_index
            )
            for call_index in range(domain_call_count)
        )
        domain_executions = tuple(
            TypedDomainExecution(
                id=execution_id,
                program=TypedDomainProgram(
                    id=(
                        program_id
                        if domain_call_count == 1
                        else DomainProgramId(SymbolId(local_id=f"program-{call_index}"))
                    ),
                    dialect_id="tests.domain",
                    dialect_version="1",
                    body=("test-program", call_index),
                    input_ports=(
                        (
                            DomainInputPortDef(
                                "drive_frequency",
                                domain_input.value_type,
                            ),
                        )
                        if domain_input is not None
                        else ()
                    ),
                    result_ports=tuple(
                        DomainResultPortDef(binding.id) for binding in bindings
                    ),
                ),
                inputs=(
                    {"drive_frequency": domain_input}
                    if domain_input is not None
                    else {}
                ),
                results=bindings,
            )
            for call_index, (execution_id, bindings) in enumerate(
                zip(execution_ids, result_groups, strict=True)
            )
        )
        execution_id_by_result = {
            binding.id: execution.id
            for execution in domain_executions
            for binding in execution.results
        }
        domain_product_producers.extend(
            DomainProductProducer(
                id=binding.producer_id,
                product_id=binding.product_id,
                execution_id=execution_id_by_result[binding.id],
                result_id=binding.id,
            )
            for binding in result_bindings
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
    program = CoreProgram(
        id="unified-backend-contract",
        kind="compiler_test",
        point_domain=points,
        parameter_overlays=tuple(parameter_overlays),
        effects=(*state, *domain_executions),
        product_defs=products,
        instrument_product_producers=instrument_product_producers,
        domain_product_producers=tuple(domain_product_producers),
        product_uses=tuple(use for use, _record in selections),
        record_uses=tuple(record for _use, record in selections),
    )
    environment = validate_config_environment(
        load_config() if config is None else config
    )
    if parameter_data is not None:
        environment = replace(environment, parameters=parameter_data)
    return link_program(program, environment)


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
    program = CoreProgram(
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


def _assert_no_domain_effects(*compilers: _DomainCompiler) -> None:
    assert all(compiler.runtime.submit_calls == 0 for compiler in compilers)
    assert all(compiler.runtime.fetch_calls == 0 for compiler in compilers)
    assert all(compiler.runtime.reconcile_calls == 0 for compiler in compilers)


def test_unified_planning_rejects_missing_local_provider_before_effects() -> None:
    linked = _linked_program(state_mode="varying")
    compiler = _DomainCompiler("tests.missing-claim")

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(domain_compilers=(compiler,)).compile(
            linked,
            config=load_config(),
        )

    assert _problem_codes(captured.value) == {"local_instrument_provider_missing"}
    assert captured.value.problems[0].details == {}
    assert all(
        problem.phase is ProblemPhase.PLANNING for problem in captured.value.problems
    )
    assert compiler.compile_calls == 0
    assert compiler.prepare_calls == 0
    _assert_no_domain_effects(compiler)


def test_execution_config_must_match_linked_snapshot_before_adapter_effects() -> None:
    linked = _linked_program()
    compiler = _DomainCompiler("tests.config-mismatch")
    different_config = load_config().model_copy(update={"id": "different-config"})

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(domain_compilers=(compiler,)).compile(
            linked,
            config=different_config,
        )

    assert _problem_codes(captured.value) == {"execution_config_snapshot_mismatch"}
    assert compiler.compile_calls == 0
    assert compiler.prepare_calls == 0
    _assert_no_domain_effects(compiler)


def test_planning_reports_unplaced_transform_as_a_capability_boundary() -> None:
    linked = _linked_instrument_fed_transform_program()
    [transform] = linked.program.measurement_transforms
    [output_use_id] = transform.outputs[0].product_use_ids

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(provider=TestSignalInstrumentProvider()).compile(
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


def test_unified_planning_rejects_ambiguous_domain_compiler_before_effects() -> None:
    linked = _linked_program()
    first = _DomainCompiler("tests.overlap.first")
    second = _DomainCompiler("tests.overlap.second")
    backend = ExecutionBackend(
        domain_compilers=(first, second),
    )

    with pytest.raises(CheckFailed) as captured:
        backend.compile(linked, config=load_config())

    assert _problem_codes(captured.value) == {"domain_compiler_selection_ambiguous"}
    assert first.compile_calls == 1
    assert second.compile_calls == 1
    assert first.prepare_calls == 0
    assert second.prepare_calls == 0
    _assert_no_domain_effects(first, second)


def test_run_compilation_enforces_explicit_point_materialization_budget() -> None:
    linked = _linked_program(point_count=2)
    compiler = _DomainCompiler("tests.materialization-budget")

    with pytest.raises(CheckFailed) as captured:
        ExecutionBackend(
            domain_compilers=(compiler,),
            max_materialized_points=1,
        ).compile(linked, config=load_config())

    assert _problem_codes(captured.value) == {"point_materialization_budget_exceeded"}
    assert compiler.compile_calls == 0


def test_parameter_scan_binding_is_shared_with_domain_inputs() -> None:
    frequency_type = Scalar(QuantityType(unit="GHz"))
    point_type = Table(
        columns=(TableColumn("frequency", frequency_type),),
        min_rows=2,
        max_rows=2,
    )
    bindings = RelationTypeBindings(
        parameters=PARAMETER_TYPES,
        point_row=RowType.from_table(point_type),
    )
    domain_input = ValueInput(
        value=scalar_value_expr(
            param(
                "readout_devices",
                key={"device_id": "r0"},
                column="frequency",
            ),
            bindings=bindings,
            expected_type=frequency_type,
        )
    )
    overlay = overlay_parameter_cell(
        "readout_devices",
        key={"device_id": "r0"},
        key_types={"device_id": Scalar(String())},
        column_id="frequency",
        value=point_col("frequency"),
        value_type=frequency_type,
        bindings=bindings,
    )
    linked = _linked_program(
        domain_input=domain_input,
        parameter_overlays=(overlay,),
        parameter_data=parameter_fixture_data(),
    )
    compiler = _DomainCompiler("tests.parameter-binding")

    plan = ExecutionBackend(domain_compilers=(compiler,)).compile(
        linked,
        config=load_config(),
    )

    assert run_local_effects(plan) is None
    assert compiler.prepared_inputs == [
        (
            Quantity(value=4.9, unit="GHz"),
            Quantity(value=5.1, unit="GHz"),
        )
    ]
    assert [
        params.lookup_row("readout_devices", {"device_id": "r0"})["frequency"]
        for params in plan.linked_points.point_parameters
    ] == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]


def test_varying_local_state_forms_domain_effect_barriers() -> None:
    linked = _linked_program(state_mode="varying")
    compiler = _DomainCompiler("tests.effect-regions")
    provider = _TrackingProvider()
    backend = ExecutionBackend(
        provider=provider,
        domain_compilers=(compiler,),
    )

    plan = backend.compile(linked, config=load_config())

    assert tuple(region.point_indices for region in run_point_regions(plan)) == (
        (0,),
        (1,),
    )
    assert tuple(
        job.point_indices
        for region in run_point_regions(plan)
        for job in region.domain_jobs
    ) == ((0,), (1,))
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert compiler.compile_calls == 1
    assert compiler.prepare_calls == 2
    _assert_no_domain_effects(compiler)


def test_domain_compiler_batches_one_state_stable_region() -> None:
    linked = _linked_program(state_mode="constant")
    compiler = _DomainCompiler("tests.constant-peripheral")
    provider = _TrackingProvider()
    backend = ExecutionBackend(
        provider=provider,
        domain_compilers=(compiler,),
    )

    plan = backend.compile(linked, config=load_config())
    local_effects = run_local_effects(plan)
    assert local_effects is not None
    assert local_effects.product_use_ids == ()
    assert {
        job.source_id
        for region in run_point_regions(plan)
        for job in region.domain_jobs
    } == {"domain-domain-tests.constant-peripheral.target"}
    assert tuple(region.point_indices for region in run_point_regions(plan)) == (
        (0, 1),
    )
    domain_jobs = tuple(
        job for region in run_point_regions(plan) for job in region.domain_jobs
    )
    assert tuple(job.point_indices for job in domain_jobs) == ((0, 1),)
    assert local_effects.product_use_ids == ()
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert compiler.compile_calls == 1
    assert compiler.prepare_calls == 1
    assert [job.id for job in domain_jobs] == ["domain:tests.constant-peripheral.job-0"]
    _assert_no_domain_effects(compiler)


def test_ordered_domain_calls_share_one_target_resource_and_keep_identity() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=2,
        domain_call_count=2,
    )
    compiler = _DomainCompiler("tests.multi-call")

    plan = ExecutionBackend(domain_compilers=(compiler,)).compile(
        linked,
        config=load_config(),
    )

    jobs = tuple(
        job for region in run_point_regions(plan) for job in region.domain_jobs
    )
    assert [job.prepared.context.execution.id for job in jobs] == [
        "domain-0",
        "domain-1",
    ]
    assert [job.id for job in jobs] == [
        "domain-0:tests.multi-call.job-0",
        "domain-1:tests.multi-call.job-0",
    ]
    assert [job.source_id for job in jobs] == [
        "domain-domain-0-tests.multi-call.target",
        "domain-domain-1-tests.multi-call.target",
    ]
    assert plan.resource_claims == (ResourceClaim("tests.multi-call.target", "target"),)
    assert compiler.compile_calls == 2
    assert compiler.prepare_calls == 2
    _assert_no_domain_effects(compiler)


def test_mixed_planning_reuses_materialized_linked_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(state_mode="constant")
    compiler = _DomainCompiler("tests.single-materialization")

    def reject_rematerialization(_linked: LinkedPlan) -> MaterializedLinkedPoints:
        raise AssertionError("backend must reuse its materialized linked points")

    monkeypatch.setattr(
        local_materialization,
        "materialize_linked_points",
        reject_rematerialization,
    )

    prepared = ExecutionBackend(
        provider=_TrackingProvider(),
        domain_compilers=(compiler,),
    ).compile(linked, config=load_config())

    assert run_local_effects(prepared) is not None
    assert any(region.domain_jobs for region in run_point_regions(prepared))


def test_mixed_plan_preview_combines_domain_records_with_local_runtime() -> None:
    linked = _linked_program(state_mode="constant")
    compiler = _DomainCompiler("tests.preview-domain")
    provider = _TrackingProvider()
    plan = ExecutionBackend(
        provider=provider,
        domain_compilers=(compiler,),
    ).compile(linked, config=load_config())

    assert [record.id for record in plan.projection.projection.records] == ["record-0"]
    local_effects = run_local_effects(plan)
    assert local_effects is not None
    assert any(
        stage.operations
        for point in local_effects.points
        for stage in point.stages
        if isinstance(stage, ApplyStateStage)
    )
    _assert_no_domain_effects(compiler)


def test_zero_point_domain_plan_retains_direct_product_ownership() -> None:
    linked = _linked_program(point_count=0)
    compiler = _DomainCompiler("tests.zero-point")

    plan = ExecutionBackend(domain_compilers=(compiler,)).compile(
        linked,
        config=load_config(),
    )
    assert run_point_regions(plan) == ()
    assert plan.values.product_use_ids == tuple(use.id for use in linked.product_uses)
    assert compiler.compile_calls == 1
    assert compiler.prepare_calls == 0
    assert len(plan.linked_points.point_domain.points) == 0

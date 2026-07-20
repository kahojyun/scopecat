from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Never

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    LinkedPointMaterializer,
    specialize_linked_program,
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
    DomainResourcePortDef,
    DomainResultPortDef,
    MeasurementTransformId,
)
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import MaterializedPointDomain, PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
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
from scopecat.execution.local.program import ApplyStateOperation, CollectOperation
from scopecat.execution.program import (
    RunCoverageBlock,
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunDomainJob,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import product_use
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    ResourceClaim,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String, Table, TableColumn
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.planning.routing import ResourcePortManifest, RoutingView
from scopecat.planning.system import ExperimentSystem
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
    DomainResultBinding,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchRequest,
    DomainSubmitReceipt,
    DomainSubmitRequest,
)
from scopecat.sdk.domain.view import DomainCallView
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
    instrument_acquisition,
    link_program,
    overlay_parameter_cell,
)


class _EffectProbeRuntime:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.fetch_calls = 0

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


@dataclass
class _DomainCompiler:
    compiler_id: str
    resource_claims: tuple[DomainResourceClaim, ...] = ()
    max_points_per_job: int = 100
    runtime: _EffectProbeRuntime = field(default_factory=_EffectProbeRuntime)
    claim_calls: int = 0
    compile_calls: int = 0
    compile_requests: list[DomainCompileRequest] = field(default_factory=list)
    prepare_calls: int = 0
    prepared_inputs: list[tuple[object, ...]] = field(default_factory=list)
    events: list[str] | None = None
    assign_target_by_execution: bool = False

    def claim_resources(
        self,
        call: DomainCallView,
    ) -> tuple[ResourceClaim, ...]:
        self.claim_calls += 1
        target_id = (
            f"{self.compiler_id}.{call.id}.target"
            if self.assign_target_by_execution
            else f"{self.compiler_id}.target"
        )
        return tuple(
            ResourceClaim(claim.id, claim.kind) for claim in self.resource_claims
        ) or (ResourceClaim(target_id, "target"),)

    def compile(
        self,
        request: DomainCompileRequest,
    ) -> DomainCompilation:
        self.compile_calls += 1
        self.compile_requests.append(request)
        if self.events is not None:
            self.events.append("compile")
        return compiled_jobs(
            request,
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
        result_addresses = tuple(
            tuple(
                f"{self.compiler_id}.result.{point.ordinal}.{use_index}"
                for use_index in range(len(product_uses))
            )
            for point in context.points
        )
        mapping = preparation.map_measurements(
            results=tuple(
                DomainResultBinding(
                    result_address,
                    point,
                    product_uses[use_index],
                )
                for point, addresses in zip(
                    context.points, result_addresses, strict=True
                )
                for use_index, result_address in enumerate(addresses)
            ),
        )
        target_id = (
            f"{self.compiler_id}.{context.execution.id}.target"
            if self.assign_target_by_execution
            else f"{self.compiler_id}.target"
        )
        invocation = DomainInvocationSpec(
            invocation_id=(
                f"{self.compiler_id}.invocation.batch-{context.batch_ordinal}"
            ),
            target=DomainTargetArtifactIdentity(
                target_id=target_id,
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
            mapping=mapping,
            invocation=invocation,
            runtime=self.runtime,
            realize=_reject_realization,
        )


@dataclass
class _BindingProbeCompiler:
    bound_ordinals: tuple[int, ...] = ()
    compile_request: DomainCompileRequest | None = field(default=None, init=False)

    def claim_resources(
        self,
        call: DomainCallView,
    ) -> tuple[ResourceClaim, ...] | None:
        del call
        return None

    def compile(self, request: DomainCompileRequest) -> None:
        self.compile_request = request
        self.bound_ordinals = request.resolve_inputs(
            ("drive_frequency",), (1,), max_points=1
        ).ordinals
        return None

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        del job, context
        raise AssertionError("an unselected compiler cannot prepare jobs")


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
    domain_before_state: bool = False,
    acquisition_before_domain: bool = False,
    record_instrument_products: bool = True,
    point_count: Literal[0, 2] = 2,
    equal_point_values: bool = False,
    domain_input: ValueInput | None = None,
    domain_resource: bool = False,
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
                        {
                            "frequency": Quantity(
                                value=4.9 if equal_point_values else 5.1,
                                unit="GHz",
                            )
                        },
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
    if selected_domain_product_count:
        program_id = DomainProgramId(SymbolId(local_id="program"))
        selected = tuple(
            zip(
                products[:selected_domain_product_count],
                selections[:selected_domain_product_count],
                strict=True,
            )
        )
        result_bindings: list[TypedDomainResultBinding] = []
        for index, (product, (use, _record)) in enumerate(selected):
            result_id = f"result-{index}"
            result_bindings.append(
                TypedDomainResultBinding(
                    id=result_id,
                    product_id=product.id,
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
                    resource_ports=(
                        (DomainResourcePortDef("drive", ("domain.drive",)),)
                        if domain_resource
                        else ()
                    ),
                ),
                inputs=(
                    {"drive_frequency": domain_input}
                    if domain_input is not None
                    else {}
                ),
                results=bindings,
                resources=(
                    {"drive": logical_resource_port_id("domain-drive")}
                    if domain_resource
                    else {}
                ),
            )
            for call_index, (execution_id, bindings) in enumerate(
                zip(execution_ids, result_groups, strict=True)
            )
        )
    instrument_acquisitions = tuple(
        instrument_acquisition(product, capability="scalar_signal")
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
                resource_port_id=logical_resource_port_id("source"),
                capability_id="set_frequency",
                field_path="frequency",
                value=state_value,
            ),
        )
        if state_value is not None
        else ()
    )
    domain_and_state = (
        (*domain_executions, *state)
        if domain_before_state
        else (*state, *domain_executions)
    )
    effects = (
        (*instrument_acquisitions, *domain_and_state)
        if acquisition_before_domain
        else (*domain_and_state, *instrument_acquisitions)
    )
    recorded_selections = (
        selections
        if record_instrument_products
        else selections[:selected_domain_product_count]
    )
    program = CoreProgram(
        id="unified-system-contract",
        kind="compiler_test",
        point_domain=points,
        resource_requirements=(
            *(
                (
                    LogicalResourceRequirement(
                        port_id=logical_resource_port_id("domain-drive"),
                        capabilities=("domain.drive",),
                    ),
                )
                if domain_resource
                else ()
            ),
            *(
                (
                    LogicalResourceRequirement(
                        port_id=logical_resource_port_id("source"),
                        capabilities=(
                            ("set_frequency", "scalar_signal")
                            if state
                            else ("scalar_signal",)
                        ),
                    ),
                )
                if state or instrument_acquisitions
                else ()
            ),
        ),
        parameter_overlays=tuple(parameter_overlays),
        effects=effects,
        product_defs=products,
        product_uses=tuple(use for use, _record in recorded_selections),
        record_uses=tuple(record for _use, record in recorded_selections),
    )
    environment = validate_config_environment(
        load_config() if config is None else config
    )
    if parameter_data is not None:
        environment = replace(environment, parameters=parameter_data)
    return specialize_linked_program(link_program(program, environment))


def _point_frequency_domain_input() -> ValueInput:
    frequency_type = Scalar(QuantityType(unit="GHz"))
    point_type = Table(
        columns=(TableColumn("frequency", frequency_type),),
        min_rows=0,
        max_rows=None,
    )
    return ValueInput(
        value=scalar_value_expr(
            point_col("frequency"),
            bindings=RelationTypeBindings(point_row=RowType.from_table(point_type)),
            expected_type=frequency_type,
        )
    )


def _linked_instrument_fed_transform_program() -> LinkedPlan:
    source = product_output("source", unit="ratio")
    derived = product_output("derived", unit="ratio")
    source_use = product_use(source.id)
    derived_use, derived_record = record_product(derived)
    transform_id = MeasurementTransformId(SymbolId(local_id="normalize"))
    transform = TypedMeasurementTransform(
        id=transform_id,
        semantic=MeasurementTransformSemanticContract(
            id="tests.normalize",
            version="1",
            portability="host_only",
        ),
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
                product_use_ids=(derived_use.id,),
            ),
        ),
    )
    program = CoreProgram(
        id="unplaced-instrument-transform",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("scalar_signal",),
            ),
        ),
        effects=(
            instrument_acquisition(
                source,
                capability="scalar_signal",
                provider_key="signal",
            ),
        ),
        measurement_transforms=(transform,),
        product_defs=(source, derived),
        product_uses=(source_use, derived_use),
        record_uses=(derived_record,),
    )
    return specialize_linked_program(
        link_program(
            program,
            validate_config_environment(load_config()),
        )
    )


def _problem_codes(error: CheckFailed) -> set[str]:
    return {problem.code for problem in error.problems}


def _track_bound_resource_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> list[LogicalResourcePortId]:
    calls: list[LogicalResourcePortId] = []
    original = RoutingView.bind_port

    def track_binding(
        routing: RoutingView,
        *,
        port_id: LogicalResourcePortId,
        capabilities: Sequence[str],
    ) -> ResourcePortManifest:
        calls.append(port_id)
        return original(
            routing,
            port_id=port_id,
            capabilities=capabilities,
        )

    monkeypatch.setattr(RoutingView, "bind_port", track_binding)
    return calls


def _assert_no_domain_effects(*compilers: _DomainCompiler) -> None:
    assert all(compiler.runtime.submit_calls == 0 for compiler in compilers)
    assert all(compiler.runtime.fetch_calls == 0 for compiler in compilers)


def test_unified_planning_rejects_missing_local_provider_before_effects() -> None:
    linked = _linked_program(state_mode="varying")
    compiler = _DomainCompiler("tests.missing-claim")

    with pytest.raises(CheckFailed) as captured:
        ExperimentSystem(domain_compiler=compiler).compile(
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
        ExperimentSystem(domain_compiler=compiler).compile(
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
        ExperimentSystem(provider=TestSignalInstrumentProvider()).compile(
            linked,
            config=load_config(),
        )

    assert _problem_codes(captured.value) == {
        "measurement_transform_implementation_missing"
    }
    assert captured.value.problems[0].details == {
        "transform_id": "normalize",
        "input_product_ids": ("source",),
        "output_product_use_ids": (output_use_id.value,),
    }
    assert captured.value.problems[0].phase is ProblemPhase.PLANNING


def test_run_compilation_materializes_large_space_in_bounded_blocks() -> None:
    linked = _linked_program(point_count=2)
    compiler = _DomainCompiler("tests.materialization-budget")

    plan = ExperimentSystem(
        domain_compiler=compiler,
        coverage_block_size=1,
    ).compile(linked, config=load_config())

    assert len(plan.points.points) == 2
    assert [
        operation.point_indices
        for operation in plan.coverage
        if isinstance(operation, RunCoverageBlock)
    ] == [(0,), (1,)]
    assert compiler.compile_calls == 2


def test_local_resource_manifest_is_reused_across_coverage_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(domain_product_count=0, point_count=2)
    calls = _track_bound_resource_ports(monkeypatch)
    plan = ExperimentSystem(
        provider=TestSignalInstrumentProvider(),
        coverage_block_size=1,
    ).compile(linked, config=load_config())

    assert calls == [logical_resource_port_id("source")]
    assert len(tuple(plan.coverage)) == 2
    assert calls == [logical_resource_port_id("source")]


def test_domain_only_resource_does_not_require_a_local_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(domain_resource=True)
    compiler = _DomainCompiler("tests.domain-only-resource")
    calls = _track_bound_resource_ports(monkeypatch)

    plan = ExperimentSystem(domain_compiler=compiler).compile(
        linked,
        config=load_config(),
    )

    [block] = plan.coverage
    assert block.point_indices == (0, 1)
    assert calls == []
    assert compiler.compile_calls == 1
    resource = compiler.compile_requests[0].call.resource("drive")
    assert resource.resource_port_id == "domain-drive"
    assert resource.capabilities == ("domain.drive",)
    assert block.resource_claims == (
        ResourceClaim("tests.domain-only-resource.target", "target"),
    )


def test_mixed_target_builds_manifests_only_for_local_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(
        domain_resource=True,
        state_mode="constant",
    )
    compiler = _DomainCompiler("tests.mixed-resource-target")
    calls = _track_bound_resource_ports(monkeypatch)

    plan = ExperimentSystem(
        provider=TestSignalInstrumentProvider(),
        domain_compiler=compiler,
    ).compile(linked, config=load_config())

    assert calls == [logical_resource_port_id("source")]
    assert len(tuple(plan.coverage)) == 1
    assert calls == [logical_resource_port_id("source")]


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

    plan = ExperimentSystem(domain_compiler=compiler).compile(
        linked,
        config=load_config(),
    )

    assert plan.host is None
    [block] = plan.coverage
    assert isinstance(block, RunCoverageBlock)
    assert block.point_indices == (0, 1)
    [domain_job] = (
        operation
        for operation in block.operations
        if isinstance(operation, RunDomainJob)
    )
    assert isinstance(domain_job, RunDomainJob)
    domain_job.prepare()
    assert compiler.prepared_inputs == [
        (
            Quantity(value=4.9, unit="GHz"),
            Quantity(value=5.1, unit="GHz"),
        )
    ]


def test_unclaimed_local_state_does_not_fragment_domain_jobs() -> None:
    linked = _linked_program(state_mode="varying")
    compiler = _DomainCompiler("tests.effect-regions")
    provider = _TrackingProvider()
    system = ExperimentSystem(
        provider=provider,
        domain_compiler=compiler,
    )

    plan = system.compile(linked, config=load_config())

    [block] = plan.coverage
    assert block.point_indices == (0, 1)
    assert [
        operation.point_ordinals
        for operation in block.operations
        if isinstance(operation, RunDomainJob)
    ] == [(0, 1)]
    assert [
        operation.point_indices
        for operation in block.operations
        if isinstance(operation, RunCoverageEffect)
    ] == [(0,), (1,)]
    assert [
        operation.point_indices
        for operation in block.operations
        if isinstance(operation, RunCoverageCheckpoint)
    ] == [(0,), (1,)]
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert compiler.compile_calls == 1
    assert compiler.claim_calls == 1
    assert compiler.prepare_calls == 0
    _assert_no_domain_effects(compiler)


def test_domain_and_local_state_retain_declared_effect_order() -> None:
    linked = _linked_program(
        state_mode="constant",
        domain_before_state=True,
    )
    plan = ExperimentSystem(
        provider=_TrackingProvider(),
        domain_compiler=_DomainCompiler("tests.declared-effect-order"),
    ).compile(linked, config=load_config())

    [block] = plan.coverage
    consequential = tuple(
        operation
        for operation in block.operations
        if not isinstance(operation, RunCoverageCheckpoint)
    )

    assert isinstance(consequential[0], RunDomainJob)
    assert isinstance(consequential[1], RunCoverageEffect)
    assert isinstance(consequential[1].operation, ApplyStateOperation)


def test_local_acquisition_before_domain_is_ordered_per_point() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=1,
        acquisition_before_domain=True,
    )
    compiler = _DomainCompiler(
        "tests.acquisition-before-domain",
        resource_claims=(DomainResourceClaim("instrument", "source-0"),),
    )
    plan = ExperimentSystem(
        provider=_TrackingProvider(),
        domain_compiler=compiler,
    ).compile(linked, config=load_config())

    [block] = plan.coverage

    assert block.point_indices == (0, 1)
    for ordinal in range(2):
        offset = ordinal * 3
        acquisition, domain, checkpoint = block.operations[offset : offset + 3]
        assert isinstance(acquisition, RunCoverageEffect)
        assert acquisition.point_indices == (ordinal,)
        assert isinstance(acquisition.operation, CollectOperation)
        assert isinstance(domain, RunDomainJob)
        assert domain.point_ordinals == (ordinal,)
        assert isinstance(checkpoint, RunCoverageCheckpoint)
        assert checkpoint.point_indices == (ordinal,)
    assert [request.barrier_regions for request in compiler.compile_requests] == [
        ((0,),),
        ((1,),),
    ]


def test_domain_before_local_acquisition_is_ordered_per_point() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=1,
    )
    compiler = _DomainCompiler(
        "tests.domain-before-acquisition",
        resource_claims=(DomainResourceClaim("instrument", "source-0"),),
    )
    plan = ExperimentSystem(
        provider=_TrackingProvider(),
        domain_compiler=compiler,
    ).compile(linked, config=load_config())

    [block] = plan.coverage

    assert block.point_indices == (0, 1)
    domain, acquisition_0, checkpoint_0, acquisition_1, checkpoint_1 = block.operations
    assert isinstance(domain, RunDomainJob)
    assert domain.point_ordinals == (0, 1)
    for ordinal, (acquisition, checkpoint) in enumerate(
        ((acquisition_0, checkpoint_0), (acquisition_1, checkpoint_1))
    ):
        assert isinstance(acquisition, RunCoverageEffect)
        assert acquisition.point_indices == (ordinal,)
        assert isinstance(acquisition.operation, CollectOperation)
        assert isinstance(checkpoint, RunCoverageCheckpoint)
        assert checkpoint.point_indices == (ordinal,)
    assert [request.barrier_regions for request in compiler.compile_requests] == [
        ((0, 1),),
    ]


def test_unused_local_acquisition_does_not_fragment_domain_coverage() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=1,
        record_instrument_products=False,
    )
    compiler = _DomainCompiler("tests.unused-acquisition")
    plan = ExperimentSystem(domain_compiler=compiler).compile(
        linked,
        config=load_config(),
    )

    [block] = plan.coverage
    [domain] = (
        operation
        for operation in block.operations
        if isinstance(operation, RunDomainJob)
    )

    assert block.point_indices == (0, 1)
    assert domain.point_ordinals == (0, 1)
    assert [request.barrier_regions for request in compiler.compile_requests] == [
        ((0, 1),)
    ]


def test_conflicting_local_state_refines_domain_jobs_by_exact_coverage() -> None:
    linked = _linked_program(state_mode="varying")
    compiler = _DomainCompiler(
        "tests.state-conflict",
        resource_claims=(DomainResourceClaim("instrument", "source-0"),),
    )

    plan = ExperimentSystem(
        provider=_TrackingProvider(),
        domain_compiler=compiler,
    ).compile(linked, config=load_config())

    [block] = plan.coverage
    assert block.point_indices == (0, 1)
    assert [
        operation.point_ordinals
        for operation in block.operations
        if isinstance(operation, RunDomainJob)
    ] == [(0,), (1,)]
    assert compiler.compile_calls == 2
    assert compiler.claim_calls == 1
    assert [request.barrier_regions for request in compiler.compile_requests] == [
        ((0,),),
        ((1,),),
    ]


def test_equal_materialized_state_values_share_one_domain_region() -> None:
    linked = _linked_program(state_mode="varying", equal_point_values=True)
    compiler = _DomainCompiler("tests.typed-effect-dependencies")

    plan = ExperimentSystem(
        provider=_TrackingProvider(),
        domain_compiler=compiler,
    ).compile(linked, config=load_config())

    blocks = tuple(plan.coverage)
    jobs = tuple(
        operation
        for block in blocks
        for operation in block.operations
        if isinstance(operation, RunDomainJob)
    )
    assert tuple(job.point_ordinals for job in jobs) == ((0, 1),)
    assert compiler.prepare_calls == 0


def test_domain_compiler_batches_one_state_stable_region() -> None:
    linked = _linked_program(state_mode="constant")
    compiler = _DomainCompiler("tests.constant-peripheral")
    provider = _TrackingProvider()
    system = ExperimentSystem(
        provider=provider,
        domain_compiler=compiler,
    )

    plan = system.compile(linked, config=load_config())
    local_effects = plan.host
    assert local_effects is not None
    point_catalog = plan.points
    assert point_catalog.experiment_id == linked.program.id
    assert point_catalog.experiment_kind == linked.program.kind
    assert point_catalog.coordinate_ids == ("frequency",)
    assert tuple(point.ordinal for point in point_catalog.points) == (0, 1)
    assert [point.coordinates for point in point_catalog.points] == [
        {"frequency": Quantity(value=4.9, unit="GHz")},
        {"frequency": Quantity(value=5.1, unit="GHz")},
    ]
    domain_jobs = tuple(
        operation
        for block in plan.coverage
        for operation in block.operations
        if isinstance(operation, RunDomainJob)
    )
    assert tuple(job.point_ordinals for job in domain_jobs) == ((0, 1),)
    [domain_job] = domain_jobs
    domain_job.prepare()
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert compiler.compile_calls == 1
    assert compiler.prepare_calls == 1
    assert [job.id for job in domain_jobs] == ["domain:coverage-0:job-0"]
    _assert_no_domain_effects(compiler)


def test_ordered_domain_calls_share_one_target_resource_and_keep_job_identity() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=2,
        domain_call_count=2,
    )
    compiler = _DomainCompiler("tests.multi-call")

    plan = ExperimentSystem(domain_compiler=compiler).compile(
        linked,
        config=load_config(),
    )

    blocks = tuple(plan.coverage)
    jobs = tuple(
        operation
        for block in blocks
        for operation in block.operations
        if isinstance(operation, RunDomainJob)
    )
    assert len({job.id for job in jobs}) == 2
    assert {claim for block in blocks for claim in block.resource_claims} == {
        ResourceClaim("tests.multi-call.target", "target")
    }
    assert compiler.compile_calls == 2
    assert compiler.prepare_calls == 0
    _assert_no_domain_effects(compiler)


def test_system_compiler_can_assign_domain_calls_to_distinct_targets() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=2,
        domain_call_count=2,
    )
    compiler = _DomainCompiler(
        "tests.multi-target",
        assign_target_by_execution=True,
    )

    plan = ExperimentSystem(domain_compiler=compiler).compile(
        linked,
        config=load_config(),
    )

    assert {claim for block in plan.coverage for claim in block.resource_claims} == {
        ResourceClaim("tests.multi-target.domain-0.target", "target"),
        ResourceClaim("tests.multi-target.domain-1.target", "target"),
    }


def test_point_inventory_closes_before_first_streaming_domain_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(domain_input=_point_frequency_domain_input())
    events: list[str] = []
    compiler = _DomainCompiler("tests.symbolic-first", events=events)
    original_materialize = LinkedPointMaterializer.materialize_point_domain

    def track_materialization(
        materializer: LinkedPointMaterializer,
    ) -> MaterializedPointDomain:
        events.append("materialize")
        return original_materialize(materializer)

    monkeypatch.setattr(
        LinkedPointMaterializer,
        "materialize_point_domain",
        track_materialization,
    )

    plan = ExperimentSystem(domain_compiler=compiler).compile(
        linked,
        config=load_config(),
    )

    assert events == ["materialize"]
    tuple(plan.coverage)
    assert events == ["materialize", "compile"]


def test_rejected_domain_call_does_not_bind_point_inputs() -> None:
    linked = _linked_program(domain_input=_point_frequency_domain_input())
    compiler = _BindingProbeCompiler()

    with pytest.raises(CheckFailed) as captured:
        ExperimentSystem(domain_compiler=compiler).compile(
            linked,
            config=load_config(),
        )

    assert _problem_codes(captured.value) == {"domain_compiler_missing"}
    assert compiler.compile_request is None
    assert compiler.bound_ordinals == ()


def test_complete_point_materialization_does_not_evaluate_domain_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materializer = LinkedPointMaterializer(
        _linked_program(domain_input=_point_frequency_domain_input())
    )

    materializer.bind_domain_inputs(
        "domain",
        ("drive_frequency",),
        (1,),
        max_points=1,
    )

    def reject_domain_inputs(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError("point materialization must not evaluate domain inputs")

    monkeypatch.setattr(
        LinkedPointMaterializer,
        "_domain_inputs",
        reject_domain_inputs,
    )
    linked_points = materializer.materialize()

    assert len(linked_points.point_domain.points) == 2


def test_mixed_plan_preview_combines_domain_records_with_local_runtime() -> None:
    linked = _linked_program(state_mode="constant")
    compiler = _DomainCompiler("tests.preview-domain")
    provider = _TrackingProvider()
    plan = ExperimentSystem(
        provider=provider,
        domain_compiler=compiler,
    ).compile(linked, config=load_config())

    assert [record.id for record in plan.measurements.records] == ["record-0"]
    local_effects = plan.host
    assert local_effects is not None
    assert any(
        operation.operation
        for block in plan.coverage
        if isinstance(block, RunCoverageBlock)
        for operation in block.operations
        if isinstance(operation, RunCoverageEffect)
        and isinstance(operation.operation, ApplyStateOperation)
    )
    _assert_no_domain_effects(compiler)


def test_zero_point_domain_plan_retains_direct_product_ownership() -> None:
    linked = _linked_program(point_count=0)
    compiler = _DomainCompiler("tests.zero-point")

    plan = ExperimentSystem(domain_compiler=compiler).compile(
        linked,
        config=load_config(),
    )
    assert tuple(plan.coverage) == ()
    assert plan.measurements.product_values.product_use_ids == tuple(
        use.id for use in linked.product_uses
    )
    assert compiler.compile_calls == 0
    assert compiler.prepare_calls == 0
    assert plan.points.points == ()

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Never, cast, override

import pytest

import scopecat.compiler.linking.linked as linking
import scopecat.planning.system as planning_system
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    MeasurementPostprocessorId,
)
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    ScalarValueInput,
    TypedDomainExecution,
    TypedDomainResultBinding,
    TypedMeasurementPostprocessor,
    TypedMeasurementPostprocessorOutput,
    ValueInput,
    record_product,
    set_state_field,
)
from scopecat.config.environment import build_config_environment
from scopecat.domain.program import (
    DomainInputPort,
    DomainProgramDef,
    DomainResultPort,
)
from scopecat.execution.local.program import ApplyStateOperation
from scopecat.execution.program import (
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunDomainJob,
)
from scopecat.graph.relations.model import (
    lit,
    parameter_lookup,
    point_col,
)
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import product_use
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    ResourceClaim,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, Table, TableColumn
from scopecat.measurements.results import MeasurementValue
from scopecat.planning.routing import ResourcePortManifest, RoutingView
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import (
    ConfigProfileSnapshot,
    DomainTargetBinding,
)
from scopecat.sdk.domain import (
    DomainBatchRequest,
    DomainPreparationBuilder,
)
from scopecat.sdk.domain.execution import (
    PreparedDomainExecution,
)
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResultValue,
)
from scopecat.sdk.domain.result_mapping import (
    DomainResultBinding,
)
from scopecat.sdk.domain.runtime import (
    DomainFetchReceipt,
    DomainFetchResult,
    DomainSubmitReceipt,
)
from scopecat.sdk.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from tests.testkit.authoring import load_config
from tests.testkit.parameter_fixtures import (
    READOUT_FREQUENCY_LOOKUP,
)
from tests.testkit.parameter_fixtures import (
    parameters as parameter_fixture_data,
)
from tests.testkit.relation_plans import scalar_value_expr
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.typed_program import (
    instrument_acquisition,
    link_program,
    observable_product,
    overlay_parameter_cell,
)


class _EffectProbeRuntime:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.fetch_calls = 0

    def submit(
        self,
        submission_key: str,
        payload: dict[str, str],
    ) -> DomainSubmitReceipt:
        del submission_key, payload
        self.submit_calls += 1
        raise AssertionError("planning must not submit a domain invocation")

    def fetch(
        self,
        submission_key: str,
        job_id: str,
    ) -> DomainFetchReceipt | DomainFetchResult[dict[str, str]]:
        del submission_key, job_id
        self.fetch_calls += 1
        raise AssertionError("planning must not fetch a domain invocation")


@dataclass
class _DomainCompiler:
    compiler_id: str
    max_points_per_batch: int = 100
    runtime: _EffectProbeRuntime = field(default_factory=_EffectProbeRuntime)
    compile_calls: int = 0
    compile_requests: list[DomainBatchRequest] = field(default_factory=list)
    prepared_inputs: list[tuple[object, ...]] = field(default_factory=list)
    events: list[str] | None = None

    @property
    def target_id(self) -> str:
        return "tests.domain.target"

    @property
    def target_kind(self) -> str:
        return "tests.domain"

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution:
        self.compile_calls += 1
        self.compile_requests.append(request)
        if self.events is not None:
            self.events.append("compile")
        if request.inputs.program:
            self.prepared_inputs.append(
                request.inputs.program[0][1],
            )
        preparation = DomainPreparationBuilder(request)
        product_uses = request.product_uses
        result_addresses = tuple(
            tuple(
                f"{self.compiler_id}.result.{point.ordinal}.{use_index}"
                for use_index in range(len(product_uses))
            )
            for point in request.points
        )
        mapping = preparation.map_measurements(
            results=tuple(
                DomainResultBinding(
                    result_address,
                    point,
                    product_uses[use_index],
                )
                for point, addresses in zip(
                    request.points, result_addresses, strict=True
                )
                for use_index, result_address in enumerate(addresses)
            ),
        )
        invocation = DomainInvocationSpec(
            invocation_id=(
                f"{self.compiler_id}.invocation.batch-{request.batch_ordinal}"
            ),
            target_id=self.target_id,
            compiler_id=self.compiler_id,
            capability_fingerprint=f"{self.compiler_id}.capabilities",
            artifact_id=(f"{self.compiler_id}.artifact.batch-{request.batch_ordinal}"),
            artifact_fingerprint=f"{self.compiler_id}.artifact-fingerprint",
            target_intent={
                "compiler_id": self.compiler_id,
                "batch_ordinal": str(request.batch_ordinal),
            },
            payload={
                "compiler_id": self.compiler_id,
                "batch_ordinal": str(request.batch_ordinal),
            },
        )
        return preparation.build(
            mapping=mapping,
            invocation=invocation,
            runtime=self.runtime,
            realize=_reject_realization,
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


@dataclass
class _BroadTrackingProvider(_TrackingProvider):
    @override
    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        description = super().describe(context)
        [source] = description.instruments
        return replace(
            description,
            instruments=(
                source,
                source.model_copy(update={"instrument_id": "unused-0"}),
            ),
        )


def _reject_realization(
    _fetched: DomainFetchResult[dict[str, str]],
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
    domain_input: ScalarValueInput | None = None,
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
    )
    points = PointDomain(
        axes=(
            point_axis_values(
                "frequency",
                point_type.columns[0].value_type,
                (
                    (
                        Quantity(value=4.9, unit="GHz"),
                        Quantity(value=5.1, unit="GHz"),
                    )
                    if point_count
                    else ()
                ),
            ),
        )
    )
    products = tuple(
        observable_product(f"signal-{index}", unit="ratio")
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
        program_id = "program"
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
                program=DomainProgramDef(
                    id=(
                        program_id
                        if domain_call_count == 1
                        else f"program-{call_index}"
                    ),
                    dialect_id="tests.domain",
                    dialect_version="1",
                    body=("test-program", call_index),
                    input_ports=(
                        (
                            DomainInputPort(
                                "drive_frequency",
                                domain_input.value_type,
                            ),
                        )
                        if domain_input is not None
                        else ()
                    ),
                    result_ports=tuple(
                        DomainResultPort(binding.id) for binding in bindings
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
    instrument_acquisitions = tuple(
        instrument_acquisition(
            product,
            capability="scalar_signal",
            provider_key="signal",
        )
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
    environment = build_config_environment(load_config() if config is None else config)
    if parameter_data is not None:
        environment = replace(environment, parameters=parameter_data)
    return link_program(program, environment)


def _point_frequency_domain_input() -> ScalarValueInput:
    frequency_type = Scalar(QuantityType(unit="GHz"))
    point_type = Table(
        columns=(TableColumn("frequency", frequency_type),),
    )
    return ValueInput(
        value=scalar_value_expr(
            point_col("frequency"),
            bindings=RelationTypeBindings(point_row=RowType.from_table(point_type)),
            expected_type=frequency_type,
        )
    )


def _postprocess_identity(
    value: MeasurementValue,
) -> dict[str, MeasurementValue]:
    return {"result": value}


def _linked_instrument_fed_postprocessor_program() -> LinkedPlan:
    source = observable_product("source", unit="ratio")
    derived = observable_product("derived", unit="ratio")
    source_use = product_use(source.id)
    derived_use, derived_record = record_product(derived)
    postprocessor_id = MeasurementPostprocessorId(SymbolId(local_id="normalize"))
    postprocessor = TypedMeasurementPostprocessor(
        id=postprocessor_id,
        input_product_id=source.id,
        input_product_use_id=source_use.id,
        outputs=(
            TypedMeasurementPostprocessorOutput(
                id="result",
                product_id=derived.id,
                product_use_ids=(derived_use.id,),
            ),
        ),
        kernel=_postprocess_identity,
    )
    program = CoreProgram(
        id="instrument-postprocessor",
        kind="compiler_test",
        point_domain=PointDomain(axes=()),
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
        measurement_postprocessors=(postprocessor,),
        product_defs=(source, derived),
        product_uses=(source_use, derived_use),
        record_uses=(derived_record,),
    )
    return link_program(
        program,
        build_config_environment(load_config()),
    )


def _problem_codes(error: CheckFailed) -> set[str]:
    return {problem.code for problem in error.problems}


def _config_with_domain_resources(
    *instrument_ids: str,
) -> ConfigProfileSnapshot:
    config = load_config()
    system = config.system.model_copy(
        update={
            "domain_target": DomainTargetBinding(
                id="tests.domain.target",
                kind="tests.domain",
                instrument_ids=list(instrument_ids),
            )
        }
    )
    return config.model_copy(update={"system": system})


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
        ExperimentSystem(domain_compiler=compiler).compile(linked)

    assert _problem_codes(captured.value) == {"local_instrument_provider_missing"}
    assert captured.value.problems[0].details == {}
    assert all(
        problem.phase is ProblemPhase.PLANNING for problem in captured.value.problems
    )
    assert compiler.compile_calls == 0
    _assert_no_domain_effects(compiler)


def test_planning_keeps_postprocessor_outputs_out_of_local_acquisition() -> None:
    linked = _linked_instrument_fed_postprocessor_program()

    plan = ExperimentSystem(provider=TestSignalInstrumentProvider()).compile(linked)

    [postprocessor] = plan.measurement_postprocessors
    assert postprocessor.id.qualified_name == "normalize"
    assert postprocessor.input_product_id.qualified_name == "source"


def test_domain_target_partitions_complete_point_space_by_capacity() -> None:
    linked = _linked_program(point_count=2)
    compiler = _DomainCompiler(
        "tests.target-capacity",
        max_points_per_batch=1,
    )

    plan = ExperimentSystem(domain_compiler=compiler).compile(linked)

    assert len(plan.points.points) == 2
    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)
    assert [
        operation.point_ordinals
        for operation in plan.coverage
        if isinstance(operation, RunDomainJob)
    ] == [(0,), (1,)]
    assert compiler.compile_calls == 2
    assert [request.point_ordinals for request in compiler.compile_requests] == [
        (0,),
        (1,),
    ]


def test_local_resource_manifest_is_selected_once_for_complete_point_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(domain_product_count=0, point_count=2)
    calls = _track_bound_resource_ports(monkeypatch)
    plan = ExperimentSystem(provider=TestSignalInstrumentProvider()).compile(linked)

    assert calls == [logical_resource_port_id("source")]
    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)
    assert calls == [logical_resource_port_id("source")]


def test_run_claims_and_host_order_include_only_used_local_instruments() -> None:
    config = load_config()
    seed_instrument = config.instrument_registry.instruments[0]
    config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "instrument_registry": config.instrument_registry.model_copy(
                        update={
                            "instruments": [
                                seed_instrument,
                                seed_instrument.model_copy(update={"id": "unused-0"}),
                            ]
                        }
                    )
                }
            )
        }
    )
    provider = _BroadTrackingProvider()
    linked = _linked_program(domain_product_count=0, config=config)

    plan = ExperimentSystem(provider=provider).compile(linked)

    assert plan.resource_claims == (ResourceClaim("source-0"),)
    assert plan.host is not None
    assert plan.host.resource_order == ("source-0",)
    assert set(plan.host.advertised_descriptions) == {"source-0", "unused-0"}


def test_domain_target_instrument_does_not_require_a_local_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(config=_config_with_domain_resources("source-0"))
    compiler = _DomainCompiler("tests.domain-target-instrument")
    calls = _track_bound_resource_ports(monkeypatch)

    plan = ExperimentSystem(domain_compiler=compiler).compile(linked)

    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)
    assert calls == []
    assert compiler.compile_calls == 1
    assert set(plan.resource_claims) == {
        ResourceClaim("source-0"),
        ResourceClaim("tests.domain.target", "target"),
    }


def test_mixed_target_builds_manifests_only_for_local_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(
        state_mode="constant",
    )
    compiler = _DomainCompiler("tests.mixed-resource-target")
    calls = _track_bound_resource_ports(monkeypatch)

    plan = ExperimentSystem(
        provider=TestSignalInstrumentProvider(),
        domain_compiler=compiler,
    ).compile(linked)

    assert calls == [logical_resource_port_id("source")]
    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)
    assert calls == [logical_resource_port_id("source")]


def test_parameter_scan_binding_is_shared_with_domain_inputs() -> None:
    frequency_type = Scalar(QuantityType(unit="GHz"))
    point_type = Table(
        columns=(TableColumn("frequency", frequency_type),),
    )
    bindings = RelationTypeBindings(
        point_row=RowType.from_table(point_type),
    )
    domain_input = ValueInput(
        value=scalar_value_expr(
            parameter_lookup(
                READOUT_FREQUENCY_LOOKUP,
                key={"device_id": "r0"},
            ),
            bindings=bindings,
            expected_type=frequency_type,
        )
    )
    overlay = overlay_parameter_cell(
        "readout_devices",
        row_index=0,
        key={"device_id": "r0"},
        column_id="frequency",
        axis_id="frequency",
    )
    linked = _linked_program(
        domain_input=domain_input,
        parameter_overlays=(overlay,),
        parameter_data=parameter_fixture_data(),
    )
    compiler = _DomainCompiler("tests.parameter-binding")

    plan = ExperimentSystem(domain_compiler=compiler).compile(linked)

    assert plan.host is None
    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)
    [domain_job] = (
        operation for operation in plan.coverage if isinstance(operation, RunDomainJob)
    )
    assert isinstance(domain_job, RunDomainJob)
    assert isinstance(domain_job.execution, PreparedDomainExecution)
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

    plan = system.compile(linked)

    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)
    assert [
        operation.point_ordinals
        for operation in plan.coverage
        if isinstance(operation, RunDomainJob)
    ] == [(0, 1)]
    assert [
        operation.point_index
        for operation in plan.coverage
        if isinstance(operation, RunCoverageEffect)
    ] == [0, 1]
    assert [
        operation.point_index
        for operation in plan.coverage
        if isinstance(operation, RunCoverageCheckpoint)
    ] == [0, 1]
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert compiler.compile_calls == 1
    _assert_no_domain_effects(compiler)


def test_domain_and_local_state_retain_declared_effect_order() -> None:
    linked = _linked_program(
        state_mode="constant",
        domain_before_state=True,
    )
    plan = ExperimentSystem(
        provider=_TrackingProvider(),
        domain_compiler=_DomainCompiler("tests.declared-effect-order"),
    ).compile(linked)

    consequential = tuple(
        operation
        for operation in plan.coverage
        if not isinstance(operation, RunCoverageCheckpoint)
    )

    assert isinstance(consequential[0], RunDomainJob)
    assert isinstance(consequential[1], RunCoverageEffect)
    assert isinstance(consequential[1].operation, ApplyStateOperation)


def test_planning_rejects_local_and_domain_target_instrument_overlap() -> None:
    config = _config_with_domain_resources("source-0")
    linked = _linked_program(
        product_count=2,
        domain_product_count=1,
        config=config,
    )
    compiler = _DomainCompiler("tests.instrument-overlap")

    with pytest.raises(CheckFailed) as captured:
        ExperimentSystem(
            provider=_TrackingProvider(),
            domain_compiler=compiler,
        ).compile(linked)

    assert _problem_codes(captured.value) == {"domain_target_local_instrument_overlap"}
    assert captured.value.problems[0].details == {"instrument_ids": ("source-0",)}
    assert compiler.compile_calls == 0


def test_unused_local_acquisition_does_not_fragment_domain_coverage() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=1,
        record_instrument_products=False,
    )
    compiler = _DomainCompiler("tests.unused-acquisition")
    plan = ExperimentSystem(domain_compiler=compiler).compile(linked)

    [domain] = (
        operation for operation in plan.coverage if isinstance(operation, RunDomainJob)
    )

    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)
    assert domain.point_ordinals == (0, 1)
    assert [request.point_ordinals for request in compiler.compile_requests] == [(0, 1)]


def test_domain_compiler_batches_complete_point_domain() -> None:
    linked = _linked_program(state_mode="constant")
    compiler = _DomainCompiler("tests.constant-peripheral")
    provider = _TrackingProvider()
    system = ExperimentSystem(
        provider=provider,
        domain_compiler=compiler,
    )

    plan = system.compile(linked)
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
        operation for operation in plan.coverage if isinstance(operation, RunDomainJob)
    )
    assert tuple(job.point_ordinals for job in domain_jobs) == ((0, 1),)
    [domain_job] = domain_jobs
    assert isinstance(domain_job.execution, PreparedDomainExecution)
    assert provider.describe_calls == 1
    assert provider.provide_calls == 0
    assert compiler.compile_calls == 1
    assert [job.id for job in domain_jobs] == ["domain:batch-0"]
    _assert_no_domain_effects(compiler)


def test_ordered_domain_calls_share_one_target_resource_and_keep_job_identity() -> None:
    linked = _linked_program(
        product_count=2,
        domain_product_count=2,
        domain_call_count=2,
    )
    compiler = _DomainCompiler("tests.multi-call")

    plan = ExperimentSystem(domain_compiler=compiler).compile(linked)

    jobs = tuple(
        operation for operation in plan.coverage if isinstance(operation, RunDomainJob)
    )
    assert len({job.id for job in jobs}) == 2
    assert plan.resource_claims == (ResourceClaim("tests.domain.target", "target"),)
    assert compiler.compile_calls == 2
    _assert_no_domain_effects(compiler)


def test_system_rejects_a_compiler_for_a_different_target() -> None:
    compiler = _DomainCompiler("tests.target-mismatch")
    config = _config_with_domain_resources()
    mismatched = DomainTargetBinding(id="other.target", kind="tests.domain")
    mismatched_config = config.model_copy(
        update={
            "system": config.system.model_copy(update={"domain_target": mismatched})
        }
    )
    linked = _linked_program(
        product_count=2,
        domain_product_count=2,
        domain_call_count=2,
        config=mismatched_config,
    )

    with pytest.raises(CheckFailed) as captured:
        ExperimentSystem(domain_compiler=compiler).compile(linked)

    assert _problem_codes(captured.value) == {"domain_target_mismatch"}


def test_system_rejects_a_compiler_for_a_different_target_kind() -> None:
    compiler = _DomainCompiler("tests.target-kind-mismatch")
    config = _config_with_domain_resources()
    mismatched = DomainTargetBinding(
        id="tests.domain.target",
        kind="tests.other-domain",
    )
    mismatched_config = config.model_copy(
        update={
            "system": config.system.model_copy(update={"domain_target": mismatched})
        }
    )
    linked = _linked_program(
        product_count=2,
        domain_product_count=2,
        domain_call_count=2,
        config=mismatched_config,
    )

    with pytest.raises(CheckFailed) as captured:
        ExperimentSystem(domain_compiler=compiler).compile(linked)

    assert _problem_codes(captured.value) == {"domain_target_kind_mismatch"}


def test_point_inventory_and_domain_compilation_close_before_program_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = _linked_program(domain_input=_point_frequency_domain_input())
    events: list[str] = []
    compiler = _DomainCompiler("tests.symbolic-first", events=events)
    original_materialize = cast(
        "Callable[[LinkedPlan], MaterializedLinkedPoints]",
        planning_system.__dict__["materialize_linked_points"],
    )

    def track_materialization(
        selected: LinkedPlan,
    ) -> MaterializedLinkedPoints:
        events.append("materialize")
        return original_materialize(selected)

    monkeypatch.setattr(
        planning_system,
        "materialize_linked_points",
        track_materialization,
    )

    plan = ExperimentSystem(domain_compiler=compiler).compile(linked)

    assert events == ["materialize", "compile"]
    assert isinstance(plan.coverage, tuple)
    first_inspection = tuple(plan.coverage)
    second_inspection = tuple(plan.coverage)
    assert first_inspection == second_inspection
    assert tuple(point.ordinal for point in plan.points.points) == (0, 1)


def test_complete_point_materialization_does_not_evaluate_domain_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_domain_inputs(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError("point materialization must not evaluate domain inputs")

    monkeypatch.setattr(
        linking,
        "_materialize_domain_execution_input",
        reject_domain_inputs,
    )
    linked_points = materialize_linked_points(
        _linked_program(domain_input=_point_frequency_domain_input())
    )

    assert len(linked_points.point_domain.points) == 2


def test_mixed_plan_preview_combines_domain_records_with_local_runtime() -> None:
    linked = _linked_program(state_mode="constant")
    compiler = _DomainCompiler("tests.preview-domain")
    provider = _TrackingProvider()
    plan = ExperimentSystem(
        provider=provider,
        domain_compiler=compiler,
    ).compile(linked)

    assert [record.id for record in plan.measurements.records] == ["record-0"]
    local_effects = plan.host
    assert local_effects is not None
    assert any(
        operation.operation
        for operation in plan.coverage
        if isinstance(operation, RunCoverageEffect)
        and isinstance(operation.operation, ApplyStateOperation)
    )
    _assert_no_domain_effects(compiler)


def test_zero_point_domain_plan_retains_direct_product_ownership() -> None:
    linked = _linked_program(point_count=0)
    compiler = _DomainCompiler("tests.zero-point")

    plan = ExperimentSystem(domain_compiler=compiler).compile(linked)
    assert tuple(plan.coverage) == ()
    assert plan.measurements.catalog.product_use_ids == tuple(
        use.id for use in linked.program.product_uses
    )
    assert compiler.compile_calls == 0
    assert plan.points.points == ()

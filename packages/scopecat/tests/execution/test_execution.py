from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import cast, override

import pytest
from pydantic import JsonValue

from scopecat.adapters.sqlite import SQLiteRunRepository
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    LogicalResourceRequirement,
    TypedComputeNode,
    ValueInput,
    core_acquisitions,
    record_product,
    set_state_field,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.evidence import (
    instrument_state_evidence_ref,
)
from scopecat.execution.local.program import CollectOperation
from scopecat.execution.program import RunHostBinding
from scopecat.graph.relations.model import (
    lit,
    point_col,
)
from scopecat.graph.relations.point_domain import point_axis_values, point_product
from scopecat.graph.values import (
    ComputeOutput,
    OperationId,
    operation_result_id,
)
from scopecat.kernel.errors import ProviderContractError
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Payload, Scalar, String, TableColumn
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Table as TableType
from scopecat.planning.provider_binding import (
    preflight_instrument_provider,
    validate_run_host_binding,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.instrument import (
    CommandChannelBinding,
    InstrumentReadback,
    InstrumentStateField,
    InstrumentStateSnapshot,
)
from scopecat.records.run import RunManifest
from scopecat.runs.access import dataset_storage_ref
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments.contracts import (
    CapabilityDescription,
    CapabilityField,
    CollectAxisRequest,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    product_axis,
)
from tests.testkit.execution import execute_bound_run
from tests.testkit.instrument_drivers import SignalInstrumentDriver
from tests.testkit.local_materialization import (
    LocalEffectInspection,
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.materialized_effects import config_with_physical_resources
from tests.testkit.records import (
    assert_model_round_trip,
)
from tests.testkit.relation_plans import (
    scalar_value_expr,
    value_expr,
)
from tests.testkit.runtime import (
    sqlite_execution_session,
    sqlite_run_repository,
)
from tests.testkit.signal_instruments import (
    TestSignalInstrument,
)
from tests.testkit.typed_program import (
    compute_result,
    instrument_acquisition,
    link_program,
    observable_product,
    typed_program,
)
from tests.testkit.workflow_fixtures import load_config, load_experiment


def test_execution_builds_one_bound_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_count = 0

    def counted_session(
        project_root: str | Path,
        run_id: str,
        *,
        runs: SQLiteRunRepository | None = None,
    ):
        nonlocal session_count
        session_count += 1
        return sqlite_execution_session(project_root, run_id, runs=runs)

    monkeypatch.setattr(
        "tests.testkit.execution.sqlite_execution_session",
        counted_session,
    )

    execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        project_root=tmp_path,
    )

    assert session_count == 1


def test_instrument_models_round_trip() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="test.instrument",
        implementation_version="v1",
        capabilities=[
            CapabilityDescription(
                id="set_frequency",
                fields=[
                    CapabilityField(
                        id="frequency",
                        value_type=Scalar(QuantityType(unit="GHz")),
                    )
                ],
            )
        ],
    )
    state_value = StateValue(Quantity(value=5.0, unit="GHz"))
    state = InstrumentStateSnapshot(
        instrument_id="source-0",
        fields=[
            InstrumentStateField(
                capability_id="set_frequency",
                field_path="frequency",
                value=state_value,
            )
        ],
    )
    command = InstrumentStateCommand(
        instrument_id="source-0",
        fields=[
            InstrumentStateCommandField(
                resource_id="source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=state_value,
                entity_ids=["q0"],
                channel_bindings=[
                    CommandChannelBinding(
                        entity_id="q0",
                        channel_id="drive.awg0.ch1",
                        capability="set_frequency",
                    )
                ],
            )
        ],
    )

    assert_model_round_trip(
        description,
    )
    assert_model_round_trip(
        state,
    )
    assert_model_round_trip(
        command,
    )


def test_instrument_state_snapshot_rejects_non_durable_metadata() -> None:
    with pytest.raises(ValueError, match="valid JSON value"):
        InstrumentStateSnapshot(
            instrument_id="source-0",
            metadata={"opaque": cast("JsonValue", object())},
        )


def test_run_persists_measurements_and_run_files(
    tmp_path: Path,
) -> None:
    config = load_config()
    manifest = execute_bound_run(
        config=config,
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        project_root=tmp_path,
    )

    repository = sqlite_run_repository(tmp_path)
    assert manifest.status == "completed"
    assert {record.id for record in manifest.records} == {"instrument-state-evidence"}
    assert {dataset.id for dataset in manifest.datasets} == {"raw-measurements"}
    raw_dataset = manifest.datasets[0]
    assert raw_dataset.kind == "measurement_dataset"
    persisted_manifest = repository.read_manifest(manifest.run_id)
    persisted_config = repository.read_config_profile_snapshot(manifest.run_id)
    state_evidence = repository.read_model(
        manifest.run_id,
        instrument_state_evidence_ref(),
        InstrumentStateEvidence,
    )
    assert persisted_manifest == manifest
    assert persisted_config == config
    assert {
        snapshot.instrument_id
        for snapshot in [*state_evidence.initial_state, *state_evidence.final_state]
    } == {"source-0"}
    final_state_value = state_evidence.final_state[0].fields[0].value.root
    assert final_state_value == Quantity(value=5.1, unit="GHz")
    persisted_state_evidence = state_evidence.model_dump(mode="json")
    assert persisted_state_evidence["final_state"][0]["fields"][0]["value"] == {
        "value": 5.1,
        "unit": "GHz",
    }
    assert not repository.exists(manifest.run_id, "experiment-plan.json")
    assert not repository.exists(
        manifest.run_id,
        "records/device_program/device-program.json",
    )

    measurements = sqlite_run_repository(tmp_path).read_measurement_records(
        manifest.run_id,
        dataset_storage_ref(raw_dataset),
    )
    assert [item.point_index for item in measurements] == [0, 1, 2]
    drive_frequencies: list[float] = []
    for item in measurements:
        drive_frequency = item.coordinates["drive_frequency"]
        assert isinstance(drive_frequency, Quantity)
        drive_frequencies.append(drive_frequency.value)
    assert drive_frequencies == [
        4.9,
        5.0,
        5.1,
    ]
    signal_values: list[float] = []
    for measurement in measurements:
        signal = measurement.observables["signal"]
        assert isinstance(signal, Quantity)
        signal_values.append(signal.value)
    assert signal_values == [
        0.5,
        1.0,
        0.5,
    ]


def test_terminal_commit_does_not_publish_manifest_after_content_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_ref = instrument_state_evidence_ref()

    def fail_terminal_commit(
        _storage: SQLiteRunRepository,
        _commit: TerminalRunCommit,
    ) -> RunManifest:
        raise OSError("injected terminal persistence failure")

    monkeypatch.setattr(
        SQLiteRunRepository,
        "commit_terminal",
        fail_terminal_commit,
    )

    with pytest.raises(OSError, match="injected terminal persistence"):
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[TestSignalInstrument()],
            project_root=tmp_path,
        )

    storage = sqlite_run_repository(tmp_path)
    manifest = storage.list_runs()[0]
    assert manifest.outcome is None
    assert not storage.exists(manifest.run_id, pending_ref)


class _NonFiniteSignalInstrument(TestSignalInstrument):
    @override
    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_commands.append(command)
        values = (float("nan"), float("inf"), float("-inf"))
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    "signal": Quantity(
                        value=values[command.point_index],
                        unit="ratio",
                    )
                },
                metadata={"encoding": "ieee-754"},
            )
        )


def test_run_round_trips_non_finite_terminal_measurements(
    tmp_path: Path,
) -> None:
    manifest = execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[_NonFiniteSignalInstrument()],
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    repository = sqlite_run_repository(tmp_path)
    dataset_ref = dataset_storage_ref(manifest.datasets[0])
    wire = "".join(
        repository.read_text(
            manifest.run_id,
            f"{dataset_ref}/chunks/{index:020d}.json",
        )
        for index in range(3)
    )
    assert "NaN" in wire
    assert "Infinity" in wire
    assert "-Infinity" in wire
    measurements = sqlite_run_repository(tmp_path).read_measurement_records(
        manifest.run_id,
        dataset_storage_ref(manifest.datasets[0]),
    )
    values = [
        cast("Quantity", measurement.observables["signal"]).value
        for measurement in measurements
    ]
    assert math.isnan(values[0])
    assert values[1:] == [float("inf"), float("-inf")]


class _OrderedAbiProblemProvider:
    provider_id = "tests.ordered_abi_provider"

    def __init__(self) -> None:
        self.provide_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        source_description = TestSignalInstrument().describe()
        source_description = source_description.model_copy(
            update={
                "capabilities": [
                    capability
                    for capability in source_description.capabilities
                    if capability.id != "scalar_signal"
                ]
            }
        )
        unknown_description = (
            TestSignalInstrument()
            .describe()
            .model_copy(update={"instrument_id": "not-in-config"})
        )
        return InstrumentProviderDescription(
            provider_id="tests.different_provider_id",
            instruments=(source_description, unknown_description),
            problems=(
                Problem(
                    code="provider_abi_warning",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    message="provider ABI warning",
                    location=model_location("instrument_provider", "description"),
                ),
            ),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        self.provide_called = True
        return InstrumentProviderResult(drivers=())


class _PartialDescriptionProvider:
    provider_id = "tests.partial_description_provider"

    def __init__(self) -> None:
        self.provide_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        description = (
            TestSignalInstrument()
            .describe()
            .model_copy(update={"instrument_id": "not-in-config"})
        )
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(description,),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        self.provide_called = True
        return InstrumentProviderResult(drivers=())


class _FailingDescriptionProvider:
    provider_id = "tests.failing_description_provider"

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.provide_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        raise self.error

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        self.provide_called = True
        return InstrumentProviderResult(drivers=())


class _UnitAbiProvider:
    provider_id = "tests.unit_abi_provider"

    def __init__(
        self,
        *,
        product_unit: str | None,
        axis_unit: str | None = None,
        include_axis: bool = False,
    ) -> None:
        self.product_unit = product_unit
        self.axis_unit = axis_unit
        self.include_axis = include_axis
        self.provide_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        description = TestSignalInstrument().describe()
        capabilities: list[CapabilityDescription] = []
        for capability in description.capabilities:
            if capability.id != "scalar_signal":
                capabilities.append(capability)
                continue
            advertised_product = capability.products[0].model_copy(
                update={
                    "unit": self.product_unit,
                    "axes": (
                        [
                            product_axis(
                                "sample",
                                kind="sample",
                                size=2,
                                unit=self.axis_unit,
                            )
                        ]
                        if self.include_axis
                        else []
                    ),
                }
            )
            capabilities.append(
                capability.model_copy(update={"products": [advertised_product]})
            )
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(
                description.model_copy(update={"capabilities": capabilities}),
            ),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        self.provide_called = True
        return InstrumentProviderResult(drivers=())


def _lower_test_host_binding(
    plan: LocalEffectInspection,
    config: ConfigProfileSnapshot,
    provider: InstrumentProvider,
    *,
    planning_problems: tuple[Problem, ...] = (),
):
    preflight = preflight_instrument_provider(
        config=config,
        instrument_provider=provider,
    )
    program = RunHostBinding(
        resource_order=plan.resource_order,
        provider_id=preflight.provider_id,
        advertised_descriptions=preflight.advertised_descriptions,
    )
    return validate_run_host_binding(
        host=program,
        preamble_operations=plan.preamble_operations,
        effect_blocks=(tuple(effect.operation for effect in plan.effects),),
        problems=(*planning_problems, *preflight.problems),
    )


def test_provider_abi_problems_are_aggregated_in_stable_order_before_run(
    tmp_path: Path,
) -> None:
    provider = _OrderedAbiProblemProvider()
    config = load_config()
    plan = materialize_local_execution(
        link_program(load_experiment(), build_config_environment(config))
    )
    plan = _first_point_plan(plan)
    planning_problems = (
        Problem(
            code="plan_warning",
            phase=ProblemPhase.PLANNING,
            message="materialized local semantics warning",
            location=model_location("materialized_effects"),
        ),
    )

    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(
            plan,
            config,
            provider,
            planning_problems=planning_problems,
        )

    assert [problem.code for problem in captured.value.problems] == [
        "plan_warning",
        "provider_abi_warning",
        "instrument_provider_id_mismatch",
        "instrument_not_in_config",
        "instrument_product_unsupported",
    ]
    assert not provider.provide_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def test_partial_provider_description_reports_missing_bound_instrument_before_run(
    tmp_path: Path,
) -> None:
    provider = _PartialDescriptionProvider()
    config = load_config()
    plan = materialize_local_execution(
        link_program(load_experiment(), build_config_environment(config))
    )

    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(plan, config, provider)

    assert [problem.code for problem in captured.value.problems] == [
        "instrument_not_in_config",
        "missing_instrument_description",
    ]
    assert not provider.provide_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def test_provider_description_exception_fails_at_preflight_boundary(
    tmp_path: Path,
) -> None:
    failure = RuntimeError("description unavailable")
    provider = _FailingDescriptionProvider(failure)
    config = load_config()
    plan = materialize_local_execution(
        link_program(load_experiment(), build_config_environment(config))
    )
    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(plan, config, provider)

    assert [problem.code for problem in captured.value.problems] == [
        "instrument_provider_description_failed"
    ]
    assert captured.value.__cause__ is failure
    assert not provider.provide_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


@pytest.mark.parametrize("advertised_unit", [None, "GHz"])
def test_provider_product_unit_mismatch_is_rejected_before_run(
    tmp_path: Path,
    advertised_unit: str | None,
) -> None:
    provider = _UnitAbiProvider(product_unit=advertised_unit)
    config = load_config()
    plan = materialize_local_execution(
        link_program(load_experiment(), build_config_environment(config))
    )
    plan = _first_point_plan(plan)

    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(plan, config, provider)

    problem = captured.value.problems[0]
    assert len(captured.value.problems) == 1
    assert problem.code == "instrument_product_unit_mismatch"
    assert problem.location == model_location(
        "execution_program",
        "operations",
        operations_of_type(plan, CollectOperation, point_index=0)[0].operation_id,
        "requests",
        "signal",
        "unit",
    )
    assert not provider.provide_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


@pytest.mark.parametrize("advertised_unit", [None, "GHz"])
def test_provider_product_axis_unit_mismatch_is_rejected_before_run(
    tmp_path: Path,
    advertised_unit: str | None,
) -> None:
    provider = _UnitAbiProvider(
        product_unit="ratio",
        axis_unit=advertised_unit,
        include_axis=True,
    )
    config = load_config()
    environment = build_config_environment(config)
    experiment = load_experiment()
    plan = materialize_local_execution(link_program(experiment, environment))
    plan = _first_point_plan(plan)
    collect = operations_of_type(plan, CollectOperation, point_index=0)[0]
    request = collect.command.requests[0].model_copy(
        update={
            "dimensions": [
                CollectAxisRequest(id="sample", kind="sample", size=2, unit="ns")
            ]
        }
    )
    updated_collect = replace(
        collect,
        command=collect.command.model_copy(update={"requests": [request]}),
    )
    effects = tuple(
        replace(effect, operation=updated_collect)
        if effect.operation is collect
        else effect
        for effect in plan.effects
    )
    plan = replace(plan, effects=effects)

    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(plan, config, provider)

    problem = captured.value.problems[0]
    assert len(captured.value.problems) == 1
    assert problem.code == "instrument_product_axis_unit_mismatch"
    assert problem.location == model_location(
        "execution_program",
        "operations",
        updated_collect.operation_id,
        "requests",
        "signal",
        "axes",
        0,
        "unit",
    )
    assert not provider.provide_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def _first_point_plan(
    plan: LocalEffectInspection,
) -> LocalEffectInspection:
    return replace(
        plan,
        points=plan.points[:1],
        effects=tuple(
            replace(effect, point_indices=(0,))
            for effect in plan.effects
            if 0 in effect.point_indices
        ),
    )


def test_provider_description_interruption_precedes_run_acceptance(
    tmp_path: Path,
) -> None:
    provider = _FailingDescriptionProvider(KeyboardInterrupt("description cancelled"))
    config = load_config()
    plan = materialize_local_execution(
        link_program(load_experiment(), build_config_environment(config))
    )

    with pytest.raises(KeyboardInterrupt, match="description cancelled"):
        _lower_test_host_binding(plan, config, provider)

    assert not provider.provide_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def test_run_shares_identical_residual_point_compute(tmp_path: Path) -> None:
    calls: list[Quantity] = []

    def build_program(*, value: object) -> dict[str, object]:
        assert isinstance(value, Quantity)
        calls.append(value)
        return {"value": value}

    operation_id = OperationId(SymbolId(local_id="build-program"))
    result_id = operation_result_id(operation_id)
    slow_axis_type = TableType(
        columns=(TableColumn("frequency", Scalar(QuantityType())),),
    )
    fast_axis_type = TableType(
        columns=(TableColumn("amplitude", Scalar(String())),),
    )
    point_type = TableType(
        columns=(*slow_axis_type.columns, *fast_axis_type.columns),
    )
    product = observable_product("signal")
    acquisition = instrument_acquisition(
        product,
        resource_port_id="source",
        capability="scalar_signal",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="cached-compute-run",
        kind="cached_compute",
        point_domain=PointDomain(
            root=point_product(
                point_axis_values(
                    "frequency",
                    slow_axis_type.columns[0].value_type,
                    (
                        Quantity(value=4.9, unit="GHz"),
                        Quantity(value=5.1, unit="GHz"),
                    ),
                ),
                point_axis_values(
                    "amplitude",
                    fast_axis_type.columns[0].value_type,
                    ("low", "medium", "high"),
                ),
            ),
        ),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("play_program", "scalar_signal"),
            ),
        ),
        state=[
            set_state_field(
                resource_port_id=logical_resource_port_id("source"),
                capability_id="play_program",
                field_path="program",
                value=compute_result("build-program"),
            )
        ],
        product_defs=[product],
        instrument_acquisitions=[acquisition],
        product_uses=[product_use],
        record_uses=[record_use],
        compute_nodes=[
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                implementation=LocalPythonImplementation(
                    id=ImplementationId("python.build-program.v1"),
                    kernel=build_program,
                ),
                result=ComputeOutput(
                    id=result_id,
                    value_type=Scalar(Payload("pulse_program")),
                ),
                inputs={
                    "value": ValueInput(
                        value=value_expr(
                            point_col("frequency"),
                            expected_type=Scalar(QuantityType()),
                            bindings=RelationTypeBindings(
                                point_row=RowType.from_table(point_type)
                            ),
                        ),
                    )
                },
            )
        ],
    )
    config = config_with_physical_resources(
        {"source-0": ("play_program", "scalar_signal")}
    )
    instrument = SignalInstrumentDriver()
    manifest = execute_bound_run(
        config=config,
        experiment=spec,
        instruments=[instrument],
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert calls == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert len(instrument.applied) == 2
    assert all(
        transition.stage != "compute"
        for transition in sqlite_execution_session(
            tmp_path,
            manifest.run_id,
        ).journal.entries()
    )
    payloads = [next(iter(command.payloads.values())) for command in instrument.applied]
    payload_ids = [payload.id for payload in payloads]
    assert payload_ids[1] != payload_ids[0]
    assert all(
        payload_id.startswith(f"{result_id.qualified_name}.payload.")
        for payload_id in payload_ids
    )
    assert {payload.semantic_operation_id for payload in payloads} == {"build-program"}
    assert [payload.implementation_id for payload in payloads] == [
        "python.build-program.v1"
    ] * 2
    assert [payload.payload for payload in payloads] == [
        {"value": Quantity(value=4.9, unit="GHz")},
        {"value": Quantity(value=5.1, unit="GHz")},
    ]


def test_run_skips_unchanged_state_fields(tmp_path: Path) -> None:
    instrument = TestSignalInstrument()
    base_experiment = load_experiment()
    experiment = replace(
        base_experiment,
        effects=(
            set_state_field(
                resource_port_id=logical_resource_port_id("source"),
                capability_id="set_frequency",
                field_path="frequency",
                value=scalar_value_expr(
                    lit(Quantity(value=5.9, unit="GHz")),
                    expected_type=Scalar(QuantityType(unit="GHz")),
                ),
            ),
            *core_acquisitions(base_experiment),
        ),
    )
    manifest = execute_bound_run(
        config=load_config(),
        experiment=experiment,
        instruments=[instrument],
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert len(instrument.applied_commands) == 1

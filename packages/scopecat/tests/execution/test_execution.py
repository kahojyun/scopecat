from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Never, cast

import pytest
from pydantic import JsonValue

from scopecat.adapters.sqlite import SQLiteRunRepository
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    LogicalResourceRequirement,
    TypedComputeNode,
    ValueInput,
    bound_acquisitions,
    record_product,
    set_state_property,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.evidence import (
    instrument_state_evidence_ref,
)
from scopecat.execution.local.program import CollectOperation
from scopecat.execution.ports.instruments import RunInstrumentHost
from scopecat.execution.program import RunHostBinding
from scopecat.graph.relations.model import (
    lit,
    point_col,
)
from scopecat.graph.relations.point_domain import point_axis_values
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
    resolve_instrument_contract_catalog,
    validate_run_host_binding,
)
from scopecat.program.logical import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.instrument import (
    CommandChannelBinding,
    InstrumentPropertyState,
    InstrumentStateSnapshot,
)
from scopecat.records.measurement import MeasurementScalar
from scopecat.records.run import RunManifest
from scopecat.runs.access import dataset_storage_ref
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments import DriverPayload
from scopecat.sdk.instruments.commands import (
    CollectAxisRequest,
    InstrumentStateAssignment,
    InstrumentStateCommand,
)
from scopecat.sdk.instruments.contracts import (
    FixedAcquisitionSpec,
    InstrumentDescription,
    InterfaceSpec,
    PropertySpec,
    acquisition_axis,
)
from scopecat.sdk.instruments.provider import (
    InstrumentConnectionContext,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from tests.testkit.execution import execute_bound_run
from tests.testkit.instrument_drivers import SignalInstrumentDriver
from tests.testkit.local_materialization import (
    LocalEffectInspection,
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.materialized_effects import config_with_physical_resources
from tests.testkit.payload_codecs import json_payload_codecs
from tests.testkit.records import (
    assert_model_round_trip,
)
from tests.testkit.relation_plans import scalar_value_expr
from tests.testkit.runtime import (
    sqlite_execution_session,
    sqlite_run_repository,
)
from tests.testkit.signal_instruments import (
    TestSignalInstrument,
)
from tests.testkit.typed_program import (
    bind_program_facts,
    compute_result,
    instrument_acquisition,
    instrument_invocation,
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
        instruments: RunInstrumentHost | None = None,
    ):
        nonlocal session_count
        session_count += 1
        return sqlite_execution_session(
            project_root,
            run_id,
            runs=runs,
            instruments=instruments,
        )

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
        interfaces=[
            InterfaceSpec(
                id="test.set_frequency/v1",
                properties=[
                    PropertySpec(
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
        properties=[
            InstrumentPropertyState(
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=state_value,
            )
        ],
    )
    command = InstrumentStateCommand(
        command_id="round-trip-state",
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=state_value,
                entity_ids=["q0"],
                channel_bindings=[
                    CommandChannelBinding(
                        entity_id="q0",
                        channel_id="drive.awg0.ch1",
                        interface_id="test.set_frequency/v1",
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
        for snapshot in [
            *state_evidence.observed_state,
            *state_evidence.prepared_state,
            *state_evidence.final_state,
        ]
    } == {"source-0"}
    assert state_evidence.observed_state == state_evidence.prepared_state
    final_state_value = state_evidence.final_state[0].properties[0].value.root
    assert final_state_value == Quantity(value=5.1, unit="GHz")
    persisted_state_evidence = state_evidence.model_dump(mode="json")
    assert persisted_state_evidence["final_state"][0]["properties"][0]["value"] == {
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
        assert isinstance(drive_frequency, MeasurementScalar)
        assert not isinstance(drive_frequency.value, bool)
        assert isinstance(drive_frequency.value, int | float)
        drive_frequencies.append(float(drive_frequency.value))
    assert drive_frequencies == [
        4.9,
        5.0,
        5.1,
    ]
    signal_values: list[float] = []
    for measurement in measurements:
        signal = measurement.observables["signal"]
        assert isinstance(signal, MeasurementScalar)
        assert not isinstance(signal.value, bool)
        assert isinstance(signal.value, int | float)
        signal_values.append(float(signal.value))
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


class _OrderedAbiProblemProvider:
    provider_id = "tests.ordered_abi_provider"

    def __init__(self) -> None:
        self.connect_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        source_description = TestSignalInstrument().describe()
        source_description = source_description.model_copy(
            update={
                "interfaces": [
                    interface
                    for interface in source_description.interfaces
                    if interface.id != "test.scalar_signal/v1"
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

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> Never:
        del context
        self.connect_called = True
        raise AssertionError("preflight must not connect an instrument")


class _PartialDescriptionProvider:
    provider_id = "tests.partial_description_provider"

    def __init__(self) -> None:
        self.connect_called = False

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

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> Never:
        del context
        self.connect_called = True
        raise AssertionError("preflight must not connect an instrument")


class _FailingDescriptionProvider:
    provider_id = "tests.failing_description_provider"

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.connect_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        raise self.error

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> Never:
        del context
        self.connect_called = True
        raise AssertionError("preflight must not connect an instrument")


class _UnitAbiProvider:
    provider_id = "tests.unit_abi_provider"

    def __init__(
        self,
        *,
        result_unit: str | None,
        axis_unit: str | None = None,
        include_axis: bool = False,
    ) -> None:
        self.result_unit = result_unit
        self.axis_unit = axis_unit
        self.include_axis = include_axis
        self.connect_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        description = TestSignalInstrument().describe()
        interfaces: list[InterfaceSpec] = []
        for interface in description.interfaces:
            if interface.id != "test.scalar_signal/v1":
                interfaces.append(interface)
                continue
            acquisition = interface.acquisitions[0]
            assert isinstance(acquisition, FixedAcquisitionSpec)
            advertised_result = acquisition.results[0].model_copy(
                update={
                    "unit": self.result_unit,
                    "axes": (
                        [
                            acquisition_axis(
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
            interfaces.append(
                interface.model_copy(
                    update={
                        "acquisitions": [
                            acquisition.model_copy(
                                update={"results": [advertised_result]}
                            )
                        ]
                    }
                )
            )
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(description.model_copy(update={"interfaces": interfaces}),),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> Never:
        del context
        self.connect_called = True
        raise AssertionError("preflight must not connect an instrument")


def _lower_test_host_binding(
    plan: LocalEffectInspection,
    config: ConfigProfileSnapshot,
    provider: InstrumentProvider,
    *,
    planning_problems: tuple[Problem, ...] = (),
):
    catalog = resolve_instrument_contract_catalog(
        config=config,
        provider_id=provider.provider_id,
        describe=provider.describe,
    )
    if catalog.problems and not catalog.instruments:
        raise ProviderContractError((*planning_problems, *catalog.problems))
    provider_id = catalog.provider_id
    if provider_id is None:
        raise AssertionError("provider resolution must retain its identity")
    program = RunHostBinding(
        resource_order=plan.resource_order,
        provider_id=provider_id,
        advertised_descriptions={
            description.instrument_id: description
            for description in catalog.instruments
        },
    )
    return validate_run_host_binding(
        host=program,
        effect_blocks=(tuple(effect.operation for effect in plan.effects),),
        problems=(*planning_problems, *catalog.problems),
    )


def test_provider_abi_problems_are_aggregated_in_stable_order_before_run(
    tmp_path: Path,
) -> None:
    provider = _OrderedAbiProblemProvider()
    config = load_config()
    plan = materialize_local_execution(
        bind_program_facts(load_experiment(), build_config_environment(config))
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
        "instrument_acquisition_result_unsupported",
    ]
    assert not provider.connect_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def test_partial_provider_description_reports_missing_bound_instrument_before_run(
    tmp_path: Path,
) -> None:
    provider = _PartialDescriptionProvider()
    config = load_config()
    plan = materialize_local_execution(
        bind_program_facts(load_experiment(), build_config_environment(config))
    )

    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(plan, config, provider)

    assert [problem.code for problem in captured.value.problems] == [
        "instrument_not_in_config",
        "missing_instrument_description",
    ]
    assert not provider.connect_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def test_provider_description_exception_fails_at_preflight_boundary(
    tmp_path: Path,
) -> None:
    failure = RuntimeError("description unavailable")
    provider = _FailingDescriptionProvider(failure)
    config = load_config()
    plan = materialize_local_execution(
        bind_program_facts(load_experiment(), build_config_environment(config))
    )
    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(plan, config, provider)

    assert [problem.code for problem in captured.value.problems] == [
        "instrument_provider_description_failed"
    ]
    assert captured.value.__cause__ is None
    assert not provider.connect_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


@pytest.mark.parametrize("advertised_unit", [None, "GHz"])
def test_provider_acquisition_result_unit_mismatch_is_rejected_before_run(
    tmp_path: Path,
    advertised_unit: str | None,
) -> None:
    provider = _UnitAbiProvider(result_unit=advertised_unit)
    config = load_config()
    plan = materialize_local_execution(
        bind_program_facts(load_experiment(), build_config_environment(config))
    )
    plan = _first_point_plan(plan)

    with pytest.raises(ProviderContractError) as captured:
        _lower_test_host_binding(plan, config, provider)

    problem = captured.value.problems[0]
    assert len(captured.value.problems) == 1
    assert problem.code == "instrument_acquisition_result_unit_mismatch"
    assert problem.location == model_location(
        "execution_program",
        "operations",
        operations_of_type(plan, CollectOperation, point_index=0)[0].operation_id,
        "requests",
        "signal",
        "unit",
    )
    assert not provider.connect_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


@pytest.mark.parametrize("advertised_unit", [None, "GHz"])
def test_provider_acquisition_axis_unit_mismatch_is_rejected_before_run(
    tmp_path: Path,
    advertised_unit: str | None,
) -> None:
    provider = _UnitAbiProvider(
        result_unit="ratio",
        axis_unit=advertised_unit,
        include_axis=True,
    )
    config = load_config()
    environment = build_config_environment(config)
    experiment = load_experiment()
    plan = materialize_local_execution(bind_program_facts(experiment, environment))
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
    assert problem.code == "instrument_acquisition_result_axis_unit_mismatch"
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
    assert not provider.connect_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def _first_point_plan(
    plan: LocalEffectInspection,
) -> LocalEffectInspection:
    return replace(
        plan,
        points=plan.points[:1],
        effects=tuple(effect for effect in plan.effects if effect.point_index == 0),
    )


def test_provider_description_interruption_precedes_run_acceptance(
    tmp_path: Path,
) -> None:
    provider = _FailingDescriptionProvider(KeyboardInterrupt("description cancelled"))
    config = load_config()
    plan = materialize_local_execution(
        bind_program_facts(load_experiment(), build_config_environment(config))
    )

    with pytest.raises(KeyboardInterrupt, match="description cancelled"):
        _lower_test_host_binding(plan, config, provider)

    assert not provider.connect_called
    assert sqlite_run_repository(tmp_path).list_runs() == []


def test_run_evaluates_residual_compute_per_point(tmp_path: Path) -> None:
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
        interface="test.scalar_signal/v1",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        point_domain=PointDomain(
            axes=(
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
                interfaces=("test.play_program/v1", "test.scalar_signal/v1"),
            ),
        ),
        invocations=[
            instrument_invocation(
                id="play-program",
                resource_port_id=logical_resource_port_id("source"),
                interface="test.play_program/v1",
                operation="play",
                arguments={"program": compute_result("build-program")},
            )
        ],
        product_defs=[product],
        instrument_acquisitions=[acquisition],
        product_uses=[product_use],
        record_uses=[record_use],
        compute_nodes=[
            TypedComputeNode(
                id=operation_id,
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
                        value=scalar_value_expr(
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
        {"source-0": ("test.play_program/v1", "test.scalar_signal/v1")}
    )
    instrument = SignalInstrumentDriver()
    payload_codecs = json_payload_codecs("pulse_program")
    manifest = execute_bound_run(
        config=config,
        experiment=spec,
        instruments=[instrument],
        project_root=tmp_path,
        payload_codecs=payload_codecs,
    )

    assert manifest.status == "completed"
    assert calls == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert len(instrument.invoked) == 6
    assert all(
        transition.stage != "compute"
        for transition in sqlite_execution_session(
            tmp_path,
            manifest.run_id,
        ).journal.entries()
    )
    arguments: list[DriverPayload] = []
    for command in instrument.invoked:
        [argument] = command.arguments.values()
        assert isinstance(argument, DriverPayload)
        arguments.append(argument)
    assert [argument.schema_id for argument in arguments] == ["pulse_program"] * 6
    assert [argument.value for argument in arguments] == [
        {"value": {"value": 4.9, "unit": "GHz"}},
        {"value": {"value": 4.9, "unit": "GHz"}},
        {"value": {"value": 4.9, "unit": "GHz"}},
        {"value": {"value": 5.1, "unit": "GHz"}},
        {"value": {"value": 5.1, "unit": "GHz"}},
        {"value": {"value": 5.1, "unit": "GHz"}},
    ]


def test_run_skips_unchanged_state_properties(tmp_path: Path) -> None:
    instrument = TestSignalInstrument()
    base_experiment = load_experiment()
    experiment = replace(
        base_experiment,
        effects=(
            set_state_property(
                resource_port_id=base_experiment.resource_requirements[0].port_id,
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=scalar_value_expr(
                    lit(Quantity(value=5.9, unit="GHz")),
                    expected_type=Scalar(QuantityType(unit="GHz")),
                ),
            ),
            *bound_acquisitions(base_experiment),
        ),
    )
    manifest = execute_bound_run(
        config=load_config(),
        experiment=experiment,
        instruments=[instrument],
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert len(instrument.applied_requests) == 1

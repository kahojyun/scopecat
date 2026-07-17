from __future__ import annotations

import json
import math
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast, override

import pytest
from pydantic import BaseModel, JsonValue

from scopecat.adapters.filesystem.execution import FilesystemExecutionJournal
from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.bound import BoundAxis, BoundPlan
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.linking.product_realizations import (
    select_local_product_realizations,
)
from scopecat.compiler.relations.model import (
    lit,
    literal_rows,
    point_col,
)
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.availability import (
    ValueAvailability,
    ValueRate,
    ValueStage,
)
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import ProductAxisDef
from scopecat.compiler.typed.program import (
    TypedComputeNode,
    TypedComputeOutput,
    ValueInput,
    record_product,
    set_state_field,
)
from scopecat.composition.local import (
    local_run_repository,
    local_workspace_services,
)
from scopecat.execution.evidence import (
    instrument_state_evidence_ref,
    run_outcome_ref,
)
from scopecat.execution.local.executor import prepare_execution
from scopecat.execution.local.program import ResourceClaim
from scopecat.execution.observation import (
    RunFinishedEvent,
    RuntimeEvent,
    RuntimePayloadObservation,
    RuntimeTransitionEvent,
)
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import ProviderContractError, RunFailed, RunPersistenceError
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Payload, Scalar, String, TableColumn
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Table as TableType
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.instrument import (
    CommandChannelBinding,
    InstrumentReadback,
    InstrumentStateField,
    InstrumentStateSnapshot,
)
from scopecat.records.parameter import Quantity
from scopecat.records.run import RunManifest
from scopecat.runs.access import dataset_storage_ref
from scopecat.runs.execution import inspect_run_execution
from scopecat.sdk.instruments.contracts import (
    CapabilityDescription,
    CapabilityField,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    product_axis,
)
from tests.testkit.bound_plan import config_with_physical_resources
from tests.testkit.execution import execute_bound_run, execute_program_run
from tests.testkit.instrument_drivers import SignalInstrumentDriver
from tests.testkit.records import (
    assert_model_round_trip,
    read_measurement_records,
    read_model,
)
from tests.testkit.relation_plans import (
    scalar_value_expr,
    table_value_expr,
    value_expr,
)
from tests.testkit.signal_instruments import (
    TestSignalInstrument,
)
from tests.testkit.typed_program import (
    compute_result,
    instrument_product_producer,
    link_program,
    observable_product,
    typed_program,
)
from tests.testkit.workflow_fixtures import load_config, load_experiment


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
                        line_id="q0.xy",
                        capability="set_frequency",
                        group_ids=["lo.xy0"],
                    )
                ],
            )
        ],
    )

    assert_model_round_trip(
        description,
        schema_version="scopecat.instrument_description.v1",
    )
    assert_model_round_trip(
        state,
        schema_version="scopecat.instrument_state_snapshot.v2",
    )
    assert_model_round_trip(
        command,
        schema_version="scopecat.instrument_state_command.v4",
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
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    assert manifest.status == "completed"
    assert {record.id for record in manifest.records} == {
        "instrument-state-evidence",
        "run-outcome",
    }
    assert {dataset.id for dataset in manifest.datasets} == {"raw-measurements"}
    raw_dataset = manifest.datasets[0]
    assert raw_dataset.kind == "measurement_dataset"
    persisted_manifest = read_model(run_dir / "manifest.json", RunManifest)
    persisted_config = read_model(
        run_dir / "config-profile.snapshot.json",
        ConfigProfileSnapshot,
    )
    state_evidence_path = run_dir / instrument_state_evidence_ref()
    state_evidence = read_model(state_evidence_path, InstrumentStateEvidence)
    assert persisted_manifest == manifest
    assert persisted_config == config
    assert state_evidence.schema_version == "scopecat.instrument_state_evidence.v3"
    assert {
        snapshot.schema_version
        for snapshot in [*state_evidence.initial_state, *state_evidence.final_state]
    } == {"scopecat.instrument_state_snapshot.v2"}
    final_state_value = state_evidence.final_state[0].fields[0].value.root
    assert final_state_value == Quantity(value=5.1, unit="GHz")
    persisted_state_evidence = json.loads(state_evidence_path.read_text())
    assert persisted_state_evidence["final_state"][0]["fields"][0]["value"] == {
        "value": 5.1,
        "unit": "GHz",
    }
    assert not (run_dir / "experiment-plan.json").exists()
    assert not (run_dir / "records" / "device_program" / "device-program.json").exists()

    measurements = read_measurement_records(run_dir / dataset_storage_ref(raw_dataset))
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


def test_terminal_persistence_error_reports_committed_and_pending_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_ref = instrument_state_evidence_ref()
    original_write = FilesystemRunRepository.write_model

    def fail_instrument_state_write(
        storage: FilesystemRunRepository,
        run_id: str,
        ref: str,
        model: BaseModel,
    ) -> None:
        if ref == pending_ref:
            raise OSError("injected instrument-state persistence failure")
        original_write(storage, run_id, ref, model)

    monkeypatch.setattr(
        FilesystemRunRepository,
        "write_model",
        fail_instrument_state_write,
    )

    with pytest.raises(RunPersistenceError) as captured:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    error = captured.value
    assert error.run_id
    assert error.phase == "instrument_state_evidence"
    assert error.retry == "after_reconciliation"
    assert error.certainty == "known"
    assert "inspect_run_execution" in error.reconciliation
    assert error.committed_refs == (run_outcome_ref(),)
    assert error.pending_ref == pending_ref
    storage = local_run_repository(tmp_path)
    manifest = storage.read_manifest(error.run_id)
    assert manifest.lifecycle == "running"
    assert storage.exists(error.run_id, run_outcome_ref())
    assert not storage.exists(error.run_id, pending_ref)


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
        workspace=tmp_path,
    )

    assert manifest.status == "completed"
    raw_path = (
        tmp_path / "runs" / manifest.run_id / dataset_storage_ref(manifest.datasets[0])
    )
    wire = raw_path.read_text()
    assert "NaN" in wire
    assert "Infinity" in wire
    assert "-Infinity" in wire
    measurements = read_measurement_records(raw_path)
    values = [
        cast(Quantity, measurement.observables["signal"]).value
        for measurement in measurements
    ]
    assert math.isnan(values[0])
    assert values[1:] == [float("inf"), float("-inf")]


class _RecordingLeaseManager:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.active = False
        self.claims: tuple[ResourceClaim, ...] = ()

    @contextmanager
    def acquire(
        self,
        claims: tuple[ResourceClaim, ...],
    ) -> Generator[None, None, None]:
        self.claims = claims
        self.events.append("lease.enter")
        self.active = True
        try:
            yield
        finally:
            self.active = False
            self.events.append("lease.exit")


class _LeaseOrderProvider:
    provider_id = "tests.lease_order_provider"

    def __init__(
        self,
        *,
        driver: TestSignalInstrument,
        leases: _RecordingLeaseManager,
        workspace: Path,
        events: list[str],
    ) -> None:
        self.driver = driver
        self.leases = leases
        self.workspace = workspace
        self.events = events

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        self.events.append("provider.describe")
        assert not self.leases.active
        assert local_run_repository(self.workspace).list_runs() == []
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(self.driver.describe(),),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        self.events.append("provider.provide")
        assert self.leases.active
        assert local_run_repository(self.workspace).list_runs()[0].status == "running"
        return InstrumentProviderResult(
            drivers=(self.driver,),
            metadata={
                "allocation": {"rack": "virtual-0", "exclusive": True},
            },
        )


class _PersistentInterruptingIdentityDriver(SignalInstrumentDriver):
    implementation_id = "tests.interrupting_identity_driver"
    implementation_version = "v1"

    def __init__(self) -> None:
        super().__init__()
        self.cleanup_count = 0
        self.terminal_read_count = 0

    @property
    @override
    def instrument_id(self) -> str:
        raise KeyboardInterrupt("identity lookup cancelled")

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        self.terminal_read_count += 1
        return InstrumentStateSnapshot(instrument_id="source-0")

    @override
    def cleanup(self) -> None:
        self.cleanup_count += 1


class _InterruptingIdentityProvider:
    provider_id = "tests.interrupting_identity_provider"

    def __init__(self, driver: _PersistentInterruptingIdentityDriver) -> None:
        self.driver = driver

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        description = (
            TestSignalInstrument()
            .describe()
            .model_copy(
                update={
                    "implementation_id": self.driver.implementation_id,
                    "implementation_version": self.driver.implementation_version,
                }
            )
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
        return InstrumentProviderResult(
            drivers=(cast("InstrumentDriver", cast("object", self.driver)),)
        )


class _TrackedSetupDriver(TestSignalInstrument):
    def __init__(self) -> None:
        super().__init__()
        self.cleanup_count = 0
        self.terminal_read_count = 0

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        self.terminal_read_count += 1
        return super().read_state()

    @override
    def cleanup(self) -> None:
        self.cleanup_count += 1


class _InvalidMetadataProvider:
    provider_id = "tests.invalid_metadata_provider"

    def __init__(self, driver: _TrackedSetupDriver) -> None:
        self.driver = driver

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(self.driver.describe(),),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        invalid_metadata = cast(
            "dict[str, JsonValue]",
            {"opaque": object()},
        )
        return InstrumentProviderResult(
            drivers=(self.driver,),
            metadata=invalid_metadata,
        )


class _MalformedDescriptionProvider:
    provider_id = "tests.malformed_description_provider"

    def __init__(self) -> None:
        self.provide_called = False

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return cast("InstrumentProviderDescription", object())

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        self.provide_called = True
        return InstrumentProviderResult(drivers=())


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
                    impact=ProblemImpact.ADVISORY,
                    category=ProblemCategory.PROVIDER_CONTRACT,
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


class _InvalidIdentityProvider:
    def __init__(self) -> None:
        self.describe_called = False
        self.provide_called = False

    @property
    def provider_id(self) -> str:
        return ""

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        self.describe_called = True
        raise AssertionError("describe must not follow an invalid provider identity")

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


def test_provider_lifecycle_is_inside_resource_lease(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    leases = _RecordingLeaseManager(events)
    provider = _LeaseOrderProvider(
        driver=TestSignalInstrument(),
        leases=leases,
        workspace=tmp_path,
        events=events,
    )
    config = load_config()
    manifest = execute_program_run(
        config=config,
        experiment=load_experiment(),
        instrument_provider=provider,
        workspace=tmp_path,
        resource_leases=leases,
    )

    assert manifest.status == "completed"
    assert events[:3] == [
        "provider.describe",
        "lease.enter",
        "provider.provide",
    ]
    assert events[-1] == "lease.exit"
    assert {(claim.kind, claim.id) for claim in leases.claims} >= {
        ("instrument", "source-0")
    }
    journal_entries = [
        json.loads(path.read_text())
        for path in sorted(
            (tmp_path / "runs" / manifest.run_id / "execution" / "journal").glob(
                "*.json"
            )
        )
    ]
    provisioned = next(
        entry
        for entry in journal_entries
        if entry["stage"] == "provide_instruments" and entry["state"] == "completed"
    )
    receipt = provisioned["evidence"]["provisioning_receipt"]
    assert receipt["provider_id"] == provider.provider_id
    assert receipt["instrument_ids"] == ["source-0"]
    assert receipt["metadata"] == {
        "allocation": {"rack": "virtual-0", "exclusive": True}
    }
    assert provisioned["evidence"]["provisioning_receipt_content_hash"] == (
        stable_content_hash(receipt)
    )


def test_returned_driver_is_finalized_when_identity_getter_interrupts(
    tmp_path: Path,
) -> None:
    driver = _PersistentInterruptingIdentityDriver()
    provider = _InterruptingIdentityProvider(driver)
    config = load_config()
    with pytest.raises(KeyboardInterrupt, match="identity lookup cancelled"):
        execute_program_run(
            config=config,
            experiment=load_experiment(),
            instrument_provider=provider,
            workspace=tmp_path,
        )

    assert driver.cleanup_count == 1
    assert driver.terminal_read_count == 1
    manifest = local_run_repository(tmp_path).list_runs()[0]
    assert manifest.status == "interrupted"
    journal_entries = [
        json.loads(path.read_text())
        for path in sorted(
            (tmp_path / "runs" / manifest.run_id / "execution" / "journal").glob(
                "*.json"
            )
        )
    ]
    cleanup = next(
        entry
        for entry in journal_entries
        if entry["stage"] == "setup_cleanup" and entry["state"] == "completed"
    )
    assert cleanup["instrument_id"] == "provider-driver-0"


def test_returned_driver_is_finalized_when_provider_metadata_is_not_json(
    tmp_path: Path,
) -> None:
    driver = _TrackedSetupDriver()
    provider = _InvalidMetadataProvider(driver)
    config = load_config()
    with pytest.raises(RunFailed) as captured:
        execute_program_run(
            config=config,
            experiment=load_experiment(),
            instrument_provider=provider,
            workspace=tmp_path,
        )

    assert "instrument_provider_result_invalid" in {
        problem.code for problem in captured.value.problems
    }
    assert driver.cleanup_count == 1
    assert driver.terminal_read_count == 1
    manifest = local_run_repository(tmp_path).list_runs()[0]
    assert manifest.status == "failed"


def test_malformed_provider_description_is_rejected_before_run_acceptance(
    tmp_path: Path,
) -> None:
    provider = _MalformedDescriptionProvider()
    config = load_config()
    plan = materialize_local_plan(
        link_program(load_experiment(), validate_config_environment(config))
    )

    with pytest.raises(ProviderContractError) as captured:
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    assert "instrument_provider_description_failed" in {
        problem.code for problem in captured.value.problems
    }
    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


def test_provider_abi_problems_are_aggregated_in_stable_order_before_run(
    tmp_path: Path,
) -> None:
    provider = _OrderedAbiProblemProvider()
    config = load_config()
    plan = materialize_local_plan(
        link_program(load_experiment(), validate_config_environment(config))
    )
    plan = _first_point_plan(
        plan,
        problems=(
            Problem(
                code="plan_warning",
                impact=ProblemImpact.ADVISORY,
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.PLANNING,
                message="bound plan warning",
                location=model_location("bound_plan"),
            ),
        ),
    )

    with pytest.raises(ProviderContractError) as captured:
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    assert [problem.code for problem in captured.value.problems] == [
        "plan_warning",
        "provider_abi_warning",
        "instrument_provider_id_mismatch",
        "instrument_not_in_config",
        "instrument_product_unsupported",
    ]
    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


def test_partial_provider_description_reports_missing_bound_instrument_before_run(
    tmp_path: Path,
) -> None:
    provider = _PartialDescriptionProvider()
    config = load_config()
    plan = materialize_local_plan(
        link_program(load_experiment(), validate_config_environment(config))
    )

    with pytest.raises(ProviderContractError) as captured:
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    assert [problem.code for problem in captured.value.problems] == [
        "instrument_not_in_config",
        "missing_instrument_description",
    ]
    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


def test_provider_description_exception_preserves_cause_and_preflight_order(
    tmp_path: Path,
) -> None:
    failure = RuntimeError("description unavailable")
    provider = _FailingDescriptionProvider(failure)
    config = load_config()
    plan = materialize_local_plan(
        link_program(load_experiment(), validate_config_environment(config))
    )
    plan = replace(
        plan,
        problems=(
            Problem(
                code="plan_warning",
                impact=ProblemImpact.ADVISORY,
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.PLANNING,
                message="bound plan warning",
                location=model_location("bound_plan"),
            ),
        ),
    )

    with pytest.raises(ProviderContractError) as captured:
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    assert [problem.code for problem in captured.value.problems] == [
        "plan_warning",
        "instrument_provider_description_failed",
    ]
    assert captured.value.__cause__ is failure
    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


def test_invalid_provider_identity_stops_before_description_and_run(
    tmp_path: Path,
) -> None:
    provider = _InvalidIdentityProvider()
    config = load_config()
    plan = materialize_local_plan(
        link_program(load_experiment(), validate_config_environment(config))
    )

    with pytest.raises(ProviderContractError) as captured:
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    assert [problem.code for problem in captured.value.problems] == [
        "instrument_provider_identity_failed"
    ]
    assert isinstance(captured.value.__cause__, TypeError)
    assert not provider.describe_called
    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


@pytest.mark.parametrize("advertised_unit", [None, "GHz"])
def test_provider_product_unit_mismatch_is_rejected_before_run(
    tmp_path: Path,
    advertised_unit: str | None,
) -> None:
    provider = _UnitAbiProvider(product_unit=advertised_unit)
    config = load_config()
    plan = materialize_local_plan(
        link_program(load_experiment(), validate_config_environment(config))
    )
    plan = _first_point_plan(plan)

    with pytest.raises(ProviderContractError) as captured:
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    problem = captured.value.problems[0]
    assert len(captured.value.problems) == 1
    assert problem.code == "instrument_product_unit_mismatch"
    assert problem.location == model_location(
        "execution_program",
        "operations",
        f"{plan.points[0].logical_id.value}.collect.source-0",
        "requests",
        "signal",
        "unit",
    )
    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


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
    environment = validate_config_environment(config)
    assert environment.routing is not None
    experiment = load_experiment()
    plan = materialize_local_plan(link_program(experiment, environment))
    point = plan.points[0]
    collect = point.collect[0]
    request = replace(
        collect.requests[0],
        axes=(BoundAxis(id="sample", kind="sample", size=2, unit="ns"),),
    )
    point = replace(
        point,
        collect=(replace(collect, requests=(request,)),),
    )
    product = replace(
        experiment.product_defs[0],
        axes=(ProductAxisDef(id="sample", kind="sample", size=2, unit="ns"),),
    )
    realizations, realization_problems = select_local_product_realizations(
        (product,),
        experiment.instrument_product_producers,
        plan.product_uses,
        routing=environment.routing,
    )
    assert realization_problems == ()
    assert realizations is not None
    plan = replace(
        plan,
        points=(point,),
        local_product_realizations=realizations,
    )

    with pytest.raises(ProviderContractError) as captured:
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    problem = captured.value.problems[0]
    assert len(captured.value.problems) == 1
    assert problem.code == "instrument_product_axis_unit_mismatch"
    assert problem.location == model_location(
        "execution_program",
        "operations",
        f"{point.logical_id.value}.collect.source-0",
        "requests",
        "signal",
        "axes",
        0,
        "unit",
    )
    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


def _first_point_plan(
    plan: BoundPlan,
    *,
    problems: tuple[Problem, ...] | None = None,
) -> BoundPlan:
    return replace(
        plan,
        points=plan.points[:1],
        **({"problems": problems} if problems is not None else {}),
    )


def test_provider_description_interruption_precedes_run_acceptance(
    tmp_path: Path,
) -> None:
    provider = _FailingDescriptionProvider(KeyboardInterrupt("description cancelled"))
    config = load_config()
    plan = materialize_local_plan(
        link_program(load_experiment(), validate_config_environment(config))
    )

    with pytest.raises(KeyboardInterrupt, match="description cancelled"):
        prepare_execution(
            config=config,
            plan=plan,
            instrument_provider=provider,
        )

    assert not provider.provide_called
    assert local_run_repository(tmp_path).list_runs() == []


def test_run_emits_transient_runtime_events(tmp_path: Path) -> None:
    events: list[RuntimeEvent] = []

    manifest = execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        workspace=tmp_path,
        event_sink=events.append,
    )

    assert manifest.status == "completed"
    lifecycle_events = [
        event.kind for event in events if event.kind in {"run_started", "run_finished"}
    ]
    assert lifecycle_events == [
        "run_started",
        "run_finished",
    ]
    transitions = [
        event for event in events if isinstance(event, RuntimeTransitionEvent)
    ]
    point_started = [
        event
        for event in transitions
        if event.stage == "point" and event.state == "started"
    ]
    point_finished = [
        event
        for event in transitions
        if event.stage == "point" and event.state == "completed"
    ]
    committed_records = [
        event
        for event in transitions
        if event.stage == "record_measurement" and event.state == "completed"
    ]
    assert len(point_started) == 3
    assert len(point_finished) == 3
    assert len(committed_records) == 3
    assert all(event.sequence is None for event in (*point_started, *point_finished))
    durable_transitions = FilesystemExecutionJournal(
        tmp_path,
        run_id=manifest.run_id,
    ).entries()
    assert not {
        "point",
        "compute",
        "initial_readback",
        "terminal_readback",
        "setup_terminal_readback",
    } & {transition.stage for transition in durable_transitions}
    assert all(event.sequence is not None for event in committed_records)
    inspection = inspect_run_execution(
        run_id=manifest.run_id,
        services=local_workspace_services(tmp_path),
    )
    assert inspection.transitions == durable_transitions
    assert not inspection.reconciliation_required
    assert [event.metrics["compute_step_count"] for event in point_started] == [
        0,
        0,
        0,
    ]
    assert [event.progress.completed_points for event in point_finished] == [1, 2, 3]
    assert all(event.state == "completed" for event in point_finished)
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert finished.result == "succeeded"
    assert finished.certainty == "known"
    assert finished.progress.completed_points == 3
    assert finished.progress.total_points == 3


def test_runtime_event_sink_failure_does_not_change_durable_execution(
    tmp_path: Path,
) -> None:
    def reject_event(_event: RuntimeEvent) -> None:
        raise RuntimeError("observer unavailable")

    manifest = execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        workspace=tmp_path,
        event_sink=reject_event,
    )

    assert manifest.status == "completed"
    durable_transitions = FilesystemExecutionJournal(
        tmp_path,
        run_id=manifest.run_id,
    ).entries()
    assert any(
        transition.stage == "collect" and transition.state == "completed"
        for transition in durable_transitions
    )
    assert any(
        transition.stage == "record_measurement" and transition.state == "completed"
        for transition in durable_transitions
    )
    assert manifest.outcome is not None
    assert all(
        problem.code != "execution_journal_commit_failed"
        for problem in manifest.outcome.problems
    )


def test_run_reuses_unchanged_compute_payloads(tmp_path: Path) -> None:
    calls: list[Quantity] = []

    def build_program(*, value: object) -> dict[str, object]:
        assert isinstance(value, Quantity)
        calls.append(value)
        return {"value": value}

    operation_id = OperationId(SymbolId(local_id="build-program"))
    result_id = operation_result_id(operation_id)
    point_type = TableType(
        columns=(TableColumn("value", Scalar(QuantityType())),),
        allow_extra_columns=True,
    )
    product = observable_product("signal")
    producer = instrument_product_producer(
        product,
        physical_resource_id="source-0",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="cached-compute-run",
        kind="cached_compute",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows(
                        [
                            {
                                "sequence_index": 0,
                                "value": Quantity(value=4.9, unit="GHz"),
                            },
                            {
                                "sequence_index": 1,
                                "value": Quantity(value=4.9, unit="GHz"),
                            },
                            {
                                "sequence_index": 2,
                                "value": Quantity(value=5.1, unit="GHz"),
                            },
                        ]
                    ),
                    expected_type=point_type,
                )
            ),
        ),
        state=[
            set_state_field(
                scalar_value_expr(
                    lit("source-0"),
                    expected_type=Scalar(String()),
                ),
                capability_id="play_program",
                field_path="program",
                value=compute_result("build-program"),
            )
        ],
        product_defs=[product],
        instrument_product_producers=[producer],
        product_uses=[product_use],
        record_uses=[record_use],
        compute_nodes=[
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                result=TypedComputeOutput(
                    id=result_id,
                    value_type=Scalar(Payload("pulse_program")),
                    availability=ValueAvailability(
                        ValueStage.EXECUTE,
                        ValueRate.POINT,
                    ),
                ),
                inputs={
                    "value": ValueInput(
                        value=value_expr(
                            point_col("value"),
                            expected_type=Scalar(QuantityType()),
                            bindings=RelationTypeBindings(
                                point_row=RowType.from_table(point_type)
                            ),
                        ),
                    )
                },
            )
        ],
        implementation_catalog=ImplementationCatalog(
            local_python=(
                LocalPythonImplementation(
                    id=ImplementationId("python.build-program.v1"),
                    operation_id=operation_id,
                    operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    kernel=build_program,
                ),
            )
        ),
    )
    events: list[RuntimeEvent] = []
    payload_observations: list[RuntimePayloadObservation] = []

    config = config_with_physical_resources({"source-0": ("play_program",)})
    manifest = execute_bound_run(
        config=config,
        experiment=spec,
        instruments=[SignalInstrumentDriver()],
        workspace=tmp_path,
        event_sink=events.append,
        payload_observer=payload_observations.append,
    )

    transitions = [
        event for event in events if isinstance(event, RuntimeTransitionEvent)
    ]
    compute_events = [
        event
        for event in transitions
        if event.stage == "compute" and event.state == "completed"
    ]
    state_events = [
        event
        for event in transitions
        if event.stage == "apply_state" and event.state == "completed"
    ]
    state_reconciled = [
        event
        for event in transitions
        if event.stage == "apply_state" and event.state == "skipped"
    ]

    assert manifest.status == "completed"
    assert calls == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert [event.metrics["compute_status"] for event in compute_events] == [
        "evaluated",
        "reused",
        "evaluated",
    ]
    assert all(event.sequence is None for event in compute_events)
    assert all(
        transition.stage != "compute"
        for transition in FilesystemExecutionJournal(
            tmp_path,
            run_id=manifest.run_id,
        ).entries()
    )
    payload_ids = cast(
        "list[str]",
        [event.metrics["payload_id"] for event in compute_events],
    )
    assert payload_ids[0] == payload_ids[1]
    assert payload_ids[2] != payload_ids[0]
    assert all(
        payload_id.startswith(f"{result_id.qualified_name}.payload.")
        for payload_id in payload_ids
    )
    assert [
        (observation.payload_id, observation.compute_status)
        for observation in payload_observations
    ] == [
        (payload_ids[0], "evaluated"),
        (payload_ids[1], "reused"),
        (payload_ids[2], "evaluated"),
    ]
    assert {
        observation.semantic_operation_id for observation in payload_observations
    } == {"build-program"}
    assert [
        observation.summary["implementation_id"] for observation in payload_observations
    ] == ["python.build-program.v1"] * 3
    assert [observation.payload.payload for observation in payload_observations] == [
        {"value": Quantity(value=4.9, unit="GHz")},
        {"value": Quantity(value=4.9, unit="GHz")},
        {"value": Quantity(value=5.1, unit="GHz")},
    ]
    assert payload_observations[0].summary["payload_id"] == payload_ids[0]
    assert [
        event.metrics["compute_evaluated_node_count"] for event in state_events
    ] == [1, 1]
    assert [event.metrics["compute_reused_node_count"] for event in state_events] == [
        0,
        0,
    ]
    assert [event.state for event in state_reconciled] == ["skipped"]
    assert [
        event.metrics["compute_reused_node_count"] for event in state_reconciled
    ] == [1]
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert finished.compute_evaluated_node_count == 2
    assert finished.compute_reused_node_count == 1
    assert finished.compute_payload_count == 3


def test_run_skips_unchanged_state_fields(tmp_path: Path) -> None:
    instrument = TestSignalInstrument()
    experiment = replace(
        load_experiment(),
        state=(
            set_state_field(
                scalar_value_expr(
                    lit("source-0"),
                    expected_type=Scalar(String()),
                ),
                capability_id="set_frequency",
                field_path="frequency",
                value=scalar_value_expr(
                    lit(Quantity(value=5.9, unit="GHz")),
                    expected_type=Scalar(QuantityType(unit="GHz")),
                ),
            ),
        ),
    )
    events: list[RuntimeEvent] = []

    manifest = execute_bound_run(
        config=load_config(),
        experiment=experiment,
        instruments=[instrument],
        workspace=tmp_path,
        event_sink=events.append,
    )

    assert manifest.status == "completed"
    assert len(instrument.applied_commands) == 1
    transitions = [
        event for event in events if isinstance(event, RuntimeTransitionEvent)
    ]
    state_events = [
        event
        for event in transitions
        if event.stage == "apply_state" and event.state == "completed"
    ]
    reconciled_events = [
        event
        for event in transitions
        if event.stage == "apply_state" and event.state == "skipped"
    ]
    assert [event.metrics["changed_field_count"] for event in state_events] == [1]
    assert [event.metrics["skipped_field_count"] for event in state_events] == [0]
    assert [event.state for event in reconciled_events] == [
        "skipped",
        "skipped",
    ]
    assert [event.metrics["skipped_field_count"] for event in reconciled_events] == [
        1,
        1,
    ]

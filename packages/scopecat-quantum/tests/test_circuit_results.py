from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import cast

import pytest
from scopecat import Quantity
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import link_program
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    TypedProgram,
    product_output,
    record_product,
)
from scopecat._point_domain_algebra import point_rows
from scopecat._relation_verification import RelationTypeBindings
from scopecat._relations import literal_rows
from scopecat._value_expressions import verify_table_value_expr
from scopecat.config_profiles import load_config_profile
from scopecat.domain_invocation import (
    LogicalPointId,
    MaterializedLinkedPoints,
    ProductUseId,
    materialize_linked_points,
)
from scopecat.value_types import Float, Scalar, Table, TableColumn

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    PulseEventId,
    PulseProgramId,
    QubitId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.calibrations import (
    CalibrationCatalog,
    select_calibrations,
)
from scopecat_quantum.circuit_results import (
    CircuitTargetAcquisitionUseBinding,
    CircuitTargetEntryPointBinding,
    CircuitTargetResultMapping,
    bind_compiled_circuit_target,
    seal_circuit_target_result_mapping,
)
from scopecat_quantum.circuit_targets import (
    PreparedCircuitTargetBatch,
    prepare_circuit_target_batch,
    prepare_circuit_target_entry,
)
from scopecat_quantum.circuits import (
    CircuitProgram,
    Measure,
    verify_circuit_program,
)
from scopecat_quantum.circuits import Sequence as CircuitSequence
from scopecat_quantum.measurement_calibrations import (
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Play,
    PulseProgram,
    ReadoutSignal,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetAcquisitionAddress,
    TargetCompileRequest,
    compile_target,
)

Q0 = QubitId("q0")
_WORKSPACE = Path(__file__).parents[3]


def _linked_points(
    *,
    program_id: str = "domain-result-mapping",
    product_count: int = 2,
) -> MaterializedLinkedPoints:
    point_type = Table(
        columns=(TableColumn("coordinate", Scalar(Float())),),
        min_rows=2,
        max_rows=2,
    )
    point_domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    (
                        {"coordinate": 10.0},
                        {"coordinate": 20.0},
                    )
                ),
                bindings=RelationTypeBindings(),
                expected_type=point_type,
            )
        )
    )
    products = tuple(
        product_output(f"result-{index}", dtype="complex128")
        for index in range(product_count)
    )
    selections = tuple(record_product(product) for product in products)
    program = TypedProgram(
        id=program_id,
        kind="domain_mapping_test",
        point_domain=point_domain,
        product_defs=products,
        product_uses=tuple(use for use, _record in selections),
        record_uses=tuple(record for _use, record in selections),
    )
    environment = validate_config_environment(
        load_config_profile(
            _WORKSPACE / "fixtures" / "core" / "simple_scan" / "config-profile.json"
        )
    )
    return materialize_linked_points(link_program(program, environment))


def _prepared_batch() -> PreparedCircuitTargetBatch:
    measurements = tuple(
        Measure(
            id=CircuitOperationId(f"measure-{index}"),
            qubit=Q0,
            acquisition_slot_id=AcquisitionSlotId(f"result-{index}"),
            acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
        )
        for index in range(2)
    )
    circuit = verify_circuit_program(
        CircuitProgram(
            id=CircuitId("shared-result-circuit"),
            body=CircuitSequence(measurements),
        ),
        (),
    )
    template_slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(Q0),
    )
    template = PulseProgram(
        id=PulseProgramId("readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("readout"),
                    signal=ReadoutSignal(Q0),
                    envelope=Constant(
                        duration=Quantity(4, "ns"),
                        amplitude=Quantity(0.2, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("acquire"),
                    signal=AcquireSignal(Q0),
                    slot_id=template_slot.id,
                    duration=Quantity(4, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    calibration = MeasurementCalibration(
        id=CalibrationId("readout-q0"),
        key=MeasurementCalibrationKey(
            Q0,
            AcquisitionKind.INTEGRATED_IQ,
        ),
        pulse_template=template,
    )
    selection = select_calibrations(
        circuit,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog((calibration,)),
        ),
    )
    entries = tuple(
        prepare_circuit_target_entry(
            TargetCompileEntryId(entry_id),
            circuit,
            selection,
            output_id=PulseProgramId("shared-result-pulses"),
        )
        for entry_id in ("entry-b", "entry-a")
    )
    return prepare_circuit_target_batch(
        entries,
        target_id=TargetId("target"),
        compiler_id=TargetCompilerId("compiler.v1"),
        capability_fingerprint="capabilities:v1",
        repetitions=3,
    )


def _valid_inputs(
    *,
    product_count: int = 2,
) -> tuple[
    MaterializedLinkedPoints,
    PreparedCircuitTargetBatch,
    tuple[CircuitTargetEntryPointBinding, ...],
    tuple[CircuitTargetAcquisitionUseBinding, ...],
]:
    linked_points = _linked_points(product_count=product_count)
    batch = _prepared_batch()
    points = linked_points.point_domain.points
    uses = linked_points.linked_plan.product_uses
    entry_bindings = (
        CircuitTargetEntryPointBinding(batch.entries[0].id, points[1].logical_id),
        CircuitTargetEntryPointBinding(batch.entries[1].id, points[0].logical_id),
    )
    acquisition_bindings = tuple(
        CircuitTargetAcquisitionUseBinding(address, uses[index].id)
        for entry in batch.entries
        for index, address in enumerate(entry.acquisition_addresses)
    )
    return linked_points, batch, entry_bindings, acquisition_bindings


def _seal(
    linked_points: MaterializedLinkedPoints,
    batch: PreparedCircuitTargetBatch,
    entry_bindings: tuple[CircuitTargetEntryPointBinding, ...],
    acquisition_bindings: tuple[CircuitTargetAcquisitionUseBinding, ...],
) -> CircuitTargetResultMapping:
    return seal_circuit_target_result_mapping(
        linked_points,
        batch,
        entry_bindings,
        acquisition_bindings,
    )


@dataclass(frozen=True, slots=True)
class _TargetArtifact:
    id: TargetArtifactId
    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    artifact_fingerprint: str
    source_entry_ids: tuple[TargetCompileEntryId, ...]
    repetitions: int


@dataclass(frozen=True, slots=True)
class _TargetCompiler:
    id: TargetCompilerId
    target_id: TargetId
    capability_fingerprint: str

    def compile(self, request: TargetCompileRequest) -> _TargetArtifact:
        return _TargetArtifact(
            id=TargetArtifactId("artifact"),
            target_id=self.target_id,
            compiler_id=self.id,
            capability_fingerprint=self.capability_fingerprint,
            artifact_fingerprint="artifact-content:v1",
            source_entry_ids=tuple(entry.id for entry in request.entries),
            repetitions=request.repetitions,
        )


def _compile(
    request: TargetCompileRequest,
) -> CompiledTargetArtifact[_TargetArtifact]:
    return compile_target(
        _TargetCompiler(
            id=request.compiler_id,
            target_id=request.target_id,
            capability_fingerprint=request.capability_fingerprint,
        ),
        request,
    )


def test_circuit_target_mapping_retains_batch_and_exact_core_proof() -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs()

    mapping = _seal(
        linked_points,
        batch,
        entry_bindings,
        acquisition_bindings,
    )

    points = linked_points.point_domain.points
    uses = linked_points.linked_plan.product_uses
    assert mapping.batch is batch
    assert mapping.linked_points is linked_points
    assert tuple(entry.logical_point_id for entry in mapping.entries) == tuple(
        point.logical_id for point in points
    )
    assert tuple(entry.entry_address for entry in mapping.entries) == (
        batch.entries[1].id,
        batch.entries[0].id,
    )
    assert {result.result_address for result in mapping.results} == set(
        batch.acquisition_addresses
    )
    assert {
        (result.logical_point_id, result.product_use_id) for result in mapping.results
    } == {(point.logical_id, use.id) for point in points for use in uses}
    for result in mapping.results:
        assert result.entry_address == result.result_address.entry_id
        assert result.product_id == result.product_use.product_id
        assert mapping.result_for_address(result.result_address) is result
        assert (
            mapping.result_for_output(
                result.logical_point_id,
                result.product_use_id,
            )
            is result
        )
    for entry in mapping.entries:
        assert mapping.entry_for_id(entry.entry_address) is entry


def test_circuit_mapping_derives_and_canonicalizes_selected_product_uses() -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs(
        product_count=3
    )
    uses = linked_points.linked_plan.product_uses

    mapping = _seal(
        linked_points,
        batch,
        entry_bindings,
        tuple(reversed(acquisition_bindings)),
    )

    assert mapping.selected_product_use_ids == (uses[0].id, uses[1].id)
    assert mapping.core_mapping.selected_product_use_ids == (
        uses[0].id,
        uses[1].id,
    )
    assert tuple(result.product_use_id for result in mapping.results) == tuple(
        use.id for _point in linked_points.point_domain.points for use in uses[:2]
    )
    with pytest.raises(KeyError, match="not in this mapping"):
        mapping.result_for_output(
            linked_points.point_domain.points[0].logical_id,
            uses[2].id,
        )


def test_compiled_circuit_target_binds_exact_mapping_request_and_artifact() -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = _seal(
        linked_points,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    compiled = _compile(batch.request)

    bound = bind_compiled_circuit_target(mapping, compiled)

    assert bound.mapping is mapping
    assert bound.compiled is compiled
    assert bound.compiled.request == bound.mapping.batch.request
    assert bound.compiled.source_entry_ids == tuple(
        entry.id for entry in bound.mapping.batch.entries
    )
    assert bound.compiled.repetitions == bound.mapping.batch.request.repetitions


def test_compiled_circuit_target_rejects_another_batch_request() -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = _seal(
        linked_points,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    compiled = _compile(replace(batch.request, repetitions=4))

    with pytest.raises(ValueError, match="exactly match the mapped circuit batch"):
        bind_compiled_circuit_target(mapping, compiled)


def test_compiled_circuit_target_binding_is_typed() -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = _seal(
        linked_points,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    compiled = _compile(batch.request)

    with pytest.raises(TypeError, match="CircuitTargetResultMapping"):
        bind_compiled_circuit_target(
            cast("CircuitTargetResultMapping", object()), compiled
        )
    with pytest.raises(TypeError, match="CompiledTargetArtifact"):
        bind_compiled_circuit_target(
            mapping,
            cast("CompiledTargetArtifact[_TargetArtifact]", object()),
        )


def test_acquisition_binding_does_not_repeat_parent_entry() -> None:
    assert {field.name for field in fields(CircuitTargetAcquisitionUseBinding)} == {
        "address",
        "product_use_id",
    }


@pytest.mark.parametrize(
    "change",
    ("missing", "duplicate", "foreign", "point_mismatch", "foreign_point"),
)
def test_entry_mapping_failures_are_rejected_before_any_effect(change: str) -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    selected = entry_bindings
    if change == "missing":
        selected = selected[:-1]
    elif change == "duplicate":
        selected = (selected[0], selected[0])
    elif change == "foreign":
        selected = (
            selected[0],
            replace(selected[1], entry_id=TargetCompileEntryId("foreign")),
        )
    elif change == "point_mismatch":
        selected = (
            selected[0],
            replace(selected[1], logical_point_id=selected[0].logical_point_id),
        )
    else:
        foreign_point = _linked_points(
            program_id="foreign-domain-result-mapping"
        ).point_domain.points[0]
        selected = (
            selected[0],
            replace(selected[1], logical_point_id=foreign_point.logical_id),
        )

    with pytest.raises(ValueError):
        _seal(linked_points, batch, selected, acquisition_bindings)


@pytest.mark.parametrize(
    "change",
    ("missing", "duplicate", "foreign", "unknown_use", "use_mismatch"),
)
def test_acquisition_mapping_failures_are_rejected_before_any_effect(
    change: str,
) -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    selected = acquisition_bindings
    if change == "missing":
        selected = selected[:-1]
    elif change == "duplicate":
        selected = (*selected[:-1], selected[0])
    elif change == "foreign":
        foreign_address = TargetAcquisitionAddress(
            entry_id=batch.entries[0].id,
            slot_id=AcquisitionSlotId("foreign"),
        )
        selected = (*selected[:-1], replace(selected[-1], address=foreign_address))
    elif change == "unknown_use":
        selected = (
            *selected[:-1],
            replace(selected[-1], product_use_id=ProductUseId("foreign")),
        )
    else:
        selected = (
            *selected[:-1],
            replace(selected[-1], product_use_id=selected[-2].product_use_id),
        )

    with pytest.raises(ValueError):
        _seal(linked_points, batch, entry_bindings, selected)


def test_foreign_address_parent_is_derived_and_rejected() -> None:
    linked_points, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    foreign_address = TargetAcquisitionAddress(
        entry_id=TargetCompileEntryId("foreign-entry"),
        slot_id=acquisition_bindings[-1].address.slot_id,
    )
    selected = (
        *acquisition_bindings[:-1],
        replace(acquisition_bindings[-1], address=foreign_address),
    )

    with pytest.raises(ValueError, match="exactly cover adapter result addresses"):
        _seal(linked_points, batch, entry_bindings, selected)


def test_quantum_mapping_types_close_runtime_identity_spaces() -> None:
    _, _, entry_bindings, acquisition_bindings = _valid_inputs()
    with pytest.raises(TypeError, match="TargetCompileEntryId"):
        CircuitTargetEntryPointBinding(
            cast("TargetCompileEntryId", TargetId("wrong-space")),
            entry_bindings[0].logical_point_id,
        )
    with pytest.raises(TypeError, match="LogicalPointId"):
        CircuitTargetEntryPointBinding(
            entry_bindings[0].entry_id,
            cast("LogicalPointId", object()),
        )
    with pytest.raises(TypeError, match="TargetAcquisitionAddress"):
        CircuitTargetAcquisitionUseBinding(
            cast("TargetAcquisitionAddress", object()),
            acquisition_bindings[0].product_use_id,
        )
    with pytest.raises(TypeError, match="ProductUseId"):
        CircuitTargetAcquisitionUseBinding(
            acquisition_bindings[0].address,
            cast("ProductUseId", TargetCompileEntryId("wrong-space")),
        )

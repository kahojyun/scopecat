from __future__ import annotations

import inspect
from dataclasses import dataclass, fields, replace
from importlib import import_module
from pathlib import Path
from typing import cast, get_type_hints

import pytest
from scopecat import Quantity
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    link_program,
)
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
    DomainCallId,
    DomainProgramId,
    DomainResultPortDef,
)
from scopecat.compiler.semantic.value_expressions import verify_table_value_expr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import DomainProductProducer
from scopecat.compiler.typed.program import (
    TypedDomainCall,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedProgram,
    product_output,
    record_product,
)
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.product_identity import product_producer_id
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar, Table, TableColumn
from scopecat.sdk.domain import (
    DomainExecutionOffer,
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultMapping,
)
from scopecat.sdk.domain.context import (
    make_domain_batch_context_internal,
    project_domain_plan_internal,
)
from scopecat.sdk.domain.invocation import materialize_linked_points

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


def _preparation(
    *,
    program_id: str = "domain-result-mapping",
    product_count: int = 2,
    shared_product: bool = False,
) -> DomainPreparationBuilder:
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
    products = (
        (product_output("shared-result", dtype="complex128"),)
        if shared_product and product_count
        else tuple(
            product_output(f"result-{index}", dtype="complex128")
            for index in range(product_count)
        )
    )
    selected_products = (
        products * product_count if shared_product and product_count else products
    )
    selections = tuple(
        record_product(product, record_id=f"record-{index}")
        for index, product in enumerate(selected_products)
    )
    if shared_product:
        result_specs = (
            (
                "result-0",
                products[0],
                tuple(use.id for use, _record in selections),
            ),
        )
    else:
        result_specs = tuple(
            (f"result-{index}", product, (selections[index][0].id,))
            for index, product in enumerate(products)
        )
    domain_program_id = DomainProgramId(SymbolId(local_id="program"))
    domain_call_id = DomainCallId(SymbolId(local_id="execute"))
    producer_ids = {
        result_id: product_producer_id(f"{result_id}-producer")
        for result_id, _product, _use_ids in result_specs
    }
    program = TypedProgram(
        id=program_id,
        kind="domain_mapping_test",
        point_domain=point_domain,
        product_defs=products,
        domain_programs=(
            TypedDomainProgram(
                id=domain_program_id,
                dialect_id="test.quantum.result-mapping",
                dialect_version="1",
                body=object(),
                result_ports=tuple(
                    DomainResultPortDef(result_id)
                    for result_id, _product, _use_ids in result_specs
                ),
            ),
        ),
        domain_calls=(
            TypedDomainCall(
                id=domain_call_id,
                program_id=domain_program_id,
                results=tuple(
                    TypedDomainResultBinding(
                        id=result_id,
                        product_id=product.id,
                        producer_id=producer_ids[result_id],
                        product_use_ids=use_ids,
                    )
                    for result_id, product, use_ids in result_specs
                ),
            ),
        ),
        domain_product_producers=tuple(
            DomainProductProducer(
                id=producer_ids[result_id],
                product_id=product.id,
                call_id=domain_call_id,
                result_id=result_id,
            )
            for result_id, product, _use_ids in result_specs
        ),
        product_uses=tuple(use for use, _record in selections),
        record_uses=tuple(record for _use, record in selections),
    )
    environment = validate_config_environment(
        load_config_profile(
            _WORKSPACE / "fixtures" / "core" / "simple_scan" / "config-profile.json"
        )
    )
    linked_points = materialize_linked_points(link_program(program, environment))
    projection = project_domain_plan_internal(linked_points)
    call = projection.view(linked_points).require_one_call(
        dialect_id="test.quantum.result-mapping"
    )
    offer = DomainExecutionOffer.for_call(
        call,
        max_points_per_batch=2,
    )
    context = make_domain_batch_context_internal(
        projection,
        MaterializedLinkedPointBatch(linked_points, (0, 1)),
        offer,
        adapter_id="test.quantum.result-mapping",
        batch_ordinal=0,
    )
    return context.new_preparation()


def _prepared_batch(*, result_count: int = 2) -> PreparedCircuitTargetBatch:
    measurements = tuple(
        Measure(
            id=CircuitOperationId(f"measure-{index}"),
            qubit=Q0,
            acquisition_slot_id=AcquisitionSlotId(f"result-{index}"),
            acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
        )
        for index in range(result_count)
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
    shared_product: bool = False,
) -> tuple[
    DomainPreparationBuilder,
    PreparedCircuitTargetBatch,
    tuple[CircuitTargetEntryPointBinding, ...],
    tuple[CircuitTargetAcquisitionUseBinding, ...],
]:
    preparation = _preparation(
        product_count=product_count,
        shared_product=shared_product,
    )
    batch = _prepared_batch(result_count=1 if shared_product else product_count)
    points = preparation.context.points
    uses = preparation.context.direct_product_uses
    entry_bindings = (
        CircuitTargetEntryPointBinding(batch.entries[0].id, points[1]),
        CircuitTargetEntryPointBinding(batch.entries[1].id, points[0]),
    )
    acquisition_bindings = (
        tuple(
            CircuitTargetAcquisitionUseBinding(address, use)
            for entry in batch.entries
            for address in entry.acquisition_addresses
            for use in uses
        )
        if shared_product
        else tuple(
            CircuitTargetAcquisitionUseBinding(address, uses[index])
            for entry in batch.entries
            for index, address in enumerate(entry.acquisition_addresses)
        )
    )
    return preparation, batch, entry_bindings, acquisition_bindings


def _seal(
    preparation: DomainPreparationBuilder,
    batch: PreparedCircuitTargetBatch,
    entry_bindings: tuple[CircuitTargetEntryPointBinding, ...],
    acquisition_bindings: tuple[CircuitTargetAcquisitionUseBinding, ...],
) -> CircuitTargetResultMapping:
    return seal_circuit_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )


def test_result_mapping_uses_the_context_bound_preparation_builder() -> None:
    preparation, target_batch, entry_bindings, acquisition_bindings = _valid_inputs()

    mapping = seal_circuit_target_result_mapping(
        preparation,
        target_batch,
        entry_bindings,
        acquisition_bindings,
    )

    assert mapping.batch is target_batch
    assert isinstance(mapping.domain_mapping, DomainResultMapping)
    assert mapping.domain_mapping.context is preparation.context
    assert (
        mapping.domain_mapping.product_uses == preparation.context.direct_product_uses
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


def test_circuit_target_mapping_retains_batch_and_exact_sdk_proof() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()

    mapping = _seal(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )

    domain_mapping = mapping.domain_mapping
    assert mapping.batch is batch
    assert domain_mapping.context is preparation.context
    assert tuple(
        (entry.entry_address, entry.result_addresses)
        for entry in domain_mapping.target_entries
    ) == tuple((entry.id, entry.acquisition_addresses) for entry in batch.entries)
    assert tuple(entry.entry_address for entry in domain_mapping.entries) == (
        batch.entries[1].id,
        batch.entries[0].id,
    )
    assert tuple(entry.point for entry in domain_mapping.entries) == (
        preparation.context.points
    )
    assert {result.result_address for result in domain_mapping.results} == set(
        batch.acquisition_addresses
    )
    assert len(domain_mapping.results) == len(preparation.context.points) * len(
        preparation.context.direct_product_uses
    )
    for result in domain_mapping.results:
        assert result.entry_address == result.result_address.entry_id
        assert all(
            product_use.product is result.product_uses[0].product
            for product_use in result.product_uses
        )
        assert domain_mapping.result_for_address(result.result_address) is result
        assert all(
            domain_mapping.result_for(result.point, product_use) is result
            for product_use in result.product_uses
        )


def test_circuit_mapping_canonicalizes_all_direct_product_uses() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs(
        product_count=3
    )
    context = preparation.context

    mapping = _seal(
        preparation,
        batch,
        entry_bindings,
        tuple(reversed(acquisition_bindings)),
    )

    assert len(context.product_uses) == 3
    assert len(context.direct_product_uses) == 3
    assert mapping.domain_mapping.product_uses == context.direct_product_uses
    assert all(
        actual is expected
        for actual, expected in zip(
            mapping.domain_mapping.product_uses,
            context.product_uses,
            strict=True,
        )
    )


def test_one_circuit_acquisition_fans_out_to_shared_product_uses() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs(
        shared_product=True
    )
    mapping = _seal(
        preparation,
        batch,
        entry_bindings,
        tuple(reversed(acquisition_bindings)),
    )
    context = preparation.context
    domain_mapping = mapping.domain_mapping

    assert len(context.direct_product_uses) == 2
    assert domain_mapping.product_uses == context.direct_product_uses
    assert len(domain_mapping.results) == len(context.points)
    assert len(domain_mapping.results) == len(batch.acquisition_addresses)
    assert all(len(result.product_uses) == 2 for result in domain_mapping.results)
    assert all(
        result.product_uses[0].product is result.product_uses[1].product
        for result in domain_mapping.results
    )
    for result in domain_mapping.results:
        assert domain_mapping.result_for(
            result.point,
            result.product_uses[0],
        ) is domain_mapping.result_for(
            result.point,
            result.product_uses[1],
        )


def test_compiled_circuit_target_binds_exact_mapping_request_and_artifact() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = _seal(
        preparation,
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
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = _seal(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    compiled = _compile(replace(batch.request, repetitions=4))

    with pytest.raises(ValueError, match="exactly match the mapped circuit batch"):
        bind_compiled_circuit_target(mapping, compiled)


def test_compiled_circuit_target_binding_is_typed() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = _seal(
        preparation,
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
    assert {field.name for field in fields(CircuitTargetEntryPointBinding)} == {
        "entry_id",
        "point",
    }
    assert {field.name for field in fields(CircuitTargetAcquisitionUseBinding)} == {
        "address",
        "product_use",
    }
    assert {field.name for field in fields(CircuitTargetResultMapping)} == {
        "batch",
        "domain_mapping",
    }


def test_public_mapping_boundaries_do_not_expose_compiler_types() -> None:
    public_callables = (seal_circuit_target_result_mapping,)
    public_types = (
        CircuitTargetEntryPointBinding,
        CircuitTargetAcquisitionUseBinding,
        CircuitTargetResultMapping,
    )

    rendered: list[str] = []
    for callable_ in public_callables:
        rendered.append(str(inspect.signature(callable_)))
        module_globals = vars(import_module(callable_.__module__))
        rendered.extend(
            repr(annotation)
            for annotation in get_type_hints(
                callable_,
                globalns=module_globals,
            ).values()
        )
    for public_type in public_types:
        rendered.append(str(inspect.signature(public_type)))
        public_hints = {
            name: annotation
            for name, annotation in get_type_hints(public_type).items()
            if not name.startswith("_")
        }
        rendered.extend(repr(annotation) for annotation in public_hints.values())

    assert "scopecat.compiler" not in "\n".join(rendered)


@pytest.mark.parametrize(
    "change",
    ("missing", "duplicate", "foreign", "point_mismatch", "foreign_point"),
)
def test_entry_mapping_failures_are_rejected_before_any_effect(change: str) -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
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
            replace(selected[1], point=selected[0].point),
        )
    else:
        foreign_point = _preparation(
            program_id="foreign-domain-result-mapping"
        ).context.points[0]
        selected = (
            selected[0],
            replace(selected[1], point=foreign_point),
        )

    with pytest.raises(ValueError):
        _seal(preparation, batch, selected, acquisition_bindings)


@pytest.mark.parametrize(
    "change",
    ("missing", "duplicate", "foreign", "foreign_use", "use_mismatch"),
)
def test_acquisition_mapping_failures_are_rejected_before_any_effect(
    change: str,
) -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
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
    elif change == "foreign_use":
        foreign_use = _preparation(
            program_id="foreign-domain-result-use"
        ).context.direct_product_uses[0]
        selected = (
            *selected[:-1],
            replace(selected[-1], product_use=foreign_use),
        )
    else:
        selected = (
            *selected[:-1],
            replace(selected[-1], product_use=selected[-2].product_use),
        )

    with pytest.raises(ValueError):
        _seal(preparation, batch, entry_bindings, selected)


def test_foreign_address_parent_is_derived_and_rejected() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    foreign_address = TargetAcquisitionAddress(
        entry_id=TargetCompileEntryId("foreign-entry"),
        slot_id=acquisition_bindings[-1].address.slot_id,
    )
    selected = (
        *acquisition_bindings[:-1],
        replace(acquisition_bindings[-1], address=foreign_address),
    )

    with pytest.raises(ValueError, match="exactly cover adapter result addresses"):
        _seal(preparation, batch, entry_bindings, selected)


def test_quantum_mapping_types_close_runtime_identity_spaces() -> None:
    _, _, entry_bindings, acquisition_bindings = _valid_inputs()
    with pytest.raises(TypeError, match="TargetCompileEntryId"):
        CircuitTargetEntryPointBinding(
            cast("TargetCompileEntryId", TargetId("wrong-space")),
            entry_bindings[0].point,
        )
    with pytest.raises(TypeError, match="DomainPointRef"):
        CircuitTargetEntryPointBinding(
            entry_bindings[0].entry_id,
            cast("DomainPointRef", object()),
        )
    with pytest.raises(TypeError, match="TargetAcquisitionAddress"):
        CircuitTargetAcquisitionUseBinding(
            cast("TargetAcquisitionAddress", object()),
            acquisition_bindings[0].product_use,
        )
    with pytest.raises(TypeError, match="DomainProductUseRef"):
        CircuitTargetAcquisitionUseBinding(
            acquisition_bindings[0].address,
            cast("DomainProductUseRef", object()),
        )

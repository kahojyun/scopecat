from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import MaterializedLinkedPointBatch, link_program
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
    DomainPreparationBuilder,
    DomainResultMapping,
)
from scopecat.sdk.domain.context import (
    make_domain_batch_context_internal,
    project_domain_plan_internal,
)
from scopecat.sdk.domain.invocation import materialize_linked_points

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    PulseEventId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.calibrations import CalibrationCatalog
from scopecat_quantum.program_results import (
    QuantumTargetAcquisitionUseBinding,
    QuantumTargetEntryPointBinding,
    QuantumTargetResultMapping,
    bind_compiled_quantum_target,
    seal_quantum_target_result_mapping,
)
from scopecat_quantum.program_targets import (
    PreparedQuantumTargetBatch,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
)
from scopecat_quantum.programs import (
    AuthoredPulseAcquisitionProvenance,
    PulseBlock,
    QuantumProgramIR,
    lower_quantum_program_to_pulses,
    verify_quantum_program,
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
    *, program_id: str = "mixed-program-result-mapping"
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
    product = product_output("result", dtype="complex128")
    product_use, record_use = record_product(product, record_id="record")
    domain_program_id = DomainProgramId(SymbolId(local_id="program"))
    domain_call_id = DomainCallId(SymbolId(local_id="execute"))
    producer_id = product_producer_id("result-producer")
    program = TypedProgram(
        id=program_id,
        kind="mixed_quantum_mapping_test",
        point_domain=point_domain,
        product_defs=(product,),
        domain_programs=(
            TypedDomainProgram(
                id=domain_program_id,
                dialect_id="test.quantum.mixed-result-mapping",
                dialect_version="1",
                body=object(),
                result_ports=(DomainResultPortDef("result"),),
            ),
        ),
        domain_calls=(
            TypedDomainCall(
                id=domain_call_id,
                program_id=domain_program_id,
                results=(
                    TypedDomainResultBinding(
                        id="result",
                        product_id=product.id,
                        producer_id=producer_id,
                        product_use_ids=(product_use.id,),
                    ),
                ),
            ),
        ),
        domain_product_producers=(
            DomainProductProducer(
                id=producer_id,
                product_id=product.id,
                call_id=domain_call_id,
                result_id="result",
            ),
        ),
        product_uses=(product_use,),
        record_uses=(record_use,),
    )
    environment = validate_config_environment(
        load_config_profile(
            _WORKSPACE / "fixtures" / "core" / "simple_scan" / "config-profile.json"
        )
    )
    linked_points = materialize_linked_points(link_program(program, environment))
    projection = project_domain_plan_internal(linked_points)
    call = projection.view(linked_points).require_one_call(
        dialect_id="test.quantum.mixed-result-mapping"
    )
    offer = DomainExecutionOffer.for_call(call, max_points_per_batch=2)
    context = make_domain_batch_context_internal(
        projection,
        MaterializedLinkedPointBatch(linked_points, (0, 1)),
        offer,
        adapter_id="test.quantum.mixed-result-mapping",
        batch_ordinal=0,
    )
    return context.new_preparation()


def _prepared(entry_id: str, source_program_id: str):
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(Q0),
    )
    duration = Quantity(4, "ns")
    template = PulseProgram(
        id=PulseProgramId(f"{source_program_id}-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("readout"),
                    signal=ReadoutSignal(Q0),
                    envelope=Constant(
                        duration=duration,
                        amplitude=Quantity(0.2, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("acquire"),
                    signal=slot.signal,
                    slot_id=slot.id,
                    duration=duration,
                ),
            )
        ),
        acquisition_slots=(slot,),
    )
    source = QuantumProgramIR(
        id=QuantumProgramId(source_program_id),
        body=PulseBlock(
            id=CircuitOperationId("inline-readout"),
            pulse_template=template,
        ),
    )
    lowered = lower_quantum_program_to_pulses(
        verify_quantum_program(source, ()),
        CalibrationCatalog(),
        output_id=PulseProgramId(f"{source_program_id}-pulses"),
    )
    return prepare_quantum_target_entry(TargetCompileEntryId(entry_id), lowered)


def _batch() -> PreparedQuantumTargetBatch:
    entries = (
        _prepared("entry-b", "mixed-source-b"),
        _prepared("entry-a", "mixed-source-a"),
    )
    return prepare_quantum_target_batch(
        entries,
        target_id=TargetId("target"),
        compiler_id=TargetCompilerId("compiler.v1"),
        capability_fingerprint="capabilities:v1",
        repetitions=11,
    )


def _valid_inputs():
    preparation = _preparation()
    batch = _batch()
    points = preparation.context.points
    product_use = preparation.context.direct_product_uses[0]
    entry_bindings = (
        QuantumTargetEntryPointBinding(batch.entries[0].id, points[1]),
        QuantumTargetEntryPointBinding(batch.entries[1].id, points[0]),
    )
    acquisition_bindings = tuple(
        QuantumTargetAcquisitionUseBinding(address, product_use)
        for address in batch.acquisition_addresses
    )
    return preparation, batch, entry_bindings, acquisition_bindings


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


def test_mapping_preserves_exact_inventory_order_and_mixed_source_origins() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()

    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )

    assert mapping.batch is batch
    assert isinstance(mapping.domain_mapping, DomainResultMapping)
    assert mapping.domain_mapping.context is preparation.context
    assert tuple(
        (entry.entry_address, entry.result_addresses)
        for entry in mapping.domain_mapping.target_entries
    ) == tuple((entry.id, entry.acquisition_addresses) for entry in batch.entries)
    assert tuple(entry.entry_address for entry in mapping.domain_mapping.entries) == (
        batch.entries[1].id,
        batch.entries[0].id,
    )
    assert {result.result_address for result in mapping.domain_mapping.results} == set(
        batch.acquisition_addresses
    )
    assert tuple(entry.source_program_id for entry in mapping.batch.entries) == (
        QuantumProgramId("mixed-source-b"),
        QuantumProgramId("mixed-source-a"),
    )
    for result in mapping.domain_mapping.results:
        origin = mapping.batch.acquisition_origin_for(result.result_address)
        assert isinstance(
            origin.provenance,
            AuthoredPulseAcquisitionProvenance,
        )
        assert (
            origin.source_program_id
            == mapping.batch.entry_for(result.entry_address).source_program_id
        )


def test_mapping_rejects_another_batch_order() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    reversed_batch = prepare_quantum_target_batch(
        tuple(reversed(batch.entries)),
        target_id=batch.request.target_id,
        compiler_id=batch.request.compiler_id,
        capability_fingerprint=batch.request.capability_fingerprint,
        repetitions=batch.request.repetitions,
    )

    with pytest.raises(ValueError, match="exact prepared batch inventory"):
        QuantumTargetResultMapping(reversed_batch, mapping.domain_mapping)


@pytest.mark.parametrize("change", ("missing", "duplicate", "foreign"))
def test_entry_mapping_requires_exact_coverage(change: str) -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    selected = entry_bindings
    if change == "missing":
        selected = selected[:-1]
    elif change == "duplicate":
        selected = (selected[0], selected[0])
    else:
        selected = (
            selected[0],
            replace(selected[1], entry_id=TargetCompileEntryId("foreign")),
        )

    with pytest.raises(ValueError):
        seal_quantum_target_result_mapping(
            preparation,
            batch,
            selected,
            acquisition_bindings,
        )


@pytest.mark.parametrize("change", ("missing", "duplicate", "foreign"))
def test_acquisition_mapping_requires_exact_qualified_addresses(change: str) -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    selected = acquisition_bindings
    if change == "missing":
        selected = selected[:-1]
    elif change == "duplicate":
        selected = (selected[0], selected[0])
    else:
        selected = (
            selected[0],
            replace(
                selected[1],
                address=TargetAcquisitionAddress(
                    entry_id=batch.entries[1].id,
                    slot_id=AcquisitionSlotId("foreign"),
                ),
            ),
        )

    with pytest.raises(ValueError):
        seal_quantum_target_result_mapping(
            preparation,
            batch,
            entry_bindings,
            selected,
        )


def test_compiled_target_binding_retains_exact_request_and_source_order() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    compiled = _compile(batch.request)

    bound = bind_compiled_quantum_target(mapping, compiled)

    assert bound.mapping is mapping
    assert bound.compiled is compiled
    assert bound.compiled.request == mapping.batch.request
    assert bound.compiled.source_entry_ids == tuple(
        entry.id for entry in mapping.batch.entries
    )
    assert tuple(entry.source_program_id for entry in bound.mapping.batch.entries) == (
        QuantumProgramId("mixed-source-b"),
        QuantumProgramId("mixed-source-a"),
    )


def test_compiled_target_binding_rejects_another_request() -> None:
    preparation, batch, entry_bindings, acquisition_bindings = _valid_inputs()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    with pytest.raises(ValueError, match="exactly match the mapped quantum batch"):
        bind_compiled_quantum_target(
            mapping,
            _compile(replace(batch.request, repetitions=12)),
        )

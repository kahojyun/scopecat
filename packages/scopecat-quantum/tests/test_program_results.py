from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    LinkedPointMaterializer,
    link_verified_program,
)
from scopecat.compiler.relations.point_domain import point_literal_rows
from scopecat.compiler.semantic.model import (
    DomainProgramId,
    DomainResultPortDef,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    product_output,
    record_product,
)
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar, Table, TableColumn
from scopecat.sdk.domain import (
    DomainPreparationBuilder,
    DomainResultMapping,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_request,
)

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
from scopecat_quantum.program_results import (
    CompiledQuantumTarget,
    QuantumTargetEntryPointBinding,
    QuantumTargetResultMapping,
    QuantumTargetResultUseBinding,
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
from scopecat_quantum.pulse_implementations import ResolvedPulseImplementations
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
from scopecat_quantum.pulses import Sequence as PulseSequence
from scopecat_quantum.result_collections import ResultCollection
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetAcquisitionAddress,
    TargetCompileRequest,
    compile_target,
    target_result_acquisition_addresses,
    target_result_entry_id,
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
        root=point_literal_rows(
            point_type.columns,
            (
                (10.0,),
                (20.0,),
            ),
        )
    )
    product = product_output("result", dtype="complex128")
    product_use, record_use = record_product(product, record_id="record")
    domain_program_id = DomainProgramId(SymbolId(local_id="program"))
    program = CoreProgram(
        id=program_id,
        kind="mixed_quantum_mapping_test",
        point_domain=point_domain,
        product_defs=(product,),
        effects=(
            TypedDomainExecution(
                id="domain",
                program=TypedDomainProgram(
                    id=domain_program_id,
                    dialect_id="test.quantum.mixed-result-mapping",
                    dialect_version="1",
                    body=object(),
                    result_ports=(DomainResultPortDef("result"),),
                ),
                results=(
                    TypedDomainResultBinding(
                        id="result",
                        product_id=product.id,
                        product_use_ids=(product_use.id,),
                    ),
                ),
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
    linked_points = LinkedPointMaterializer(
        link_verified_program(
            seal_typed_program(program, phase=ProblemPhase.PLANNING),
            environment,
        )
    ).materialize()
    closure = domain_result_closure(linked_points.linked_plan.program, "domain")
    point_ordinals = (0, 1)
    materializer = LinkedPointMaterializer(linked_points.linked_plan)
    request = make_domain_compile_request(
        linked_points.linked_plan,
        "domain",
        closure,
        (point_ordinals,),
        lambda input_ids, ordinals, max_points: materializer.bind_domain_inputs(
            "domain",
            "program",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
        lambda input_ids, ordinals, max_points: materializer.bind_domain_inputs(
            "domain",
            "compiler",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
    )
    context = make_domain_batch_context(
        request,
        linked_points,
        point_ordinals,
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
        ResolvedPulseImplementations(),
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


def _prepared_repeated(entry_id: str, source_program_id: str):
    slots = tuple(
        AcquisitionSlot(
            id=AcquisitionSlotId(f"result-{index}"),
            kind=AcquisitionKind.INTEGRATED_IQ,
            signal=AcquireSignal(Q0),
        )
        for index in range(2)
    )
    duration = Quantity(4, "ns")
    template = PulseProgram(
        id=PulseProgramId(f"{source_program_id}-template"),
        body=PulseSequence(
            tuple(
                PulseParallel(
                    (
                        Play(
                            id=PulseEventId("readout", scope=(str(index),)),
                            signal=ReadoutSignal(Q0),
                            envelope=Constant(
                                duration=duration,
                                amplitude=Quantity(0.2, "arb"),
                            ),
                        ),
                        Acquire(
                            id=PulseEventId("acquire", scope=(str(index),)),
                            signal=slot.signal,
                            slot_id=slot.id,
                            duration=duration,
                        ),
                    )
                )
                for index, slot in enumerate(slots)
            )
        ),
        acquisition_slots=slots,
    )
    source = QuantumProgramIR(
        id=QuantumProgramId(source_program_id),
        body=PulseBlock(
            id=CircuitOperationId("repeated-readout"),
            pulse_template=template,
            acquisition_slot_bindings=tuple((slot.id, slot.id) for slot in slots),
        ),
    )
    lowered = lower_quantum_program_to_pulses(
        verify_quantum_program(source, ()),
        ResolvedPulseImplementations(),
        output_id=PulseProgramId(f"{source_program_id}-pulses"),
    )
    return prepare_quantum_target_entry(TargetCompileEntryId(entry_id), lowered)


def _valid_inputs():
    preparation = _preparation()
    batch = _batch()
    points = preparation.context.points
    product_use = preparation.context.direct_product_uses[0]
    entry_bindings = (
        QuantumTargetEntryPointBinding(batch.entries[0].id, points[1]),
        QuantumTargetEntryPointBinding(batch.entries[1].id, points[0]),
    )
    result_bindings = tuple(
        QuantumTargetResultUseBinding(address, product_use)
        for address in batch.acquisition_addresses
    )
    return preparation, batch, entry_bindings, result_bindings


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


def test_mapping_preserves_logical_order_and_mixed_source_origins() -> None:
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()

    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        result_bindings,
    )

    assert mapping.batch is batch
    assert isinstance(mapping.domain_mapping, DomainResultMapping)
    assert mapping.domain_mapping.context is preparation.context
    assert tuple(
        target_result_entry_id(result.result_address)
        for result in mapping.domain_mapping.results
    ) == (
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
        [address] = target_result_acquisition_addresses(result.result_address)
        origin = mapping.batch.acquisition_origin_for(address)
        assert isinstance(
            origin.provenance,
            AuthoredPulseAcquisitionProvenance,
        )
        assert (
            origin.source_program_id
            == mapping.batch.entry_for(
                target_result_entry_id(result.result_address)
            ).source_program_id
        )


def test_mapping_groups_one_logical_result_over_a_recursive_physical_axis() -> None:
    preparation = _preparation()
    entries = (
        _prepared_repeated("entry-b", "repeated-source-b"),
        _prepared_repeated("entry-a", "repeated-source-a"),
    )
    batch = prepare_quantum_target_batch(
        entries,
        target_id=TargetId("target"),
        compiler_id=TargetCompilerId("compiler.v1"),
        capability_fingerprint="capabilities:v1",
        repetitions=3,
    )
    points = preparation.context.points
    product_use = preparation.context.direct_product_uses[0]

    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        (
            QuantumTargetEntryPointBinding(entries[0].id, points[1]),
            QuantumTargetEntryPointBinding(entries[1].id, points[0]),
        ),
        tuple(
            QuantumTargetResultUseBinding(
                ResultCollection("round", entry.acquisition_addresses),
                product_use,
            )
            for entry in entries
        ),
    )

    assert tuple(
        target_result_entry_id(result.result_address)
        for result in mapping.domain_mapping.results
    ) == (entries[1].id, entries[0].id)
    assert tuple(
        address
        for result in mapping.domain_mapping.results
        for address in target_result_acquisition_addresses(result.result_address)
    ) == (*entries[1].acquisition_addresses, *entries[0].acquisition_addresses)


def test_mapping_accepts_adapter_owned_batch_reordering() -> None:
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        result_bindings,
    )
    reversed_batch = prepare_quantum_target_batch(
        tuple(reversed(batch.entries)),
        target_id=batch.request.target_id,
        compiler_id=batch.request.compiler_id,
        capability_fingerprint=batch.request.capability_fingerprint,
        repetitions=batch.request.repetitions,
    )

    rebound = QuantumTargetResultMapping(reversed_batch, mapping.domain_mapping)

    assert rebound.batch is reversed_batch
    assert rebound.domain_mapping is mapping.domain_mapping


@pytest.mark.parametrize("change", ("missing", "duplicate", "foreign"))
def test_entry_mapping_requires_exact_coverage(change: str) -> None:
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()
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

    with pytest.raises(ValueError, match="entry-point bindings"):
        seal_quantum_target_result_mapping(
            preparation,
            batch,
            selected,
            result_bindings,
        )


@pytest.mark.parametrize("change", ("missing", "duplicate", "foreign"))
def test_result_mapping_requires_exact_qualified_addresses(change: str) -> None:
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()
    selected = result_bindings
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

    with pytest.raises(
        ValueError,
        match=(
            r"logical output|point/product-use outputs|"
            r"prepared acquisition addresses"
        ),
    ):
        seal_quantum_target_result_mapping(
            preparation,
            batch,
            entry_bindings,
            selected,
        )


def test_compiled_target_binding_retains_exact_request_and_source_order() -> None:
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        result_bindings,
    )
    compiled = _compile(batch.request)

    bound = CompiledQuantumTarget(mapping, compiled)

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
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        result_bindings,
    )
    with pytest.raises(ValueError, match="exactly match the mapped quantum batch"):
        CompiledQuantumTarget(
            mapping,
            _compile(replace(batch.request, repetitions=12)),
        )

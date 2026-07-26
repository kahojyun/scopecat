from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.compiler.linking.linked import (
    link_program,
    materialize_linked_points,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedDomainResultBinding,
    record_product,
)
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.environment import build_config_environment
from scopecat.domain.program import DomainProgramDef, DomainResultPort
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.kernel.product_identity import product_id
from scopecat.kernel.value_types import Float, Scalar
from scopecat.measurements.products import ProductDef
from scopecat.sdk.domain import (
    DomainPreparationBuilder,
    DomainResultMapping,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_request,
    make_domain_call_view,
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
    MappedQuantumTarget,
    QuantumTargetEntryPointBinding,
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
    TargetAcquisitionAddress,
    TargetCompileRequest,
    target_result_acquisition_addresses,
    target_result_entry_id,
)

Q0 = QubitId("q0")
_REPO_ROOT = Path(__file__).parents[3]


def _preparation(
    *, program_id: str = "mixed-program-result-mapping"
) -> DomainPreparationBuilder:
    point_domain = PointDomain(
        root=point_axis_values(
            "coordinate",
            Scalar(Float()),
            (10.0, 20.0),
        )
    )
    product = ProductDef(id=product_id("result"), dtype="complex128")
    product_use, record_use = record_product(product, record_id="record")
    program = CoreProgram(
        id=program_id,
        kind="mixed_quantum_mapping_test",
        point_domain=point_domain,
        product_defs=(product,),
        effects=(
            TypedDomainExecution(
                id="domain",
                program=DomainProgramDef(
                    id="program",
                    dialect_id="test.quantum.mixed-result-mapping",
                    dialect_version="1",
                    body=object(),
                    result_ports=(DomainResultPort("result"),),
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
    environment = build_config_environment(
        load_config_snapshot_document(
            _REPO_ROOT / "fixtures" / "core" / "simple_scan" / "config-snapshot.json"
        )
    )
    linked_points = materialize_linked_points(link_program(program, environment))
    closure = domain_result_closure(linked_points.linked_plan.program, "domain")
    point_ordinals = (0, 1)
    call = make_domain_call_view(
        linked_points.linked_plan,
        "domain",
        closure,
    )
    request = make_domain_batch_request(
        call,
        linked_points,
        point_ordinals,
        batch_ordinal=0,
    )
    return request.new_preparation()


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
    product_use = preparation.context.product_uses[0]
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
) -> _TargetArtifact:
    compiler = _TargetCompiler(
        id=TargetCompilerId("compiler.v1"),
        target_id=TargetId("target"),
        capability_fingerprint="capabilities:v1",
    )
    return compiler.compile(request)


def test_mapping_preserves_logical_order_while_batch_retains_origins() -> None:
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()

    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        result_bindings,
    )

    assert isinstance(mapping, DomainResultMapping)
    assert mapping.context is preparation.context
    assert tuple(
        target_result_entry_id(result.result_address) for result in mapping.results
    ) == (
        batch.entries[1].id,
        batch.entries[0].id,
    )
    assert {result.result_address for result in mapping.results} == set(
        batch.acquisition_addresses
    )
    assert tuple(entry.source_program_id for entry in batch.entries) == (
        QuantumProgramId("mixed-source-b"),
        QuantumProgramId("mixed-source-a"),
    )
    entry_by_id = {entry.id: entry for entry in batch.entries}
    for result in mapping.results:
        [address] = target_result_acquisition_addresses(result.result_address)
        origin = batch.acquisition_origin_for(address)
        assert isinstance(
            origin.provenance,
            AuthoredPulseAcquisitionProvenance,
        )
        assert (
            origin.source_program_id
            == entry_by_id[
                target_result_entry_id(result.result_address)
            ].source_program_id
        )


def test_mapping_groups_one_logical_result_over_a_recursive_physical_axis() -> None:
    preparation = _preparation()
    entries = (
        _prepared_repeated("entry-b", "repeated-source-b"),
        _prepared_repeated("entry-a", "repeated-source-a"),
    )
    batch = prepare_quantum_target_batch(
        entries,
        repetitions=3,
    )
    points = preparation.context.points
    product_use = preparation.context.product_uses[0]

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
        target_result_entry_id(result.result_address) for result in mapping.results
    ) == (entries[1].id, entries[0].id)
    assert tuple(
        address
        for result in mapping.results
        for address in target_result_acquisition_addresses(result.result_address)
    ) == (*entries[1].acquisition_addresses, *entries[0].acquisition_addresses)


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


def test_mapped_target_retains_only_artifact_and_logical_mapping() -> None:
    preparation, batch, entry_bindings, result_bindings = _valid_inputs()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        result_bindings,
    )
    artifact = _compile(batch.request)

    mapped = MappedQuantumTarget(artifact, mapping)

    assert mapped.artifact is artifact
    assert mapped.mapping is mapping

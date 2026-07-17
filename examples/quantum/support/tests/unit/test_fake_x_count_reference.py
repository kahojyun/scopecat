from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
)
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
    DomainProgramId,
    DomainResultPortDef,
    MeasurementTransformId,
)
from scopecat.compiler.semantic.value_expressions import verify_table_value_expr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    DomainProductProducer,
    MeasurementTransformProductProducer,
)
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
    TypedProgram,
    product_output,
    record_product,
    shot_axis,
)
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.product_identity import product_producer_id, product_use
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Int, Scalar, Table, TableColumn
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    project_domain_plan,
)
from scopecat.sdk.domain.invocation import materialize_linked_points
from scopecat_quantum import (
    BinaryIqDiscriminator,
    GateParameterKind,
    IqCentroid,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.reference_experiments import (
    FakeXCountProductBinding,
    prepare_fake_x_count_reference,
)

from .demo_lab_experiment_testkit import link_program

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SHOTS = 5

_Q0 = quantum.qubit("q0")
_X_COUNT = quantum.scalar_input("x_count", GateParameterKind.INTEGER)
_X = quantum.single_qubit_gate("x")
_READOUT = quantum.measure(_Q0, result="iq_shots")
_PROGRAM = quantum.program(
    "fake-x-count-test",
    quantum.sequence(quantum.repeat(_X(_Q0), _X_COUNT), _READOUT),
)


def _linked_points():
    point_type = Table(
        columns=(TableColumn("program_length", Scalar(Int(minimum=0))),),
        min_rows=3,
        max_rows=3,
    )
    point_domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    (
                        {"program_length": 100},
                        {"program_length": 100},
                        {"program_length": 100},
                    )
                ),
                bindings=RelationTypeBindings(),
                expected_type=point_type,
            )
        )
    )
    iq_shots = product_output(
        "integrated_iq_shots",
        dtype="complex128",
        unit="ratio",
        axes=(shot_axis(_SHOTS),),
    )
    probability_0 = product_output("probability_0", unit="ratio")
    probability_1 = product_output("probability_1", unit="ratio")
    iq_use = product_use(iq_shots.id)
    probability_0_use, probability_0_record = record_product(probability_0)
    probability_1_use, probability_1_record = record_product(probability_1)
    program_id = DomainProgramId(SymbolId(local_id="fake-x-count-program"))
    authored_transform = binary_iq_probability_transform(
        "binary-iq-probability",
        iq_shots="integrated_iq_shots",
        probability_0="probability_0",
        probability_1="probability_1",
        discriminator=BinaryIqDiscriminator(
            state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
            state_1_centroid=IqCentroid(real=1.0, imag=0.0),
        ),
    )
    transform_id = MeasurementTransformId(SymbolId(local_id=authored_transform.id))
    iq_producer_id = product_producer_id("iq-shots-producer")
    probability_0_producer_id = product_producer_id("probability-0-producer")
    probability_1_producer_id = product_producer_id("probability-1-producer")
    program = TypedProgram(
        id="fake-x-count-reference",
        kind="fake_x_count_reference",
        point_domain=point_domain,
        product_defs=(iq_shots, probability_0, probability_1),
        domain_execution=TypedDomainExecution(
            program=TypedDomainProgram(
                id=program_id,
                dialect_id="test.quantum",
                dialect_version="1",
                body=_PROGRAM,
                result_ports=(DomainResultPortDef("iq_shots"),),
            ),
            results=(
                TypedDomainResultBinding(
                    id="iq_shots",
                    product_id=iq_shots.id,
                    producer_id=iq_producer_id,
                    product_use_ids=(iq_use.id,),
                ),
            ),
        ),
        measurement_transforms=(
            TypedMeasurementTransform(
                id=transform_id,
                semantic=authored_transform.semantic,
                rate="point",
                inputs=(
                    TypedMeasurementTransformInput(
                        id="iq_shots",
                        product_id=iq_shots.id,
                        product_use_id=iq_use.id,
                    ),
                ),
                outputs=(
                    TypedMeasurementTransformOutput(
                        id="probability_0",
                        product_id=probability_0.id,
                        producer_id=probability_0_producer_id,
                        product_use_ids=(probability_0_use.id,),
                    ),
                    TypedMeasurementTransformOutput(
                        id="probability_1",
                        product_id=probability_1.id,
                        producer_id=probability_1_producer_id,
                        product_use_ids=(probability_1_use.id,),
                    ),
                ),
            ),
        ),
        domain_product_producers=(
            DomainProductProducer(
                id=iq_producer_id,
                product_id=iq_shots.id,
                result_id="iq_shots",
            ),
        ),
        measurement_transform_product_producers=(
            MeasurementTransformProductProducer(
                id=probability_0_producer_id,
                product_id=probability_0.id,
                transform_id=transform_id,
                output_id="probability_0",
            ),
            MeasurementTransformProductProducer(
                id=probability_1_producer_id,
                product_id=probability_1.id,
                transform_id=transform_id,
                output_id="probability_1",
            ),
        ),
        product_uses=(iq_use, probability_0_use, probability_1_use),
        record_uses=(
            probability_0_record,
            probability_1_record,
            replace(probability_1_record, id="probability_1_alias"),
        ),
    )
    environment = validate_config_environment(
        load_config_profile(
            _REPO_ROOT / "fixtures/core/simple_scan/config-profile.json"
        )
    )
    linked_points = materialize_linked_points(link_program(program, environment))
    projection = project_domain_plan(linked_points)
    view = projection.view(linked_points)
    execution = view.require_execution(dialect_id="test.quantum")
    context = make_domain_batch_context(
        projection,
        MaterializedLinkedPointBatch(linked_points, (0, 1, 2)),
        adapter_id="test.fake-x-count",
        batch_ordinal=0,
    )
    [transform] = execution.measurement_transforms
    return context.new_preparation(), FakeXCountProductBinding(
        iq_shots=execution.result("iq_shots").product_uses,
        transform=transform,
    )


def test_fake_x_count_reference_pure_preparation_closes_target_and_measurements() -> (
    None
):
    preparation, products = _linked_points()
    programs = tuple(
        quantum.bind(_PROGRAM, {"x_count": count}).verified for count in (0, 1, 3)
    )
    prepared = prepare_fake_x_count_reference(
        preparation,
        products,
        acquisition_slot_id=_READOUT.result.acquisition_slot_id,
        programs=programs,
        x_counts=(0, 1, 3),
        shots=_SHOTS,
    )

    assert prepared.x_counts == (0, 1, 3)
    assert prepared.programs == programs
    assert prepared.programs[1].program.id.value == "fake-x-count-test"
    assert tuple(
        entry.target_entry.program.duration_seconds for entry in prepared.entries
    ) == (
        Decimal("8e-9"),
        Decimal("12e-9"),
        Decimal("20e-9"),
    )
    compiled = prepared.compiled_target.compiled
    target = prepared.invocation.target
    assert target.target_id == compiled.target_id.value
    assert target.compiler_id == compiled.compiler_id.value
    assert target.capability_fingerprint == compiled.capability_fingerprint
    assert target.artifact_id == compiled.artifact_id.value
    assert target.artifact_fingerprint == compiled.artifact_fingerprint
    assert prepared.invocation.payload is prepared.realization

    measurements = prepared.measurements
    probability_0_use = products.transform.output("probability_0").product_uses[0]
    probability_1_use = products.transform.output("probability_1").product_uses[0]
    assert measurements.mapping is prepared.compiled_target.mapping.domain_mapping
    assert measurements.source_product_uses == products.iq_shots
    assert measurements.derived_product_uses == (
        probability_0_use,
        probability_1_use,
    )
    assert measurements.product_uses == (
        *products.iq_shots,
        probability_0_use,
        probability_1_use,
    )
    [binding] = measurements.host_transforms
    assert binding.transform is products.transform
    assert binding.transform.id == "binary-iq-probability"
    assert tuple(port.product_use for port in binding.transform.inputs) == (
        products.iq_shots[0],
    )
    assert tuple(port.product_uses for port in binding.transform.outputs) == (
        (probability_0_use,),
        (probability_1_use,),
    )

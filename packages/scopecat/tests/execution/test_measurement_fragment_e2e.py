from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from scopecat.adapters.memory import (
    MemoryCollectionRepository,
    MemoryExecutionJournal,
    MemoryMeasurementRecordCommitter,
    MemoryPayloadEvidenceCommitter,
)
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import MaterializedLinkedPoints, link_program
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.value_expressions import verify_table_value_expr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.program import TypedProgram, product_output
from scopecat.compiler.typed.records import RecordUse
from scopecat.execution.local.engine import ExecutionEngine
from scopecat.execution.local.measurement_fragments import (
    bind_local_collection_fragment,
    local_collection_fragment,
)
from scopecat.execution.local.program import (
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    ExecutionProgram,
    PointProgram,
)
from scopecat.kernel.product_identity import ProductUse, product_use
from scopecat.kernel.value_types import Float, Scalar, Table, TableColumn
from scopecat.measurements.host_transforms import (
    BoundHostMeasurementTransformPlan,
    HostMeasurementTransformCall,
    HostMeasurementTransformFragmentBinding,
    HostMeasurementTransformImplementation,
    HostMeasurementTransformImplementationBinding,
    bind_host_measurement_transforms,
    execute_host_measurement_transforms,
    select_host_measurement_transforms,
)
from scopecat.measurements.projection import (
    bind_measurement_projection,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.recording import commit_projected_measurement_records
from scopecat.measurements.results import CoordinateValue
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.measurements.transform_model import (
    MeasurementTransformDef,
    MeasurementTransformInputPort,
    MeasurementTransformOutputPort,
    NativeMeasurementTransformId,
)
from scopecat.measurements.transform_verification import (
    verify_measurement_transform_graph,
)
from scopecat.measurements.values import (
    ProductValueFragmentDef,
    SelectedMeasurementValueAssembly,
    select_measurement_value_assembly,
)
from scopecat.records.measurement import MeasurementValue
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.invocation import materialize_linked_points
from scopecat.sdk.instruments import (
    CollectCommand,
    CollectProductRequest,
)
from tests.testkit.authoring import load_config
from tests.testkit.signal_instruments import TestSignalInstrument

_RUN_ID = "local-measurement-fragment-run"
_INSTRUMENT_ID = "source-0"
_LOCAL_FRAGMENT_ID = "local-source"
_TRANSFORM_FRAGMENT_ID = "scaled-derived"


@dataclass(frozen=True, slots=True)
class _Scenario:
    linked_points: MaterializedLinkedPoints
    source: ProductUse
    derived: ProductUse
    source_product: ProductDef
    derived_product: ProductDef


def _scenario() -> _Scenario:
    point_type = Table(
        columns=(TableColumn("x", Scalar(Float())),),
        min_rows=3,
        max_rows=3,
    )
    source_product = product_output("raw-signal", unit="ratio")
    derived_product = product_output("scaled-signal", unit="ratio")
    source = product_use(source_product.id)
    derived = product_use(derived_product.id)
    program = TypedProgram(
        id="local-measurement-fragment-e2e",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                verify_table_value_expr(
                    literal_rows(({"x": 10.0}, {"x": 20.0}, {"x": 30.0})),
                    bindings=RelationTypeBindings(),
                    expected_type=point_type,
                )
            )
        ),
        product_defs=(source_product, derived_product),
        product_uses=(source, derived),
        record_uses=(
            RecordUse(id="scaled", product_use_id=derived.id),
            RecordUse(id="scaled-alias", product_use_id=derived.id),
        ),
    )
    linked_points = materialize_linked_points(
        link_program(program, validate_config_environment(load_config()))
    )
    return _Scenario(
        linked_points=linked_points,
        source=source,
        derived=derived,
        source_product=source_product,
        derived_product=derived_product,
    )


def _source_only_execution_program(scenario: _Scenario) -> ExecutionProgram:
    points = scenario.linked_points.point_domain.points
    return ExecutionProgram(
        experiment_id="local-measurement-fragment-e2e",
        points=tuple(
            PointProgram(
                point_index=point.logical_ordinal,
                point_uid=point.logical_id.value,
                coordinates=cast("Mapping[str, CoordinateValue]", dict(point.row)),
                stages=(
                    CollectStage(
                        operations=(
                            _source_collect_operation(
                                scenario,
                                point_uid=point.logical_id.value,
                                point_index=point.logical_ordinal,
                                point_count=len(points),
                            ),
                        )
                    ),
                ),
            )
            for point in points
        ),
        product_uses=(scenario.source, scenario.derived),
        collection_product_use_ids=(scenario.source.id,),
        record_projections=(),
        resource_order=(_INSTRUMENT_ID,),
    )


def _source_collect_operation(
    scenario: _Scenario,
    *,
    point_uid: str,
    point_index: int,
    point_count: int,
) -> CollectOperation:
    operation_id = f"{point_uid}.collect.{_INSTRUMENT_ID}"
    return CollectOperation(
        operation_id=operation_id,
        instrument_id=_INSTRUMENT_ID,
        command=CollectCommand(
            operation_id=operation_id,
            instrument_id=_INSTRUMENT_ID,
            point_index=point_index,
            point_count=point_count,
            requests=[
                CollectProductRequest(
                    id="signal",
                    capability_id="scalar_signal",
                    unit="ratio",
                    dtype="float64",
                    metadata={"transport_hint": "local-only"},
                )
            ],
        ),
        result_bindings=(
            CollectionResultBinding(
                provider_key="signal",
                product_use_id=scenario.source.id,
                product_id=scenario.source.product_id,
            ),
        ),
    )


def _transform_plan(
    scenario: _Scenario,
    assembly: SelectedMeasurementValueAssembly,
    kernel_calls: list[HostMeasurementTransformCall],
) -> BoundHostMeasurementTransformPlan:
    transform = MeasurementTransformDef(
        id=NativeMeasurementTransformId("scale-local-signal"),
        semantic=MeasurementTransformSemanticContract(
            id="tests.scale_measurement",
            version="1",
            parameters={"factor": 2.0},
        ),
        rate="point",
        inputs=(
            MeasurementTransformInputPort(
                "source",
                scenario.source.id,
                scenario.source_product,
            ),
        ),
        outputs=(
            MeasurementTransformOutputPort(
                "derived",
                (scenario.derived.id,),
                scenario.derived_product,
            ),
        ),
    )

    def scale(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        kernel_calls.append(call)
        value = call.inputs["source"]
        if not isinstance(value, Quantity):
            raise TypeError("scale input must be a scalar quantity")
        return {
            "derived": Quantity(
                value=value.value * 2.0,
                unit=value.unit,
            )
        }

    implementation = HostMeasurementTransformImplementation(
        id="tests.scale_measurement.python.v1",
        semantic_id=transform.semantic.id,
        semantic_version=transform.semantic.version,
        rate="point",
        implementation_fingerprint="tests.scale_measurement.python.v1",
        validate_transform=lambda _transform: None,
        kernel=scale,
    )
    graph = verify_measurement_transform_graph(
        scenario.linked_points,
        (transform,),
    )
    selected = select_host_measurement_transforms(
        graph,
        (implementation,),
        (
            HostMeasurementTransformImplementationBinding(
                transform.id,
                implementation.id,
            ),
        ),
    )
    return bind_host_measurement_transforms(
        selected,
        assembly,
        (
            HostMeasurementTransformFragmentBinding(
                transform.id,
                _TRANSFORM_FRAGMENT_ID,
            ),
        ),
    )


def test_local_collection_reaches_neutral_transform_and_recording() -> None:
    scenario = _scenario()
    program = _source_only_execution_program(scenario)
    assembly = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=(scenario.source.id, scenario.derived.id),
        fragment_defs=(
            ProductValueFragmentDef(
                _LOCAL_FRAGMENT_ID,
                (scenario.source.id,),
            ),
            ProductValueFragmentDef(
                _TRANSFORM_FRAGMENT_ID,
                (scenario.derived.id,),
            ),
        ),
    )
    local_binding = bind_local_collection_fragment(
        assembly,
        _LOCAL_FRAGMENT_ID,
        program,
    )
    kernel_calls: list[HostMeasurementTransformCall] = []
    transform_plan = _transform_plan(scenario, assembly, kernel_calls)
    projection = bind_measurement_projection(
        select_measurement_projection(scenario.linked_points),
        assembly,
    )

    driver = TestSignalInstrument(instrument_id=_INSTRUMENT_ID)
    journal = MemoryExecutionJournal()
    readbacks = MemoryCollectionRepository()
    legacy_measurements = MemoryMeasurementRecordCommitter()
    engine_result = ExecutionEngine(
        run_id=_RUN_ID,
        program=program,
        drivers={driver.instrument_id: driver},
        descriptions={driver.instrument_id: driver.describe()},
        journal=journal,
        measurements=legacy_measurements,
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    local_fragment = local_collection_fragment(
        local_binding,
        run_id=_RUN_ID,
        repository=readbacks,
        receipts=readbacks.receipts,
    )
    transformed = execute_host_measurement_transforms(
        transform_plan,
        (local_fragment,),
    )
    projected = project_measurement_records(
        projection,
        transformed.values,
        run_id=_RUN_ID,
    )
    projected_committer = MemoryMeasurementRecordCommitter()
    committed = commit_projected_measurement_records(
        projected,
        projected_committer,
        journal,
    )

    points = scenario.linked_points.point_domain.points
    assert engine_result.status == "completed"
    assert engine_result.measurements == ()
    assert legacy_measurements.chunks == ()
    assert program.collection_product_use_ids == (scenario.source.id,)
    assert local_binding.collection_product_use_ids == (scenario.source.id,)
    assert transform_plan.source_fragment_ids == (local_binding.fragment_id,)
    assert len(driver.collect_commands) == len(points)
    assert len(readbacks.chunks) == len(points)
    assert len(readbacks.receipts) == len(points)
    assert all(
        tuple(request.id for request in command.requests) == ("signal",)
        for command in driver.collect_commands
    )

    assert local_fragment.fragment_id == _LOCAL_FRAGMENT_ID
    assert local_fragment.selection.linked_points is scenario.linked_points
    assert local_fragment.selection.fragment(_LOCAL_FRAGMENT_ID).product_use_ids == (
        scenario.source.id,
    )
    assert tuple(
        fragment.fragment_id for fragment in transformed.transform_fragments
    ) == (_TRANSFORM_FRAGMENT_ID,)
    assert transformed.transform_fragments[0].selection.fragment(
        _TRANSFORM_FRAGMENT_ID
    ).product_use_ids == (scenario.derived.id,)
    assert transformed.values.product_use_ids == (
        scenario.source.id,
        scenario.derived.id,
    )
    assert [(call.logical_point_id, call.point_index) for call in kernel_calls] == [
        (point.logical_id, point.logical_ordinal) for point in points
    ]

    assert len(projected.records) == len(points)
    assert len(projected_committer.chunks) == len(points)
    assert len(committed.receipts) == len(points)
    for record, expected in zip(projected.records, (1.0, 2.0, 1.0), strict=True):
        assert set(record.observables) == {"scaled", "scaled-alias"}
        assert record.observables["scaled"] == Quantity(expected, "ratio")
        assert record.observables["scaled-alias"] == record.observables["scaled"]
        assert record.logical_point_id == points[record.point_index].logical_id.value
        assert record.metadata == {}

    recording_entries = tuple(
        entry for entry in journal.entries if entry.stage == "record_measurement"
    )
    assert len(recording_entries) == 2 * len(points)
    producer_neutral_projection = repr(
        (
            tuple(
                (
                    value.logical_point_id,
                    value.product_use_id,
                    value.product_id,
                    value.value,
                )
                for value in local_fragment.values
            ),
            kernel_calls,
            projected.records,
            recording_entries,
        )
    )
    for source_only_term in (
        _INSTRUMENT_ID,
        "tests.signal_instrument",
        "test_offline",
        "transport_hint",
    ):
        assert source_only_term not in producer_neutral_projection

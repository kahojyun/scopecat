from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest
from scopecat_testkit.measurement_assembly import (
    assembled_measurement_values_for_all_uses,
    measurement_assembly_scenario,
    measurement_value_candidates,
)

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.points import AcceptedRunPoint
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Array,
    ArrayDimension,
    Float,
    Scalar,
    TableColumn,
)
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)
from scopecat.measurements.products import ProductAxisDef
from scopecat.measurements.projection import (
    MeasurementProjection,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.records import (
    ValueRecordCandidate,
    ValueRecordUse,
    expected_dataset_schema,
)
from scopecat.measurements.results import (
    InstrumentAcquisitionEvidence,
    MeasurementPointDomainAxis,
    MeasurementPointDomainLinearSource,
    MeasurementPointDomainRangeSource,
    MeasurementPointDomainValuesSource,
    MeasurementProductGridPointDomain,
    MeasurementScalar,
)
from scopecat.measurements.values import (
    seal_measurement_values,
)
from scopecat.planning.measurement_projection import (
    project_run_point_catalog,
)
from scopecat.program.point_domain import (
    point_axis_linear,
    point_axis_range,
    point_axis_values,
)
from scopecat.records.measurement import (
    MeasurementArray,
    measurement_point_axis_values,
)


def test_projection_keeps_all_records_without_narrowing_the_value_catalog() -> None:
    scenario = measurement_assembly_scenario(use_count=3)
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    assert projection.catalog.product_use_ids == tuple(use.id for use in scenario.uses)
    assert tuple(record.id for record in projection.records) == (
        "primary",
        "alias",
        "secondary",
    )


def test_projection_records_symbolic_scalar_values_without_product_provenance() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0, 1.0), use_count=0)
    value_id = ValueId(SymbolId(local_id="score"))
    value_record = ValueRecordUse(
        id="score",
        value_id=value_id,
        source_value_id="analysis/score",
        value_type=Scalar(Float()),
        requires_execution=True,
    )
    candidates = tuple(
        ValueRecordCandidate(
            logical_point_id=point.logical_id,
            value_id=value_id,
            value=float(point.ordinal + 1),
        )
        for point in scenario.points
    )
    projection = select_measurement_projection(
        scenario.catalog,
        (value_record,),
    )
    values = seal_measurement_values(scenario.catalog, (), points=scenario.points)

    projected = project_measurement_records(
        projection,
        values,
        run_id="value-record-run",
        points=scenario.points,
        value_candidates=candidates,
    )

    assert [record.observables["score"] for record in projected.records] == [
        MeasurementScalar.create(dtype="float64", value=1.0),
        MeasurementScalar.create(dtype="float64", value=2.0),
    ]
    schema = projection.schema
    assert schema is not None
    variable = next(item for item in schema.variables if item.id == "score")
    assert variable.source_product_id is None
    assert variable.source_value_id == "analysis/score"


def test_projection_records_symbolic_array_values_with_local_dimensions() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=0)
    value_id = ValueId(SymbolId(local_id="trace"))
    value_record = ValueRecordUse(
        id="trace",
        value_id=value_id,
        source_value_id="analysis/trace",
        value_type=Array(
            dtype="float64",
            dimensions=(ArrayDimension("sample", 3, kind="time", unit="ns"),),
            unit="V",
        ),
        requires_execution=True,
    )
    [point] = scenario.points
    projection = select_measurement_projection(
        scenario.catalog,
        (value_record,),
    )
    values = seal_measurement_values(scenario.catalog, (), points=scenario.points)

    projected = project_measurement_records(
        projection,
        values,
        run_id="array-value-record-run",
        points=scenario.points,
        value_candidates=(
            ValueRecordCandidate(
                logical_point_id=point.logical_id,
                value_id=value_id,
                value=np.asarray([1.0, 2.0, 3.0]),
            ),
        ),
    )

    trace = projected.records[0].observables["trace"]
    assert isinstance(trace, MeasurementArray)
    assert trace.unit == "V"
    assert trace.values.tolist() == [1.0, 2.0, 3.0]
    schema = projection.schema
    assert schema is not None
    dimensions = [
        (dimension.id, dimension.kind, dimension.size)
        for dimension in schema.dimensions
    ]
    assert dimensions == [
        ("point", "point", 1),
        ("sample", "time", 3),
    ]
    variable = next(item for item in schema.variables if item.id == "trace")
    assert variable.dims == ("point", "sample")


def test_projection_schema_persists_ordered_product_grid_axes() -> None:
    scenario = measurement_assembly_scenario(
        point_values=(0.0, 1.0, 2.0),
        use_count=1,
    )
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    schema = projection.schema

    assert schema is not None
    assert schema.point_domain == MeasurementProductGridPointDomain(
        axes=[
            MeasurementPointDomainAxis(
                id="x",
                size=3,
                source=MeasurementPointDomainValuesSource(
                    values=[
                        MeasurementScalar.create(value=value)
                        for value in (0.0, 1.0, 2.0)
                    ]
                ),
            ),
            MeasurementPointDomainAxis(
                id="opaque",
                size=1,
                source=MeasurementPointDomainValuesSource(values=[None]),
            ),
        ]
    )
    assert schema.metadata == {"experiment_id": "test.bound-program"}


def test_product_grid_schema_infers_coordinate_unit_from_axis_values() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0, 1.0), use_count=1)
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    schema = expected_dataset_schema(
        experiment_id="quantity-axis",
        point_count=2,
        records=projection.records,
        point_coordinate_columns=(TableColumn("frequency", Scalar(QuantityType())),),
        point_domain_axes=(
            point_axis_values(
                "frequency",
                Scalar(QuantityType()),
                (
                    Quantity(value=4.9, unit="GHz"),
                    Quantity(value=5.1, unit="GHz"),
                ),
            ),
        ),
    )

    assert schema is not None
    frequency = next(
        variable for variable in schema.variables if variable.id == "frequency"
    )
    assert frequency.unit == "GHz"


def test_product_grid_schema_retains_large_range_as_compact_source() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=1)
    projection = select_measurement_projection(scenario.catalog, scenario.records)
    point_count = 1_000_000

    schema = expected_dataset_schema(
        experiment_id="compact-range-axis",
        point_count=point_count,
        records=projection.records,
        point_coordinate_columns=(TableColumn("index", Scalar(Float())),),
        point_domain_axes=(
            point_axis_range(
                "index",
                Scalar(Float()),
                0.0,
                float(point_count - 1),
                point_count,
            ),
        ),
    )

    assert schema is not None
    assert isinstance(schema.point_domain, MeasurementProductGridPointDomain)
    [axis] = schema.point_domain.axes
    assert axis.size == point_count
    assert axis.source == MeasurementPointDomainRangeSource(
        start=MeasurementScalar.create(value=0.0),
        stop=MeasurementScalar.create(value=float(point_count - 1)),
    )


def test_product_grid_schema_round_trips_centered_axis_generation() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=1)
    projection = select_measurement_projection(scenario.catalog, scenario.records)
    frequency_type = Scalar(QuantityType(unit="GHz"))

    schema = expected_dataset_schema(
        experiment_id="centered-axis",
        point_count=3,
        records=projection.records,
        point_coordinate_columns=(TableColumn("frequency", frequency_type),),
        point_domain_axes=(
            point_axis_linear(
                "frequency",
                frequency_type,
                Quantity(5.0, "GHz"),
                Quantity(2.0, "GHz"),
                3,
            ),
        ),
    )

    assert schema is not None
    restored = type(schema).model_validate(schema.model_dump(mode="json"))
    assert isinstance(restored.point_domain, MeasurementProductGridPointDomain)
    [axis] = restored.point_domain.axes
    assert axis.source == MeasurementPointDomainLinearSource(
        center=MeasurementScalar.create(value=5.0, unit="GHz"),
        span=MeasurementScalar.create(value=2.0, unit="GHz"),
    )
    assert measurement_point_axis_values(axis) == tuple(
        MeasurementScalar.create(value=value, unit="GHz") for value in (4.0, 5.0, 6.0)
    )


def test_product_grid_schema_rejects_inconsistent_coordinate_units() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0, 1.0), use_count=1)
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    with pytest.raises(ValueError, match="inconsistent quantity units"):
        expected_dataset_schema(
            experiment_id="quantity-axis",
            point_count=2,
            records=projection.records,
            point_coordinate_columns=(
                TableColumn("frequency", Scalar(QuantityType())),
            ),
            point_domain_axes=(
                point_axis_values(
                    "frequency",
                    Scalar(QuantityType()),
                    (
                        Quantity(value=4.9, unit="GHz"),
                        Quantity(value=5_100.0, unit="MHz"),
                    ),
                ),
            ),
        )


def test_projection_preserves_order_across_product_and_value_records() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=1)
    value_id = ValueId(SymbolId(local_id="score"))
    projection = select_measurement_projection(
        scenario.catalog,
        (
            ValueRecordUse(
                id="score",
                value_id=value_id,
                source_value_id="analysis/score",
                value_type=Scalar(Float()),
            ),
            *scenario.records,
        ),
    )

    assert [record.id for record in projection.records] == [
        "score",
        "primary",
        "alias",
    ]


def test_value_projection_contract_uses_stable_semantic_source_identity() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=0)

    def projection_for(transient_id: str) -> MeasurementProjection:
        return select_measurement_projection(
            scenario.catalog,
            (
                ValueRecordUse(
                    id="score",
                    value_id=ValueId(
                        SymbolId(scope=("values",), local_id=transient_id)
                    ),
                    source_value_id="analysis/score",
                    value_type=Scalar(Float()),
                ),
            ),
        )

    first = projection_for("first-runtime-value")
    second = projection_for("second-runtime-value")

    assert first.contract_fingerprint == second.contract_fingerprint
    assert first.schema == second.schema


def test_projection_schema_keeps_the_complete_planned_point_count() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0, 1.0, 2.0), use_count=2)
    projection = select_measurement_projection(
        scenario.catalog,
        scenario.records,
    )

    selected_points = project_run_point_catalog(scenario.bound_points, (1, 2)).points
    ordinals = tuple(point.ordinal for point in selected_points)
    assert ordinals == (1, 2)
    assert projection.coordinate_ids == ("x",)
    schema = projection.schema
    assert schema is not None
    assert (
        next(
            dimension for dimension in schema.dimensions if dimension.id == "point"
        ).size
        == 3
    )


def test_dimension_identity_changes_catalog_and_projection_contracts() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    product = scenario.catalog.product_defs[0]
    first_product = replace(
        product,
        axes=(
            ProductAxisDef(
                id="sample",
                dimension_id="product/first/sample",
                kind="sample",
                size=2,
            ),
        ),
    )
    second_product = replace(
        first_product,
        axes=(
            replace(
                first_product.axes[0],
                dimension_id="product/second/sample",
            ),
        ),
    )
    first_catalog = replace(
        scenario.catalog,
        product_defs=(first_product, *scenario.catalog.product_defs[1:]),
    )
    second_catalog = replace(
        scenario.catalog,
        product_defs=(second_product, *scenario.catalog.product_defs[1:]),
    )

    assert first_catalog.contract_fingerprint != second_catalog.contract_fingerprint
    assert (
        select_measurement_projection(
            first_catalog, scenario.records
        ).contract_fingerprint
        != select_measurement_projection(
            second_catalog, scenario.records
        ).contract_fingerprint
    )


def test_recording_group_is_part_of_the_projection_contract_and_schema() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    ungrouped = select_measurement_projection(scenario.catalog, scenario.records)
    grouped_records = tuple(
        replace(record, recording_group_id="readout/sweep")
        for record in scenario.records
    )
    grouped = select_measurement_projection(scenario.catalog, grouped_records)

    assert grouped.contract_fingerprint != ungrouped.contract_fingerprint
    schema = grouped.schema
    assert schema is not None
    assert {variable.recording_group_id for variable in schema.variables} == {
        None,
        "readout/sweep",
    }
    assert {
        variable.recording_group_id
        for variable in schema.variables
        if variable.id in {record.id for record in grouped_records}
    } == {"readout/sweep"}


def test_record_aliases_project_one_value_twice_without_expanding_assembly() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="projection-run",
        points=scenario.points,
    )

    assert len(assembled.values) == len(scenario.bound_points.point_domain.points) * 3
    assert len(projected.records) == 2
    assert [record.point_index for record in projected.records] == [0, 1]
    for record in projected.records:
        assert set(record.observables) == {"primary", "alias", "secondary"}
        assert record.observables["primary"] == record.observables["alias"]


def test_record_coordinates_project_as_inner_coordinate_variables() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    observable_projection = select_measurement_projection(
        scenario.catalog,
        scenario.records,
    )
    records = (
        replace(scenario.records[0], role="coordinate"),
        *scenario.records[1:],
    )
    projection = select_measurement_projection(scenario.catalog, records)

    assert projection.contract_fingerprint != observable_projection.contract_fingerprint
    projected = project_measurement_records(
        projection,
        assembled,
        run_id="coordinate-product-run",
        points=scenario.points,
    )

    schema = projection.schema
    assert schema is not None
    assert schema.primary_coordinates == ("x", "primary")
    assert schema.primary_observables == ("alias", "secondary")
    variables = {variable.id: variable for variable in schema.variables}
    assert variables["primary"].role == "coordinate"
    assert variables["primary"].dims == ("point",)
    for record in projected.records:
        assert set(record.coordinates) == {"x", "primary"}
        assert set(record.observables) == {"alias", "secondary"}
        assert record.coordinates["primary"] == record.observables["alias"]


def test_projection_filters_non_coordinate_point_values() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="coordinate-filter-run",
        points=scenario.points,
    )

    assert [record.coordinates for record in projected.records] == [
        {"x": MeasurementScalar.create(dtype="float64", value=0.0)},
        {"x": MeasurementScalar.create(dtype="float64", value=1.0)},
    ]
    assert all("opaque" not in record.coordinates for record in projected.records)


def test_record_metadata_changes_schema_not_product_value_assembly() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    assert len(assembled.values) == 6
    first_value = assembled.values[0]
    assert first_value.product.metadata == {"definition": 0}
    assert "projection" not in first_value.product.metadata
    schema = projection.schema
    assert schema is not None
    variables = {variable.id: variable for variable in schema.variables}
    assert variables["primary"].metadata == {
        "definition": 0,
        "projection": "primary",
    }
    assert variables["alias"].metadata == {
        "definition": 0,
        "projection": "alias",
    }
    assert (
        variables["primary"].source_product_id
        == scenario.catalog.product_defs[0].id.qualified_name
    )
    assert (
        variables["alias"].source_product_id == variables["primary"].source_product_id
    )
    assert variables["x"].source_product_id is None


def test_projection_retains_acquisition_evidence_for_each_record_alias() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)
    candidates = list(measurement_value_candidates(scenario, scenario.uses))
    evidence = InstrumentAcquisitionEvidence(
        command_id="collect-signal",
        instrument_id="readout",
        interface_id="test.scalar_signal/v1",
        component_path=("channel-1",),
        acquisition_id="sample",
        result_id="signal",
        started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
    )
    candidates[0] = replace(candidates[0], evidence=evidence)
    assembled = seal_measurement_values(
        scenario.catalog,
        candidates,
        points=scenario.points,
    )
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="acquisition-evidence-run",
        points=scenario.points,
    )

    assert projected.records[0].acquisition_evidence == {
        "primary": evidence,
        "alias": evidence,
    }


def test_duplicate_coordinate_rows_keep_distinct_canonical_point_indices() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses(
        point_values=(4.0, 4.0)
    )
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="duplicate-coordinate-run",
        points=scenario.points,
    )

    assert [record.point_index for record in projected.records] == [0, 1]
    assert [record.coordinates for record in projected.records] == [
        {"x": MeasurementScalar.create(dtype="float64", value=4.0)},
        {"x": MeasurementScalar.create(dtype="float64", value=4.0)},
    ]
    schema = projection.schema
    assert schema is not None
    assert isinstance(schema.point_domain, MeasurementProductGridPointDomain)
    source = schema.point_domain.axes[0].source
    assert isinstance(source, MeasurementPointDomainValuesSource)
    assert source.values == (
        MeasurementScalar.create(dtype="float64", value=4.0),
        MeasurementScalar.create(dtype="float64", value=4.0),
    )
    assert (
        scenario.bound_points.point_domain.points[0].logical_id
        != scenario.bound_points.point_domain.points[1].logical_id
    )


def test_projection_emits_complete_run_records() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)
    assembled = seal_measurement_values(
        scenario.catalog,
        measurement_value_candidates(scenario, scenario.uses),
        points=scenario.points,
    )
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="complete-record-run",
        points=scenario.points,
    )

    assert len(projected.records) == 1
    record = projected.records[0]
    assert record.run_id == "complete-record-run"
    assert record.point_index == 0
    assert record.coordinates == {
        "x": MeasurementScalar.create(dtype="float64", value=0.0)
    }
    primary = record.observables["primary"]
    assert isinstance(primary, MeasurementScalar)
    assert primary.dtype == "float64"
    assert primary.unit == "ratio"
    assert primary.value == 0.0


def test_projection_normalizes_compiler_coordinates_to_measurement_scalars() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses(point_values=(0.0,))
    projection = select_measurement_projection(scenario.catalog, scenario.records)
    original = scenario.points[0]
    cases = (
        (
            Quantity(value=5.0, unit="GHz"),
            MeasurementScalar.create(dtype="float64", unit="GHz", value=5.0),
        ),
        (
            EntityRef(
                id="q0",
                kind="qubit",
                metadata={"label": "readout"},
            ),
            MeasurementScalar.create(
                dtype="string",
                value="q0",
                metadata={
                    "entity": {
                        "kind": "qubit",
                        "metadata": {"label": "readout"},
                    }
                },
            ),
        ),
        (
            EntityRef(id="q0"),
            MeasurementScalar.create(
                dtype="string",
                value="q0",
                metadata={"entity": {}},
            ),
        ),
        (True, MeasurementScalar.create(dtype="bool", value=True)),
        (2, MeasurementScalar.create(dtype="int64", value=2)),
        (2.5, MeasurementScalar.create(dtype="float64", value=2.5)),
        ("high", MeasurementScalar.create(dtype="string", value="high")),
    )

    for source, expected in cases:
        projected = project_measurement_records(
            projection,
            assembled,
            run_id="coordinate-normalization-run",
            points=(AcceptedRunPoint(original.logical_id, {"x": source}),),
        )

        assert projected.records[0].coordinates == {"x": expected}


def test_zero_points_and_no_record_projection_produce_no_measurement_records() -> None:
    zero = measurement_assembly_scenario(point_values=(), use_count=1)
    zero_values = seal_measurement_values(
        zero.catalog,
        (),
        points=zero.points,
    )
    zero_projection = select_measurement_projection(zero.catalog, zero.records)

    assert (
        project_measurement_records(
            zero_projection,
            zero_values,
            run_id="zero-run",
            points=zero.points,
        ).records
        == ()
    )

    no_records = measurement_assembly_scenario(point_values=(0.0, 1.0), use_count=0)
    empty_values = seal_measurement_values(
        no_records.catalog,
        (),
        points=no_records.points,
    )
    empty_projection = select_measurement_projection(
        no_records.catalog, no_records.records
    )

    assert (
        project_measurement_records(
            empty_projection,
            empty_values,
            run_id="no-record-run",
            points=no_records.points,
        ).records
        == ()
    )


def test_projected_recording_contract_matches_bound_projection() -> None:
    _scenario_value, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(
        _scenario_value.catalog, _scenario_value.records
    )

    first = project_measurement_records(
        projection,
        assembled,
        run_id="stable-record-run",
        points=_scenario_value.points,
    )
    assert first.recording_contract_fingerprint == projection.contract_fingerprint

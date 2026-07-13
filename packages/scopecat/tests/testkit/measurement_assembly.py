from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPoints,
    link_program,
)
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import TypedProgram, product_output
from scopecat.compiler.typed.records import RecordUse
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductUse, product_use
from scopecat.kernel.value_types import Float, Payload, Scalar, Table, TableColumn
from scopecat.measurements.values import (
    ClosedMeasurementProductValues,
    MeasurementValueCandidate,
    ProductValueFragmentDef,
    SelectedMeasurementValueAssembly,
    assemble_measurement_values,
    seal_measurement_value_fragment,
    select_measurement_value_assembly,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.invocation import materialize_linked_points
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import table_value_expr


@dataclass(frozen=True, slots=True)
class MeasurementAssemblyScenario:
    linked_points: MaterializedLinkedPoints
    uses: tuple[ProductUse, ...]


def measurement_assembly_scenario(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
    use_count: int = 3,
    shared_product: bool = False,
) -> MeasurementAssemblyScenario:
    point_type = Table(
        columns=(
            TableColumn("x", Scalar(Float())),
            TableColumn("opaque", Scalar(Payload("point-payload"))),
        ),
        min_rows=len(point_values),
        max_rows=len(point_values),
    )
    if shared_product and use_count:
        products = (
            product_output(
                "shared-signal",
                unit="ratio",
                dtype="float64",
                metadata={"definition": "shared"},
            ),
        )
        selected_products = products * use_count
    else:
        products = tuple(
            product_output(
                f"signal-{index}",
                unit="ratio",
                dtype="float64",
                metadata={"definition": index},
            )
            for index in range(use_count)
        )
        selected_products = products
    uses = tuple(product_use(product.id) for product in selected_products)
    records: list[RecordUse] = []
    if uses:
        records.extend(
            (
                RecordUse(
                    id="primary",
                    product_use_id=uses[0].id,
                    metadata={"projection": "primary"},
                ),
                RecordUse(
                    id="alias",
                    product_use_id=uses[0].id,
                    metadata={"projection": "alias"},
                ),
            )
        )
    if len(uses) > 1:
        records.append(
            RecordUse(
                id="secondary",
                product_use_id=uses[1].id,
                metadata={"projection": "secondary"},
            )
        )
    program = TypedProgram(
        id=f"measurement-assembly-{len(point_values)}-{use_count}",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows(
                        [
                            {
                                "x": value,
                                "opaque": PayloadValue(
                                    schema_id="point-payload",
                                    payload={"ordinal": index},
                                ),
                            }
                            for index, value in enumerate(point_values)
                        ]
                    ),
                    expected_type=point_type,
                )
            )
        ),
        product_defs=products,
        product_uses=uses,
        record_uses=tuple(records),
    )
    linked_points = materialize_linked_points(
        link_program(program, validate_config_environment(load_config()))
    )
    return MeasurementAssemblyScenario(linked_points=linked_points, uses=uses)


def measurement_fragment_definition(
    fragment_id: str,
    uses: tuple[ProductUse, ...],
) -> ProductValueFragmentDef:
    return ProductValueFragmentDef(
        id=fragment_id,
        product_use_ids=tuple(use.id for use in uses),
    )


def measurement_value_candidates(
    scenario: MeasurementAssemblyScenario,
    uses: tuple[ProductUse, ...],
) -> tuple[MeasurementValueCandidate, ...]:
    return tuple(
        MeasurementValueCandidate(
            logical_point_id=point.logical_id,
            product_use_id=use.id,
            value=Quantity(
                value=float(point.logical_ordinal * 100 + use_index),
                unit="ratio",
            ),
        )
        for point in scenario.linked_points.point_domain.points
        for use_index, use in enumerate(uses)
    )


def select_measurement_assembly(
    scenario: MeasurementAssemblyScenario,
    definitions: tuple[ProductValueFragmentDef, ...],
    *,
    required_uses: tuple[ProductUse, ...] | None = None,
) -> SelectedMeasurementValueAssembly:
    selected_uses = scenario.uses if required_uses is None else required_uses
    return select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in selected_uses),
        fragment_defs=definitions,
    )


def assembled_measurement_values_for_all_uses(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
) -> tuple[
    MeasurementAssemblyScenario,
    SelectedMeasurementValueAssembly,
    ClosedMeasurementProductValues,
]:
    scenario = measurement_assembly_scenario(point_values=point_values, use_count=3)
    definition = measurement_fragment_definition("all-values", scenario.uses)
    selected = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in scenario.uses),
        fragment_defs=(definition,),
    )
    fragment = seal_measurement_value_fragment(
        selected,
        "all-values",
        measurement_value_candidates(scenario, scenario.uses),
    )
    return scenario, selected, assemble_measurement_values(selected, (fragment,))


__all__ = [
    "MeasurementAssemblyScenario",
    "assembled_measurement_values_for_all_uses",
    "measurement_assembly_scenario",
    "measurement_fragment_definition",
    "measurement_value_candidates",
    "select_measurement_assembly",
]

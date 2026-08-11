from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.bound_facts import (
    LogicalResourceRequirement,
)
from scopecat.compiler.point_domain import PointDomain
from scopecat.config.environment import build_config_environment
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductUse, product_use
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import Float, Payload, Scalar
from scopecat.measurements.points import RunPoint
from scopecat.measurements.records import RecordUse
from scopecat.measurements.results import MeasurementScalar
from scopecat.measurements.values import (
    ClosedMeasurementProductValues,
    MeasurementValueCandidate,
    MeasurementValueCatalog,
    seal_measurement_values,
)
from scopecat.planning.measurement_projection import (
    project_measurement_catalog,
    project_run_point_catalog,
)
from scopecat.planning.point_materialization import (
    MaterializedBoundPoints,
    materialize_bound_points,
)
from scopecat.program.point_domain import point_axis_values

from scopecat_testkit.authoring import load_config
from scopecat_testkit.bound_program import (
    bind_program_facts,
    instrument_acquisitions,
    observable_product,
    program_fixture,
)


@dataclass(frozen=True, slots=True)
class MeasurementAssemblyScenario:
    bound_points: MaterializedBoundPoints
    catalog: MeasurementValueCatalog
    uses: tuple[ProductUse, ...]
    records: tuple[RecordUse, ...]

    @property
    def points(self) -> tuple[RunPoint, ...]:
        return project_run_point_catalog(self.bound_points).points


def measurement_assembly_scenario(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
    use_count: int = 3,
    shared_product: bool = False,
) -> MeasurementAssemblyScenario:
    if shared_product and use_count:
        products = (
            observable_product(
                "shared-signal",
                unit="ratio",
                dtype="float64",
                metadata={"definition": "shared"},
            ),
        )
        selected_products = products * use_count
    else:
        products = tuple(
            observable_product(
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
    program = program_fixture(
        point_domain=PointDomain(
            axes=(
                point_axis_values("x", Scalar(Float()), point_values),
                point_axis_values(
                    "opaque",
                    Scalar(Payload("point-payload")),
                    (
                        PayloadValue(
                            schema_id="point-payload",
                            payload={"constant": True},
                        ),
                    ),
                ),
            ),
        ),
        resource_requirements=(
            (
                LogicalResourceRequirement(
                    port_id=logical_resource_port_id("source"),
                    interfaces=("test.scalar_signal/v1",),
                ),
            )
            if products
            else ()
        ),
        instrument_acquisitions=instrument_acquisitions(
            *products,
            interface="test.scalar_signal/v1",
        ),
        product_defs=products,
        product_uses=uses,
        record_uses=tuple(records),
    )
    bound_points = materialize_bound_points(
        bind_program_facts(program, build_config_environment(load_config()))
    )
    return MeasurementAssemblyScenario(
        bound_points=bound_points,
        catalog=project_measurement_catalog(bound_points),
        uses=uses,
        records=tuple(records),
    )


def measurement_value_candidates(
    scenario: MeasurementAssemblyScenario,
    uses: tuple[ProductUse, ...],
) -> tuple[MeasurementValueCandidate, ...]:
    return tuple(
        MeasurementValueCandidate(
            logical_point_id=point.logical_id,
            product_use_id=use.id,
            value=MeasurementScalar.create(
                dtype="float64",
                value=float(point.logical_ordinal * 100 + use_index),
                unit="ratio",
            ),
        )
        for point in scenario.bound_points.point_domain.points
        for use_index, use in enumerate(uses)
    )


def assembled_measurement_values_for_all_uses(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
) -> tuple[
    MeasurementAssemblyScenario,
    ClosedMeasurementProductValues,
]:
    scenario = measurement_assembly_scenario(point_values=point_values, use_count=3)
    values = seal_measurement_values(
        scenario.catalog,
        measurement_value_candidates(scenario, scenario.uses),
        points=scenario.points,
    )
    return scenario, values


__all__ = [
    "MeasurementAssemblyScenario",
    "assembled_measurement_values_for_all_uses",
    "measurement_assembly_scenario",
    "measurement_value_candidates",
]

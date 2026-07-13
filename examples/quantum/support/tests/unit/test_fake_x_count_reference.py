from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.value_expressions import verify_table_value_expr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    TypedProgram,
    product_output,
    record_product,
    shot_axis,
)
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.value_types import Int, Scalar, Table, TableColumn
from scopecat.sdk.domain.invocation import materialize_linked_points

from quantum_lab_demo.reference_experiments import (
    FakeXCountProductBinding,
    prepare_fake_x_count_reference,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SHOTS = 5


def _linked_points():
    point_type = Table(
        columns=(TableColumn("x_count", Scalar(Int(minimum=0))),),
        min_rows=3,
        max_rows=3,
    )
    point_domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    (
                        {"x_count": 0},
                        {"x_count": 1},
                        {"x_count": 3},
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
    iq_use, _unused_iq_record = record_product(iq_shots)
    probability_0_use, probability_0_record = record_product(probability_0)
    probability_1_use, probability_1_record = record_product(probability_1)
    program = TypedProgram(
        id="fake-x-count-reference",
        kind="fake_x_count_reference",
        point_domain=point_domain,
        product_defs=(iq_shots, probability_0, probability_1),
        product_uses=(iq_use, probability_0_use, probability_1_use),
        record_uses=(
            probability_0_record,
            probability_1_record,
            probability_1_record.model_copy(update={"id": "probability_1_alias"}),
        ),
    )
    environment = validate_config_environment(
        load_config_profile(
            _REPO_ROOT / "fixtures/core/simple_scan/config-profile.json"
        )
    )
    linked_points = materialize_linked_points(link_program(program, environment))
    return linked_points, FakeXCountProductBinding(
        iq_use.id,
        probability_0_use.id,
        probability_1_use.id,
    )


def test_fake_x_count_reference_pure_preparation_closes_target_and_projection() -> None:
    linked_points, products = _linked_points()

    prepared = prepare_fake_x_count_reference(
        linked_points,
        products,
        shots=_SHOTS,
    )

    assert prepared.x_counts == (0, 1, 3)
    assert tuple(
        entry.target_entry.program.duration_seconds for entry in prepared.entries
    ) == (
        Decimal("8e-9"),
        Decimal("12e-9"),
        Decimal("20e-9"),
    )
    compiled = prepared.compiled_target.compiled
    intent = prepared.invocation.intent
    assert intent.target_id == compiled.target_id.value
    assert intent.compiler_id == compiled.compiler_id.value
    assert intent.capability_fingerprint == compiled.capability_fingerprint
    assert intent.artifact_id == compiled.artifact_id.value
    assert intent.artifact_fingerprint == compiled.artifact_fingerprint
    assert prepared.transform_plan.source_fragment_ids == (
        prepared.domain_fragment.fragment_id,
    )
    assert tuple(record.id for record in prepared.projection.projection.records) == (
        "probability_0",
        "probability_1",
        "probability_1_alias",
    )

import pytest

from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.kernel.content_identity import content_fingerprint
from scopecat.kernel.entity import EntityRef


def test_entity_content_fingerprint_uses_identity_not_metadata() -> None:
    configured = EntityRef(
        id="q0",
        kind="logical_qubit",
        metadata={"label": "configured"},
    )
    observed = EntityRef(
        id="q0",
        kind="logical_qubit",
        metadata={"label": "observed"},
    )

    assert content_fingerprint(configured) == content_fingerprint(observed)
    assert content_fingerprint(configured) != content_fingerprint(
        EntityRef(id="q0", kind="physical_qubit")
    )
    assert content_fingerprint(configured) != content_fingerprint(
        EntityRef(id="q1", kind="logical_qubit")
    )


def test_parameter_relation_data_rejects_cross_shape_id_collisions() -> None:
    with pytest.raises(ValueError, match="parameter ids must be unique"):
        ParameterRelationData(
            scalars={"shared": 1},
            tables={"shared": [{"value": 3}]},
        )

from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

import scopecat as sc
from scopecat.config.parameters import (
    DeleteParameterRows,
    InsertParameterRows,
    ParameterUpdate,
    ReplaceParameter,
    UpdateParameterRows,
)
from scopecat.kernel.frozen import FrozenMapping


def test_public_parameter_update_builders_return_canonical_models() -> None:
    updates = (
        sc.replace_scalar_parameter("enabled", True),
        sc.replace_series_parameter("thresholds", [1, 2]),
        sc.replace_table_parameter(
            "channels",
            [{"channel": "q0", "gain": 0.5}],
        ),
        sc.update_parameter_rows(
            "channels",
            key={"channel": "q0"},
            values={"gain": 0.75},
        ),
        sc.insert_parameter_rows(
            "channels",
            rows=[{"channel": "q1", "gain": 0.25}],
        ),
        sc.delete_parameter_rows("channels", key={"channel": "q2"}),
    )

    assert [type(update) for update in updates] == [
        ReplaceParameter,
        ReplaceParameter,
        ReplaceParameter,
        UpdateParameterRows,
        InsertParameterRows,
        DeleteParameterRows,
    ]
    assert updates[0].value.shape == "scalar"
    assert updates[1].value.shape == "series"
    assert updates[2].value.shape == "table"
    assert updates[3].key == {"channel": "q0"}
    assert updates[3].values == {"gain": 0.75}
    assert updates[4].rows == ({"channel": "q1", "gain": 0.25},)
    assert updates[5].key == {"channel": "q2"}
    assert isinstance(updates[3].key, FrozenMapping)
    assert isinstance(updates[3].values, FrozenMapping)
    assert all(isinstance(row, FrozenMapping) for row in updates[4].rows)
    assert isinstance(updates[5].key, FrozenMapping)


def test_parameter_updates_are_json_round_trippable_and_recursively_immutable() -> None:
    key = {"channel": "q0"}
    values = {"gain": 0.5}
    update = sc.update_parameter_rows(
        "channels",
        key=key,
        values=values,
    )

    assert isinstance(update.key, FrozenMapping)
    assert isinstance(update.values, FrozenMapping)
    payload = update.model_dump_json()
    assert json.loads(payload) == {
        "kind": "update_parameter_rows",
        "parameter_id": "channels",
        "key": {"channel": "q0"},
        "values": {"gain": 0.5},
    }
    assert TypeAdapter(ParameterUpdate).validate_json(payload) == update

    with pytest.raises(ValidationError, match="frozen"):
        update.parameter_id = "other"
    with pytest.raises(TypeError, match="immutable"):
        cast("dict[str, object]", cast("object", update.values))["gain"] = 0.75

    key["channel"] = "q1"
    values["gain"] = 0.75
    assert update.key == {"channel": "q0"}
    assert update.values == {"gain": 0.5}


@pytest.mark.parametrize(
    "build",
    [
        lambda: sc.replace_scalar_parameter("", True),
        lambda: sc.update_parameter_rows("channels", key={}, values={"gain": 0.5}),
        lambda: sc.update_parameter_rows("channels", key={"id": "q0"}, values={}),
        lambda: sc.insert_parameter_rows("channels", []),
        lambda: sc.delete_parameter_rows("channels", key={}),
    ],
)
def test_parameter_updates_reject_empty_identity_or_payload(
    build: Callable[[], object],
) -> None:
    with pytest.raises(ValueError, match=r"non-empty|at least 1"):
        build()

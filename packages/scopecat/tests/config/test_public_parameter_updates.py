from __future__ import annotations

import json
from typing import cast

import pytest

import scopecat as sc
from scopecat.config.parameters import (
    DeleteParameterRows,
    InsertParameterRows,
    ReplaceParameter,
    UpdateParameterRows,
)


def test_public_parameter_update_builders_return_transient_typed_intents() -> None:
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


def test_parameter_update_intents_are_not_durable_wire_models() -> None:
    update = sc.update_parameter_rows(
        "channels",
        key={"channel": "q0"},
        values={"gain": 0.5},
    )

    with pytest.raises(TypeError, match="JSON serializable"):
        json.dumps(update)
    with pytest.raises(TypeError, match="immutable"):
        cast("dict[str, object]", update.values)["gain"] = 0.75

"""Projection from transient scalar syntax to durable run-request values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from scopecat.compiler.relations.model import ScalarExpr
from scopecat.records._run_request_values import (
    normalize_json_value,
    normalize_run_request_value,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


def project_run_request_inputs(inputs: Mapping[str, object]) -> dict[str, object]:
    """Project bound template inputs into durable request values."""

    return {
        key: project_run_request_value(value, path=f"template_inputs.{key}")
        for key, value in inputs.items()
    }


def project_run_request_value(
    value: object,
    *,
    path: str = "value",
) -> object:
    """Explicitly project supported authoring values into request wire values."""

    if value is None or isinstance(value, str | bool | int | float | Quantity):
        return normalize_run_request_value(value)
    if isinstance(value, EntityRef):
        return {
            "kind": "entity",
            "entity_id": value.id,
            "entity_kind": value.kind,
            "metadata": normalize_json_value(value.metadata),
        }
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        projected: dict[str, object] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                msg = f"run request object keys must be strings at {path}"
                raise ValueError(msg)
            projected[key] = project_run_request_value(
                item,
                path=f"{path}.{key}",
            )
        return projected
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return [
            project_run_request_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(sequence)
        ]
    msg = f"unsupported authoring run request value at {path}: {type(value).__name__}"
    raise ValueError(msg)


def project_run_request_scalar(expression: ScalarExpr) -> object:
    """Project transient relation syntax into durable request semantics."""

    if expression.kind == "literal":
        return project_run_request_value(expression.value, path="expression.literal")
    if expression.kind == "point_column" and expression.name:
        return {"kind": "axis", "axis_id": expression.name}
    if expression.kind == "input" and expression.name:
        return {"kind": "input", "input_id": expression.name}
    if expression.kind == "param_scalar" and expression.name:
        return {"kind": "parameter", "parameter_id": expression.name}
    if expression.kind == "param_lookup":
        return {
            "kind": "parameter_lookup",
            "table_id": expression.table_id,
            "key": {
                name: project_run_request_scalar(value)
                for name, value in (expression.key or {}).items()
            },
            "column": expression.column,
        }
    if expression.kind == "binary":
        return {
            "kind": "binary",
            "operator": expression.op,
            "left": project_run_request_scalar(
                _required_scalar(expression.left, "expression.left")
            ),
            "right": project_run_request_scalar(
                _required_scalar(expression.right, "expression.right")
            ),
        }
    if expression.kind == "case":
        return {
            "kind": "case",
            "branches": [
                {
                    "when": project_run_request_scalar(branch.condition),
                    "then": project_run_request_scalar(branch.value),
                }
                for branch in (expression.cases or ())
            ],
            "fallback": project_run_request_scalar(
                _required_scalar(expression.fallback, "expression.fallback")
            ),
        }
    raise AssertionError(f"unsupported request scalar kind: {expression.kind}")


def _required_scalar(expression: ScalarExpr | None, path: str) -> ScalarExpr:
    if expression is None:
        raise AssertionError(f"{path} must be defined")
    return expression

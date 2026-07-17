"""Authoring value-reference composition helpers used only by tests."""

from scopecat.authoring._parameter_contracts import merge_parameter_contracts
from scopecat.authoring._value_refs import (
    ValueRef,
    _combined_table_type,
    _merge_point_dependencies,
    _require_no_column_conflicts,
    _require_table_type,
    internal_lower_table_value_ref,
    internal_value_ref_bound_point_input_ids,
    internal_value_ref_free_point_dependencies,
    internal_value_ref_free_point_input_ids,
    internal_value_ref_from_expression,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)


def internal_point_cross_value_refs(left: ValueRef, right: ValueRef) -> ValueRef:
    """Combine two partial point tables through the internal point binder."""

    left_type = _require_table_type(left, operation="point_cross")
    right_type = _require_table_type(right, operation="point_cross")
    _require_no_column_conflicts(
        left_type,
        right_type,
        operation="point_cross",
    )
    bound_point_ids = {column.id for column in left_type.columns}
    newly_bound_inputs = (
        internal_value_ref_free_point_input_ids(right) & bound_point_ids
    )
    return internal_value_ref_from_expression(
        internal_lower_table_value_ref(left).point_cross(
            internal_lower_table_value_ref(right)
        ),
        _combined_table_type(
            left_type,
            right_type,
            minimum=left_type.min_rows * right_type.min_rows,
        ),
        parameter_contracts=merge_parameter_contracts(
            internal_value_ref_parameter_contracts(left),
            internal_value_ref_parameter_contracts(right),
        ),
        point_dependencies=_merge_point_dependencies(
            internal_value_ref_point_dependencies(left),
            internal_value_ref_point_dependencies(right),
        ),
        free_point_dependencies=_merge_point_dependencies(
            internal_value_ref_free_point_dependencies(left),
            tuple(
                dependency
                for dependency in internal_value_ref_free_point_dependencies(right)
                if dependency.id not in bound_point_ids
            ),
        ),
        bound_point_input_ids=frozenset(
            {
                *internal_value_ref_bound_point_input_ids(left),
                *internal_value_ref_bound_point_input_ids(right),
                *newly_bound_inputs,
            }
        ),
    )

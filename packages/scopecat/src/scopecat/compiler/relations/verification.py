"""Static type verification for scalar plans.

The scalar AST deliberately remains an easy-to-author data model. This
module turns that model into a proof-carrying plan before compiler or runtime
code may rely on its shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from scopecat.graph.relations.model import (
    BinaryScalarExpr,
    InputScalarExpr,
    LiteralScalarExpr,
    ParameterLookupScalarExpr,
    ParameterLookupUse,
    ParameterScalarExpr,
    PointColumnScalarExpr,
    ScalarExpr,
    ScalarExpression,
)
from scopecat.graph.relations.operators import scalar_operator_result_type
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.value_type_compatibility import is_assignable, literal_scalar_type
from scopecat.kernel.value_types import (
    Scalar,
    Table,
    TableColumn,
)
from scopecat.kernel.value_validation import ValueValidationError, validate_literal

type PlanPathItem = str | int
type PlanPath = tuple[PlanPathItem, ...]


def _empty_value_bindings() -> dict[str, Scalar]:
    return {}


@dataclass(frozen=True, slots=True)
class RowType:
    """The structural type of one row, without collection cardinality or keys."""

    columns: tuple[TableColumn, ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(column.id for column in self.columns)
        if len(ids) != len(set(ids)):
            msg = "row columns must have unique ids"
            raise ValueError(msg)

    @classmethod
    def from_table(cls, value_type: Table) -> RowType:
        return cls(value_type.columns)


@dataclass(frozen=True, slots=True)
class PointRequirement:
    """The typed fields that a plan reads from the current experiment point.

    ``column_references`` retains the exact authored paths, while ``row_type``
    retains the corresponding root-column types and open-row semantics.
    """

    row_type: RowType
    column_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        references = tuple(sorted(set(self.column_references)))
        if any(not reference for reference in references):
            msg = "external row column references must be non-empty"
            raise ValueError(msg)
        if not references:
            msg = "an external row requirement must observe at least one column"
            raise ValueError(msg)
        object.__setattr__(self, "column_references", references)


@dataclass(frozen=True, slots=True)
class RelationTypeBindings:
    """Typed imports and the optional experiment-point row."""

    inputs: Mapping[str, Scalar] = field(default_factory=_empty_value_bindings)
    parameters: Mapping[str, Scalar] = field(default_factory=_empty_value_bindings)
    point_row: RowType | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", _frozen_mapping(self.inputs, "input"))
        object.__setattr__(
            self,
            "parameters",
            _frozen_mapping(self.parameters, "parameter"),
        )


class PlanImportNamespace(StrEnum):
    INPUT = "input"
    PARAMETER = "parameter"


@dataclass(frozen=True, slots=True)
class TypedPlanImport:
    namespace: PlanImportNamespace
    id: str
    value_type: Scalar
    lookup: ParameterLookupUse | None = None


class RelationPlanVerificationError(ValueError):
    """A deterministic static relation-plan failure."""

    def __init__(self, code: str, path: PlanPath, message: str) -> None:
        self.code = code
        self.path = path
        self.reason = message
        rendered = _format_path(path)
        super().__init__(f"{rendered}: {message}" if rendered else message)


class VerifiedRelationPlan:
    """Proof that a scalar plan matches its declared consumer type."""

    __slots__ = (
        "_bindings",
        "_external_point_requirement",
        "_imports",
        "_root",
        "_value_type",
    )

    def __init__(
        self,
        root: ScalarExpr,
        value_type: Scalar,
        imports: tuple[TypedPlanImport, ...],
        bindings: RelationTypeBindings,
        external_point_requirement: PointRequirement | None,
    ) -> None:
        self._root = root
        self._value_type = value_type
        self._imports = imports
        self._bindings = bindings
        self._external_point_requirement = external_point_requirement

    @property
    def root(self) -> ScalarExpr:
        return self._root

    @property
    def value_type(self) -> Scalar:
        return self._value_type

    @property
    def imports(self) -> tuple[TypedPlanImport, ...]:
        return self._imports

    def import_ids(self, namespace: PlanImportNamespace) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    imported.id
                    for imported in self._imports
                    if imported.namespace is namespace
                }
            )
        )

    @property
    def bindings(self) -> RelationTypeBindings:
        return self._bindings

    @property
    def external_point_requirement(self) -> PointRequirement | None:
        return self._external_point_requirement


def verify_relation_plan(
    root: ScalarExpr,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> VerifiedRelationPlan:
    """Verify imports and types, then certify the root for its consumer."""

    selected = bindings or RelationTypeBindings()
    verifier = _Verifier(selected)
    inferred = verifier.infer(root, (), expected_type)
    if expected_type is not None and not is_assignable(inferred, expected_type):
        raise RelationPlanVerificationError(
            "incompatible_result_type",
            (),
            f"inferred {inferred!r}, which is not assignable to {expected_type!r}",
        )
    certified = expected_type or inferred
    return VerifiedRelationPlan(
        root,
        certified,
        tuple(verifier.imports.values()),
        selected,
        _external_point_requirement(verifier, selected),
    )


class _Verifier:
    def __init__(self, bindings: RelationTypeBindings) -> None:
        self.bindings = bindings
        self.external_point_references: set[str] = set()
        self.imports: dict[
            tuple[PlanImportNamespace, str, ParameterLookupUse | None],
            TypedPlanImport,
        ] = {}

    def infer(
        self,
        node: ScalarExpr,
        path: PlanPath,
        expected: Scalar | None = None,
    ) -> Scalar:
        return self.scalar(node, path, expected)

    def scalar(
        self,
        node: ScalarExpr,
        path: PlanPath,
        expected: Scalar | None,
    ) -> Scalar:
        scalar = cast("ScalarExpression", node)
        match scalar:
            case LiteralScalarExpr():
                result = self.literal(scalar.value, path, expected)
            case PointColumnScalarExpr():
                name = scalar.name
                result = self.row_column(self.bindings.point_row, name, path)
                self.external_point_references.add(name)
            case InputScalarExpr():
                result = self.import_scalar(
                    PlanImportNamespace.INPUT,
                    scalar.name,
                    path,
                )
            case ParameterScalarExpr():
                result = self.import_scalar(
                    PlanImportNamespace.PARAMETER,
                    scalar.name,
                    path,
                )
            case ParameterLookupScalarExpr():
                result = self.parameter_lookup(scalar, path)
            case BinaryScalarExpr():
                left = self.infer(scalar.left, (*path, "left"))
                right = self.infer(scalar.right, (*path, "right"))
                try:
                    result = scalar_operator_result_type(
                        left,
                        right,
                        scalar.op,
                    )
                except (TypeError, ValueError) as error:
                    raise self.error(
                        "invalid_scalar_operator", path, str(error)
                    ) from error
                if scalar.op == "/" and _is_zero_literal(scalar.right):
                    raise self.error(
                        "division_by_zero",
                        (*path, "right"),
                        "division denominator is statically zero",
                    )
        self.require_expected(result, expected, path)
        return result

    def parameter_lookup(
        self,
        node: ParameterLookupScalarExpr,
        path: PlanPath,
    ) -> Scalar:
        use = node.use
        selected_key_types = dict(use.key_input_types)
        for name, expression in node.key.items():
            self.infer(
                expression,
                (*path, "key", name),
                selected_key_types[name],
            )
        import_key = (PlanImportNamespace.PARAMETER, use.table_id, use)
        self.imports.setdefault(
            import_key,
            TypedPlanImport(
                PlanImportNamespace.PARAMETER,
                use.table_id,
                use.result_type,
                lookup=use,
            ),
        )
        return use.result_type

    def import_scalar(
        self,
        namespace: PlanImportNamespace,
        import_id: str,
        path: PlanPath,
    ) -> Scalar:
        available = (
            self.bindings.inputs
            if namespace is PlanImportNamespace.INPUT
            else self.bindings.parameters
        )
        try:
            value_type = available[import_id]
        except KeyError as error:
            raise self.error(
                f"unknown_{namespace.value}",
                path,
                f"unknown {namespace.value} {import_id!r}",
            ) from error
        key = (namespace, import_id, None)
        self.imports.setdefault(key, TypedPlanImport(namespace, import_id, value_type))
        return value_type

    def row_column(
        self,
        row: RowType | None,
        name: str,
        path: PlanPath,
    ) -> Scalar:
        if row is None:
            raise self.error(
                "missing_row_type",
                path,
                f"column {name!r} has no typed row binding",
            )
        columns = {column.id: column for column in row.columns}
        exact = columns.get(name)
        if exact is None:
            raise self.error(
                "unknown_column",
                path,
                f"unknown column {name!r}",
            )
        return exact.value_type

    def literal(
        self,
        value: object,
        path: PlanPath,
        expected: Scalar | None,
    ) -> Scalar:
        if expected is not None:
            self.validate_literal(expected, value, path)
            return expected
        if value is None:
            raise self.error(
                "unsupported_null",
                path,
                "null literals are not supported",
            )
        return literal_scalar_type(value)

    def validate_literal(
        self,
        expected: Scalar,
        value: object,
        path: PlanPath,
    ) -> None:
        try:
            validate_literal(expected, value, path=path or ("value",))
        except ValueValidationError as error:
            raise self.error("invalid_literal", path, error.reason) from error

    def require_expected(
        self,
        actual: Scalar,
        expected: Scalar | None,
        path: PlanPath,
    ) -> None:
        if expected is not None and not is_assignable(actual, expected):
            raise self.error(
                "incompatible_result_type",
                path,
                f"inferred {actual!r}, which is not assignable to {expected!r}",
            )

    @staticmethod
    def error(
        code: str,
        path: PlanPath,
        message: str,
    ) -> RelationPlanVerificationError:
        return RelationPlanVerificationError(code, path, message)


def _frozen_mapping(
    values: Mapping[str, Scalar],
    label: str,
) -> Mapping[str, Scalar]:
    copied = dict(values)
    empty = [value_id for value_id in copied if not value_id]
    if empty:
        msg = f"{label} ids must be non-empty"
        raise ValueError(msg)
    return MappingProxyType(copied)


def _external_point_requirement(
    verifier: _Verifier,
    bindings: RelationTypeBindings,
) -> PointRequirement | None:
    return _point_requirement(
        bindings.point_row,
        verifier.external_point_references,
    )


def _point_requirement(
    row_type: RowType | None,
    references: set[str],
) -> PointRequirement | None:
    if not references:
        return None
    bound = row_type or RowType()
    selected_ids = {_row_column_root_id(bound, reference) for reference in references}
    required_type = RowType(
        tuple(column for column in bound.columns if column.id in selected_ids),
    )
    return PointRequirement(
        row_type=required_type,
        column_references=tuple(references),
    )


def _row_column_root_id(row: RowType | None, name: str) -> str:
    if row is None:
        raise AssertionError("verified row reference has no row type")
    column_ids = {column.id for column in row.columns}
    if name in column_ids:
        return name
    raise AssertionError(f"verified row reference {name!r} has no column")


def _is_zero_literal(node: ScalarExpr) -> bool:
    if not isinstance(node, LiteralScalarExpr):
        return False
    value = node.value
    if isinstance(value, QuantityValue):
        return value.value == 0
    return isinstance(value, int | float) and not isinstance(value, bool) and value == 0


def _format_path(path: PlanPath) -> str:
    if not path:
        return ""
    rendered = "root"
    for item in path:
        rendered += f"[{item}]" if isinstance(item, int) else f".{item}"
    return rendered

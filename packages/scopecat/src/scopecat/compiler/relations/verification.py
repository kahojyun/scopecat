"""Static verification and dependency analysis for canonical scalar plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import (
    Scalar,
    Table,
    TableColumn,
)
from scopecat.kernel.value_validation import ValueValidationError, validate_literal
from scopecat.program.expression_analysis import scalar_nodes
from scopecat.program.expression_operators import scalar_operator_result_type
from scopecat.program.expressions import (
    BinaryScalarExpr,
    ComputeResultScalarExpr,
    InputScalarExpr,
    LiteralScalarExpr,
    ModuleExportScalarExpr,
    ParameterLookupScalarExpr,
    ParameterLookupUse,
    ParameterScalarExpr,
    PointColumnScalarExpr,
    ScalarExpr,
    ScalarExpression,
)

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


def verify_relation_plan(
    root: ScalarExpr,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> ScalarExpression:
    """Verify one canonical expression and return the same object."""

    selected = bindings or RelationTypeBindings()
    verifier = _Verifier(selected)
    inferred = verifier.infer(root, (), expected_type)
    if expected_type is not None and not is_assignable(inferred, expected_type):
        raise RelationPlanVerificationError(
            "incompatible_result_type",
            (),
            f"inferred {inferred!r}, which is not assignable to {expected_type!r}",
        )
    return cast("ScalarExpression", root)


def relation_plan_imports(root: ScalarExpr) -> tuple[TypedPlanImport, ...]:
    """Derive the exact typed imports used by a canonical expression."""

    selected: dict[
        tuple[PlanImportNamespace, str, ParameterLookupUse | None],
        TypedPlanImport,
    ] = {}
    for scalar in scalar_nodes(root):
        if isinstance(scalar, InputScalarExpr):
            imported = TypedPlanImport(
                PlanImportNamespace.INPUT,
                scalar.name,
                scalar.value_type,
            )
        elif isinstance(scalar, ParameterScalarExpr):
            imported = TypedPlanImport(
                PlanImportNamespace.PARAMETER,
                scalar.name,
                scalar.value_type,
            )
        elif isinstance(scalar, ParameterLookupScalarExpr):
            imported = TypedPlanImport(
                PlanImportNamespace.PARAMETER,
                scalar.use.table_id,
                scalar.value_type,
                lookup=scalar.use,
            )
        else:
            continue
        key = (imported.namespace, imported.id, imported.lookup)
        selected.setdefault(key, imported)
    return tuple(selected.values())


def relation_plan_import_ids(
    root: ScalarExpr,
    namespace: PlanImportNamespace,
) -> tuple[str, ...]:
    """Return sorted unique import ids in one namespace."""

    return tuple(
        sorted(
            {
                imported.id
                for imported in relation_plan_imports(root)
                if imported.namespace is namespace
            }
        )
    )


def relation_plan_point_requirement(
    root: ScalarExpr,
) -> PointRequirement | None:
    """Derive the exact typed point columns read by an expression."""

    references: dict[str, Scalar] = {}
    for scalar in scalar_nodes(root):
        if not isinstance(scalar, PointColumnScalarExpr):
            continue
        existing = references.get(scalar.name)
        if existing is not None and existing != scalar.value_type:
            msg = f"point column {scalar.name!r} has conflicting intrinsic types"
            raise ValueError(msg)
        references.setdefault(scalar.name, scalar.value_type)
    if not references:
        return None
    names = tuple(sorted(references))
    return PointRequirement(
        row_type=RowType(tuple(TableColumn(name, references[name]) for name in names)),
        column_references=names,
    )


class _Verifier:
    def __init__(self, bindings: RelationTypeBindings) -> None:
        self.bindings = bindings

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
                self.validate_literal(scalar.value_type, scalar.value, path)
                result = scalar.value_type
            case PointColumnScalarExpr():
                bound_type = self.row_column(
                    self.bindings.point_row,
                    scalar.name,
                    path,
                )
                self.require_bound_type(bound_type, scalar.value_type, path)
                result = bound_type
            case InputScalarExpr():
                bound_type = self.import_scalar(
                    PlanImportNamespace.INPUT,
                    scalar.name,
                    path,
                )
                self.require_bound_type(bound_type, scalar.value_type, path)
                result = bound_type
            case ParameterScalarExpr():
                bound_type = self.import_scalar(
                    PlanImportNamespace.PARAMETER,
                    scalar.name,
                    path,
                )
                self.require_bound_type(bound_type, scalar.value_type, path)
                result = bound_type
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
                self.require_inferred_type(result, scalar.value_type, path)
            case ComputeResultScalarExpr():
                raise self.error(
                    "compute_result_unavailable",
                    path,
                    "compute results cannot appear inside a pure relation plan",
                )
            case ModuleExportScalarExpr():
                raise self.error(
                    "unresolved_module_export",
                    path,
                    f"unresolved module export {scalar.export_id!r}",
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
        self.require_intrinsic_type(use.result_type, node.value_type, path)
        return node.value_type

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

    def require_bound_type(
        self,
        bound: Scalar,
        intrinsic: Scalar,
        path: PlanPath,
    ) -> None:
        if is_assignable(bound, intrinsic):
            return
        raise self.error(
            "intrinsic_type_mismatch",
            path,
            f"bound type {bound!r} is not assignable to intrinsic {intrinsic!r}",
        )

    def require_intrinsic_type(
        self,
        inferred: Scalar,
        intrinsic: Scalar,
        path: PlanPath,
    ) -> None:
        if inferred == intrinsic:
            return
        raise self.error(
            "intrinsic_type_mismatch",
            path,
            f"inferred {inferred!r}, which differs from intrinsic {intrinsic!r}",
        )

    def require_inferred_type(
        self,
        inferred: Scalar,
        intrinsic: Scalar,
        path: PlanPath,
    ) -> None:
        if is_assignable(inferred, intrinsic):
            return
        raise self.error(
            "intrinsic_type_mismatch",
            path,
            f"inferred {inferred!r} is not assignable to intrinsic {intrinsic!r}",
        )

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

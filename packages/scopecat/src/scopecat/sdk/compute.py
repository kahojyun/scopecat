"""Explicit deployment contracts for portable compute functions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.program.values import ComputeFunction

_CONTRACT_ATTRIBUTE = "__scopecat_compute_implementation__"


def _empty_codecs() -> dict[str, str]:
    return {}


def _empty_resources() -> dict[str, JsonValue]:
    return {}


@dataclass(frozen=True, slots=True)
class ComputeImplementationContract:
    """Resolvable version, codecs, and execution requirements for a compute."""

    id: str
    version: str
    input_codecs: Mapping[str, str] = field(default_factory=_empty_codecs)
    output_codec: str = "scopecat.value.v1"
    runtime: str = "python"
    capabilities: tuple[str, ...] = ()
    resources: Mapping[str, JsonValue] = field(default_factory=_empty_resources)
    deterministic: bool = True

    def __post_init__(self) -> None:
        if not self.id or not self.version:
            raise ValueError("compute implementation id and version must be non-empty")
        if not self.output_codec or not self.runtime:
            raise ValueError("compute output codec and runtime must be non-empty")
        if any(not name or not codec for name, codec in self.input_codecs.items()):
            raise ValueError("compute input codec names and ids must be non-empty")
        if any(not capability for capability in self.capabilities):
            raise ValueError("compute capabilities must be non-empty")
        object.__setattr__(self, "input_codecs", dict(self.input_codecs))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "resources", freeze_json_mapping(self.resources))

    @property
    def reference(self) -> str:
        return f"registry:{self.id}@{self.version}"


class ComputeRegistry:
    """In-process resolver for explicitly deployable compute implementations."""

    __slots__ = ("_implementations",)

    def __init__(self) -> None:
        self._implementations: dict[
            str, tuple[ComputeImplementationContract, ComputeFunction]
        ] = {}

    def implementation[**P, ResultT](
        self,
        id: str,
        version: str,
        *,
        input_codecs: Mapping[str, str] | None = None,
        output_codec: str = "scopecat.value.v1",
        runtime: str = "python",
        capabilities: tuple[str, ...] = (),
        resources: Mapping[str, JsonValue] | None = None,
        deterministic: bool = True,
    ) -> Callable[[Callable[P, ResultT]], Callable[P, ResultT]]:
        contract = ComputeImplementationContract(
            id=id,
            version=version,
            input_codecs=input_codecs or {},
            output_codec=output_codec,
            runtime=runtime,
            capabilities=capabilities,
            resources=resources or {},
            deterministic=deterministic,
        )

        def register(fn: Callable[P, ResultT]) -> Callable[P, ResultT]:
            if contract.reference in self._implementations:
                raise ValueError(
                    f"compute implementation is already registered: "
                    f"{contract.reference}"
                )
            setattr(fn, _CONTRACT_ATTRIBUTE, contract)
            self._implementations[contract.reference] = (contract, fn)
            return fn

        return register

    def resolve(self, reference: str) -> ComputeFunction:
        try:
            return self._implementations[reference][1]
        except KeyError:
            raise KeyError(
                f"compute implementation is not registered: {reference}"
            ) from None

    def contract(self, reference: str) -> ComputeImplementationContract:
        try:
            return self._implementations[reference][0]
        except KeyError:
            raise KeyError(
                f"compute implementation is not registered: {reference}"
            ) from None


def compute_implementation_contract_internal(
    fn: ComputeFunction,
) -> ComputeImplementationContract | None:
    """Read a trusted registry marker without changing the callable contract."""

    value = getattr(fn, _CONTRACT_ATTRIBUTE, None)
    return value if isinstance(value, ComputeImplementationContract) else None


__all__ = ["ComputeImplementationContract", "ComputeRegistry"]

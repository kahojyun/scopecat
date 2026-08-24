"""Driver and provider boundaries for daemon-hosted instruments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from scopecat.records.config import InstrumentBindingSpec
from scopecat.sdk.instruments.authoring import (
    DriverAcquisition,
    DriverAcquisitionPlan,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
)
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    validate_instrument_description_collection,
)
from scopecat.sdk.problems import Problem


class DriverFault(Exception):
    """Exceptional driver control flow carrying one stable public problem."""

    def __init__(self, problem: Problem) -> None:
        self.problem = problem
        super().__init__(problem.message)


@runtime_checkable
class AcquisitionPreparer(Protocol):
    """Optional driver hook for demand-dependent capture preparation."""

    def prepare_acquisitions(
        self,
        plan: DriverAcquisitionPlan,
    ) -> DriverOutcome[None]: ...


class InstrumentDriver(Protocol):
    implementation_id: str
    implementation_version: str

    @property
    def instrument_id(self) -> str: ...

    def describe(self) -> InstrumentDescription: ...

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback: ...

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]: ...

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]: ...

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]: ...

    def disconnect(self) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True, slots=True)
class InstrumentProviderContext:
    """Inputs for side-effect-free catalog discovery."""

    bindings: tuple[InstrumentBindingSpec, ...]


@dataclass(frozen=True, slots=True)
class InstrumentConnectionContext:
    """Inputs for opening one driver for exactly one configured instrument."""

    binding: InstrumentBindingSpec


@dataclass(frozen=True)
class InstrumentProviderDescription:
    """Pure, binding-specific declaration of instruments a provider can create."""

    provider_id: str
    instruments: tuple[InstrumentDescription, ...] = ()
    problems: tuple[Problem, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("instrument provider id must be non-empty")
        validate_instrument_description_collection(self.instruments)


class InstrumentProvider(Protocol):
    """Pure catalog plus a one-instrument driver connection boundary.

    ``connect`` returns a fresh identified driver; expected rejections raise
    ``DriverFault``.
    """

    @property
    def provider_id(self) -> str: ...

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription: ...

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver: ...

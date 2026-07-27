"""Bind a configured instrument provider to host execution during planning."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.execution.local.drivers import preflight_problem_from_exception
from scopecat.execution.local.program import LocalOperation
from scopecat.execution.local.validation import validate_local_effect_block_instruments
from scopecat.execution.program import RunHostBinding
from scopecat.kernel.errors import ProviderContractError
from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    InstrumentProvider,
    InstrumentProviderContext,
)


@dataclass(frozen=True, slots=True)
class InstrumentProviderPreflight:
    """Pure provider ABI snapshot captured before host point lowering."""

    provider_id: str
    instrument_order: tuple[str, ...]
    advertised_descriptions: dict[str, InstrumentDescription]
    problems: tuple[Problem, ...]


def preflight_instrument_provider(
    *,
    config: ConfigProfileSnapshot,
    instrument_provider: InstrumentProvider,
) -> InstrumentProviderPreflight:
    """Describe and normalize the provider before point-local lowering."""

    problems: list[Problem] = []
    provider_id = instrument_provider.provider_id

    try:
        description = instrument_provider.describe(
            InstrumentProviderContext(config=config)
        )
    except Exception as error:
        problems.append(
            preflight_problem_from_exception(
                "instrument_provider_description_failed",
                f"instrument provider {provider_id} description failed",
                ("description",),
                error,
            )
        )
        raise ProviderContractError(problems) from error

    problems.extend(description.problems)
    if description.provider_id != provider_id:
        problems.append(
            _preflight_problem(
                "instrument_provider_id_mismatch",
                f"provider identity {provider_id!r} does not match "
                f"description {description.provider_id!r}",
                "provider_id",
            )
        )
    problems.extend(
        _validate_described_instruments(
            config=config,
            descriptions=description.instruments,
        )
    )
    return InstrumentProviderPreflight(
        provider_id=provider_id,
        instrument_order=tuple(item.instrument_id for item in description.instruments),
        advertised_descriptions={
            item.instrument_id: item for item in description.instruments
        },
        problems=tuple(problems),
    )


def validate_run_host_binding(
    *,
    host: RunHostBinding,
    effect_blocks: Sequence[Sequence[LocalOperation]],
    problems: Sequence[Problem],
) -> RunHostBinding:
    """Validate one already-closed host binding against its provider ABI."""

    selected = list(problems)
    selected.extend(
        validate_local_effect_block_instruments(
            resource_order=host.resource_order,
            operations=(
                *(
                    operation
                    for operations in effect_blocks
                    for operation in operations
                ),
            ),
            descriptions=host.advertised_descriptions,
            available_payloads={},
        )
    )
    if bool(selected):
        raise ProviderContractError(selected)
    return host


def _validate_described_instruments(
    *,
    config: ConfigProfileSnapshot,
    descriptions: tuple[InstrumentDescription, ...],
) -> list[Problem]:
    configured_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    problems: list[Problem] = []
    for description_index, description in enumerate(descriptions):
        if not description.instrument_id:
            problems.append(
                _preflight_problem(
                    "instrument_missing_id",
                    "instrument_id must be non-empty",
                    "instruments",
                    description_index,
                    "instrument_id",
                )
            )
        if not description.implementation_id:
            problems.append(
                _preflight_problem(
                    "instrument_missing_implementation_id",
                    "implementation_id must be non-empty",
                    "instruments",
                    description_index,
                    "implementation_id",
                )
            )
        if not description.implementation_version:
            problems.append(
                _preflight_problem(
                    "instrument_missing_implementation_version",
                    "implementation_version must be non-empty",
                    "instruments",
                    description_index,
                    "implementation_version",
                )
            )
        if description.instrument_id not in configured_ids:
            problems.append(
                _preflight_problem(
                    "instrument_not_in_config",
                    f"instrument {description.instrument_id} is not in config",
                    "instruments",
                    description_index,
                    "instrument_id",
                )
            )
    return problems


def _preflight_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", *path),
    )

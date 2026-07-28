"""Resolve and validate config-bound instrument contracts."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.execution.local.program import ComputeOperation, LocalOperation
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
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.records.config import (
    ApplyDefaultsRunPreparation,
    ConfigProfileSnapshot,
    InstrumentSpec,
    config_content_hash,
)
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentStateAssignment,
    validate_state_assignments,
)

from .provider_validation import preflight_problem_from_exception


def resolve_instrument_contract_catalog(
    *,
    config: ConfigProfileSnapshot,
    instrument_provider: InstrumentProvider,
) -> InstrumentContractCatalog:
    """Resolve one serializable provider contract without connecting hardware."""

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
        return InstrumentContractCatalog(
            config_content_hash=config_content_hash(config),
            provider_id=provider_id,
            problems=tuple(problems),
        )

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
    return InstrumentContractCatalog(
        config_content_hash=config_content_hash(config),
        provider_id=provider_id,
        instruments=description.instruments,
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
    selected.extend(_payload_codec_problems(host, effect_blocks))
    if bool(selected):
        raise ProviderContractError(selected)
    return host


def _payload_codec_problems(
    host: RunHostBinding,
    effect_blocks: Sequence[Sequence[LocalOperation]],
) -> list[Problem]:
    missing_schemas: set[str] = set()
    problems: list[Problem] = []
    for operations in effect_blocks:
        for operation in operations:
            if not isinstance(operation, ComputeOperation):
                continue
            slot = operation.payload_slot
            if (
                slot is None
                or slot.schema_id in host.payload_codecs
                or slot.schema_id in missing_schemas
            ):
                continue
            missing_schemas.add(slot.schema_id)
            problems.append(
                problem(
                    "payload_codec_missing",
                    f"compute payload schema {slot.schema_id!r} "
                    "has no registered codec",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location(
                        "execution_program",
                        "operations",
                        operation.operation_id,
                        "payload_slot",
                        "schema_id",
                    ),
                )
            )
    return problems


def _validate_described_instruments(
    *,
    config: ConfigProfileSnapshot,
    descriptions: tuple[InstrumentDescription, ...],
) -> list[Problem]:
    configured = {
        instrument.id: (index, instrument)
        for index, instrument in enumerate(config.instrument_registry.instruments)
    }
    configured_ids = set(configured)
    described_ids = {description.instrument_id for description in descriptions}
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
            continue
        configured_item = configured.get(description.instrument_id)
        if configured_item is not None:
            config_index, instrument = configured_item
            problems.extend(
                _validate_run_preparation(
                    instrument=instrument,
                    config_index=config_index,
                    description=description,
                )
            )
    for instrument_id, (config_index, instrument) in configured.items():
        if (
            isinstance(instrument.run_preparation, ApplyDefaultsRunPreparation)
            and instrument_id not in described_ids
        ):
            problems.append(
                problem(
                    "instrument_run_preparation_description_missing",
                    f"instrument {instrument_id} defaults cannot be validated "
                    "without an advertised description",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location(
                        "config",
                        "system",
                        "instrument_registry",
                        "instruments",
                        config_index,
                        "run_preparation",
                    ),
                )
            )
    return problems


def _validate_run_preparation(
    *,
    instrument: InstrumentSpec,
    config_index: int,
    description: InstrumentDescription,
) -> list[Problem]:
    preparation = instrument.run_preparation
    if not isinstance(preparation, ApplyDefaultsRunPreparation):
        return []
    assignments = [
        InstrumentStateAssignment(
            resource_id=instrument.id,
            interface_id=item.interface_id,
            component_path=list(item.component_path),
            property_id=item.property_id,
            value=item.value,
            entity_ids=list(item.entity_ids),
            channel_bindings=[
                binding.model_copy(deep=True) for binding in item.channel_bindings
            ],
        )
        for item in preparation.properties
    ]
    # An empty authoritative baseline requires case-local defaults to switch modes.
    issues = validate_state_assignments(
        instrument_id=instrument.id,
        assignments=assignments,
        description=description,
        baseline=InstrumentStateSnapshot(instrument_id=instrument.id),
    )
    location = model_location(
        "config",
        "system",
        "instrument_registry",
        "instruments",
        config_index,
        "run_preparation",
    )
    normalized: list[Problem] = []
    for issue in issues:
        related_locations = issue.related_locations
        if issue.location is not None:
            related_locations = (issue.location, *related_locations)
        normalized.append(
            issue.model_copy(
                update={
                    "phase": ProblemPhase.PROVIDER_PREFLIGHT,
                    "location": location,
                    "related_locations": related_locations,
                }
            )
        )
    return normalized


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

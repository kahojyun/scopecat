"""Durable local orchestration for config-bound execution programs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import cast

from pydantic import JsonValue, TypeAdapter

from scopecat.execution.effect_interpreter import RunEffectInterpreter, RunEffectResult
from scopecat.execution.events import (
    RuntimeTransitionProjector,
    observe_payload,
)
from scopecat.execution.local.drivers import (
    cleanup_after_setup_failure,
    describe_instruments,
    preflight_problem_from_exception,
    validate_instruments,
)
from scopecat.execution.local.program import PointProgram
from scopecat.execution.local.validation import validate_local_effect_block_instruments
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.execution.ports.journal import (
    CollectionRepository,
    ExecutionJournal,
    PayloadEvidenceCommitter,
)
from scopecat.execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat.execution.program import (
    RunHostBinding,
    RunOperation,
    RunPointStage,
    RunProgram,
    iter_run_operations,
)
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import (
    ProviderContractError,
)
from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)

_PROVIDER_METADATA_ADAPTER = TypeAdapter(dict[str, JsonValue])
_PROVIDER_DESCRIPTION_ADAPTER = TypeAdapter(InstrumentProviderDescription)


@dataclass(frozen=True, slots=True)
class InstrumentProviderPreflight:
    """Pure provider ABI snapshot captured before host point lowering."""

    context: InstrumentProviderContext
    provider_id: str
    instrument_order: tuple[str, ...]
    advertised_descriptions: dict[str, InstrumentDescription]
    problems: tuple[Problem, ...]
    provider: InstrumentProvider


def preflight_instrument_provider(
    *,
    config: ConfigProfileSnapshot,
    instrument_provider: InstrumentProvider,
) -> InstrumentProviderPreflight:
    """Describe and normalize the provider before point-local lowering."""

    problems: list[Problem] = []
    context = InstrumentProviderContext(config=config)
    try:
        provider_id = instrument_provider.provider_id
        if type(provider_id) is not str or not provider_id:
            msg = "instrument provider identity must be a non-empty string"
            raise TypeError(msg)
    except Exception as error:
        problems.append(
            preflight_problem_from_exception(
                "instrument_provider_identity_failed",
                "instrument provider identity lookup failed",
                ("provider_id",),
                error,
            )
        )
        raise ProviderContractError(problems) from error

    try:
        provider_description = _normalize_provider_description(
            instrument_provider.describe(context)
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

    problems.extend(provider_description.problems)
    if provider_description.provider_id != provider_id:
        problems.append(
            _preflight_problem(
                "instrument_provider_id_mismatch",
                f"provider identity {provider_id!r} does not match "
                f"description {provider_description.provider_id!r}",
                "provider_id",
            )
        )
    problems.extend(
        _validate_described_instruments(
            config=config,
            descriptions=provider_description.instruments,
        )
    )
    return InstrumentProviderPreflight(
        context=context,
        provider_id=provider_id,
        instrument_order=tuple(
            item.instrument_id for item in provider_description.instruments
        ),
        advertised_descriptions={
            item.instrument_id: item for item in provider_description.instruments
        },
        problems=tuple(problems),
        provider=instrument_provider,
    )


def validate_run_host_binding(
    *,
    program: RunHostBinding,
    points: Sequence[PointProgram],
    problems: Sequence[Problem],
) -> RunHostBinding:
    """Validate one already-closed host binding against its provider ABI."""

    selected = list(problems)
    selected.extend(
        validate_local_effect_block_instruments(
            resource_order=program.resource_order,
            stages=tuple(stage for point in points for stage in point.stages),
            descriptions=program.advertised_descriptions,
        )
    )

    if has_blocking_problems(selected):
        raise ProviderContractError(selected)
    return program


def execute_run_operations(
    *,
    config: ConfigProfileSnapshot,
    program: RunProgram,
    run_id: str,
    journal: ExecutionJournal,
    readbacks: CollectionRepository,
    payloads: PayloadEvidenceCommitter,
    transition_observer: RuntimeTransitionProjector,
    instrument_provider: InstrumentProvider | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunEffectResult:
    """Provision optional host drivers and interpret one operation sequence."""

    host = program.host
    if host is None:
        engine = RunEffectInterpreter(
            run_id=run_id,
            program=program,
            drivers={},
            journal=journal,
            readbacks=readbacks,
            payloads=payloads,
            transition_observer=transition_observer,
        )
        return engine.run(program.operations)

    return _execute_run_host_operations(
        config=config,
        host=host,
        instrument_provider=instrument_provider,
        effect_context=program,
        experiment_id=program.experiment_id,
        point_count=len(program.measurements.catalog.point_catalog.points),
        operations=program.operations,
        run_id=run_id,
        journal=journal,
        readbacks=readbacks,
        payloads=payloads,
        payload_observer=payload_observer,
        transition_observer=transition_observer,
    )


def _execute_run_host_operations(
    *,
    config: ConfigProfileSnapshot,
    host: RunHostBinding,
    instrument_provider: InstrumentProvider | None,
    effect_context: RunProgram,
    experiment_id: str,
    point_count: int,
    operations: tuple[RunOperation, ...],
    run_id: str,
    journal: ExecutionJournal,
    readbacks: CollectionRepository,
    payloads: PayloadEvidenceCommitter,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
    transition_observer: RuntimeTransitionProjector | None = None,
) -> RunEffectResult:
    """Provision host resources and interpret the complete operation sequence."""

    program = host
    if instrument_provider is None:
        raise ProviderContractError(
            (
                blocking_problem(
                    "instrument_provider_missing",
                    "host execution requires its experiment-system provider",
                    category=ProblemCategory.NOT_FOUND,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("execution", "provider"),
                ),
            )
        )
    setup_problems: list[Problem] = []
    if transition_observer is None:
        transition_observer = RuntimeTransitionProjector(
            event_sink=event_sink,
            experiment_id=experiment_id,
            point_count=point_count,
        )
    result = _provision_and_execute(
        run_id=run_id,
        experiment_id=experiment_id,
        config=config,
        context=InstrumentProviderContext(config=config),
        provider=instrument_provider,
        provider_id=host.provider_id,
        advertised_descriptions=host.advertised_descriptions,
        program=program,
        effect_context=effect_context,
        setup_problems=setup_problems,
        journal=journal,
        transition_observer=transition_observer,
        readbacks=readbacks,
        payloads=payloads,
        payload_observer=payload_observer,
        operations=operations,
    )
    if not setup_problems:
        return result
    return replace(
        result,
        problems=(
            *setup_problems,
            *(problem for problem in result.problems if problem not in setup_problems),
        ),
    )


def _provision_and_execute(
    *,
    run_id: str,
    experiment_id: str,
    config: ConfigProfileSnapshot,
    context: InstrumentProviderContext,
    provider: InstrumentProvider,
    provider_id: str,
    advertised_descriptions: dict[str, InstrumentDescription],
    program: RunHostBinding,
    effect_context: RunProgram,
    setup_problems: list[Problem],
    journal: ExecutionJournal,
    transition_observer: RuntimeTransitionProjector,
    readbacks: CollectionRepository,
    payloads: PayloadEvidenceCommitter,
    payload_observer: RuntimePayloadObserver | None,
    operations: tuple[RunOperation, ...],
) -> RunEffectResult:
    """Provision, verify, execute, and finalize while the caller holds leases."""

    provider_entry = ExecutionTransition(
        run_id=run_id,
        operation_id="lifecycle.provide-instruments",
        stage="provide_instruments",
        effect="lifecycle",
        state="started",
        evidence={
            "provider_id": provider_id,
            "advertised_instrument_ids": list(advertised_descriptions),
        },
    )
    provider_intent_committed, journal_interruption = _commit_provider_transition(
        journal,
        transition_observer,
        provider_entry,
        setup_problems,
    )
    if not provider_intent_committed:
        return _setup_result(
            run_id=run_id,
            experiment_id=experiment_id,
            problems=setup_problems,
            interruption=journal_interruption,
        )

    try:
        provider_result = provider.provide(context)
    except Exception as error:
        problem = problem_from_exception(
            "instrument_provider_failed",
            f"instrument provider {provider_id} failed",
            run_id=run_id,
            operation_id=provider_entry.operation_id,
            error=error,
        )
        setup_problems.append(problem)
        _, journal_interruption = _commit_provider_transition(
            journal,
            transition_observer,
            provider_entry.model_copy(
                update={"state": "unknown", "problems": (problem,)}
            ),
            setup_problems,
        )
        return _setup_result(
            run_id=run_id,
            experiment_id=experiment_id,
            problems=setup_problems,
            indeterminate=True,
            interruption=journal_interruption,
        )
    except BaseException as error:
        problem = _interruption_problem(
            error,
            run_id=run_id,
            operation_id=provider_entry.operation_id,
        )
        setup_problems.append(problem)
        _, journal_interruption = _commit_provider_transition(
            journal,
            transition_observer,
            provider_entry.model_copy(
                update={"state": "unknown", "problems": (problem,)}
            ),
            setup_problems,
        )
        return _setup_result(
            run_id=run_id,
            experiment_id=experiment_id,
            problems=setup_problems,
            indeterminate=True,
            interruption=error,
        )

    return _execute_provider_result(
        run_id=run_id,
        experiment_id=experiment_id,
        config=config,
        provider_id=provider_id,
        provider_result=provider_result,
        provider_entry=provider_entry,
        advertised_descriptions=advertised_descriptions,
        program=program,
        effect_context=effect_context,
        setup_problems=setup_problems,
        journal=journal,
        transition_observer=transition_observer,
        readbacks=readbacks,
        payloads=payloads,
        payload_observer=payload_observer,
        operations=operations,
    )


def _execute_provider_result(
    *,
    run_id: str,
    experiment_id: str,
    config: ConfigProfileSnapshot,
    provider_id: str,
    provider_result: InstrumentProviderResult,
    provider_entry: ExecutionTransition,
    advertised_descriptions: dict[str, InstrumentDescription],
    program: RunHostBinding,
    effect_context: RunProgram,
    setup_problems: list[Problem],
    journal: ExecutionJournal,
    transition_observer: RuntimeTransitionProjector,
    readbacks: CollectionRepository,
    payloads: PayloadEvidenceCommitter,
    payload_observer: RuntimePayloadObserver | None,
    operations: tuple[RunOperation, ...],
) -> RunEffectResult:
    """Own every returned driver until a fully constructed engine takes over."""

    instruments: list[InstrumentDriver] = []
    provider_transition_attempted = False
    engine: RunEffectInterpreter | None = None
    indeterminate = False
    interruption: BaseException | None = None
    try:
        # Ownership is acquired one driver at a time before touching any driver
        # property or provider completion metadata.  A non-conforming iterable
        # that fails part-way through cannot orphan already yielded drivers.
        for instrument in provider_result.drivers:
            instruments.append(instrument)  # noqa: PERF402
        provider_problems = list(
            contextualize_problems(
                provider_result.problems,
                run_id=run_id,
                operation_id=provider_entry.operation_id,
            )
        )
        setup_problems.extend(provider_problems)
        provider_evidence = {
            **provider_entry.evidence,
            **_provider_result_evidence(
                provider_id=provider_id,
                provider_result=provider_result,
                instruments=instruments,
                problems=provider_problems,
            ),
        }
        provider_transition_attempted = True
        transition_committed, journal_interruption = _commit_provider_transition(
            journal,
            transition_observer,
            provider_entry.model_copy(
                update={
                    "state": (
                        "failed"
                        if has_blocking_problems(provider_problems)
                        else "completed"
                    ),
                    "problems": tuple(provider_problems),
                    "evidence": provider_evidence,
                }
            ),
            setup_problems,
        )
        if not transition_committed or journal_interruption is not None:
            indeterminate = True
            interruption = journal_interruption
        else:
            actual_descriptions: list[InstrumentDescription] = []
            if instruments and not has_blocking_problems(setup_problems):
                setup_problems.extend(
                    validate_instruments(config=config, instruments=instruments)
                )
                actual_descriptions, description_problems = describe_instruments(
                    instruments
                )
                setup_problems.extend(description_problems)
                if not has_blocking_problems(setup_problems):
                    setup_problems.extend(
                        validate_local_effect_block_instruments(
                            resource_order=program.resource_order,
                            stages=tuple(
                                operation.stage
                                for operation in iter_run_operations(operations)
                                if isinstance(operation, RunPointStage)
                            ),
                            descriptions={
                                item.instrument_id: item for item in actual_descriptions
                            },
                        )
                    )
            setup_problems.extend(
                _validate_provided_descriptions(
                    run_id=run_id,
                    advertised=advertised_descriptions,
                    actual=actual_descriptions,
                )
            )
            if not has_blocking_problems(setup_problems):
                engine = RunEffectInterpreter(
                    run_id=run_id,
                    program=effect_context,
                    drivers={
                        instrument.instrument_id: instrument
                        for instrument in instruments
                    },
                    descriptions={
                        item.instrument_id: item for item in actual_descriptions
                    },
                    journal=journal,
                    transition_observer=transition_observer,
                    readbacks=readbacks,
                    payloads=payloads,
                    payload_observer=lambda payload: observe_payload(
                        observer=payload_observer,
                        run_id=run_id,
                        experiment_id=experiment_id,
                        payload=payload,
                    ),
                )
    except Exception as error:
        problem = problem_from_exception(
            "instrument_provider_result_invalid",
            f"instrument provider {provider_id} returned an invalid result",
            run_id=run_id,
            operation_id=provider_entry.operation_id,
            error=error,
        )
        setup_problems.append(problem)
        if not provider_transition_attempted:
            _commit_provider_transition(
                journal,
                transition_observer,
                provider_entry.model_copy(
                    update={"state": "failed", "problems": (problem,)}
                ),
                setup_problems,
            )
    except BaseException as error:
        problem = _interruption_problem(
            error,
            run_id=run_id,
            operation_id=provider_entry.operation_id,
        )
        setup_problems.append(problem)
        if not provider_transition_attempted:
            _commit_provider_transition(
                journal,
                transition_observer,
                provider_entry.model_copy(
                    update={"state": "unknown", "problems": (problem,)}
                ),
                setup_problems,
            )
        indeterminate = True
        interruption = error

    if engine is not None:
        # Engine construction is the ownership hand-off.  Its run boundary is
        # responsible for abort/cleanup and terminal state capture after effects.
        return engine.run(operations)
    return _finalize_owned_setup(
        run_id=run_id,
        experiment_id=experiment_id,
        instruments=instruments,
        problems=setup_problems,
        journal=journal,
        transition_observer=transition_observer,
        indeterminate=indeterminate,
        interruption=interruption,
    )


def _finalize_owned_setup(
    *,
    run_id: str,
    experiment_id: str,
    instruments: list[InstrumentDriver],
    problems: list[Problem],
    journal: ExecutionJournal,
    transition_observer: RuntimeTransitionProjector,
    indeterminate: bool = False,
    interruption: BaseException | None = None,
) -> RunEffectResult:
    final_state, cleanup_interruption = cleanup_after_setup_failure(
        instruments,
        problems,
        run_id=run_id,
        journal=journal,
        transition_observer=transition_observer,
    )
    return _setup_result(
        run_id=run_id,
        experiment_id=experiment_id,
        problems=problems,
        final_state=final_state,
        indeterminate=indeterminate,
        interruption=(
            interruption if interruption is not None else cleanup_interruption
        ),
    )


def _setup_result(
    *,
    run_id: str,
    experiment_id: str,
    problems: list[Problem],
    final_state: Sequence[InstrumentStateSnapshot] = (),
    indeterminate: bool = False,
    interruption: BaseException | None = None,
) -> RunEffectResult:
    return RunEffectResult(
        run_id=run_id,
        experiment_id=experiment_id,
        problems=tuple(problems),
        initial_state=(),
        final_state=tuple(final_state),
        indeterminate=indeterminate,
        interruption=interruption,
    )


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


def _validate_provided_descriptions(
    *,
    run_id: str,
    advertised: dict[str, InstrumentDescription],
    actual: list[InstrumentDescription],
) -> list[Problem]:
    actual_by_id = {item.instrument_id: item for item in actual}
    problems: list[Problem] = []
    for instrument_id in sorted(set(advertised) - set(actual_by_id)):
        problems.append(
            runtime_problem(
                "instrument_provider_missing_advertised_instrument",
                f"provider did not create advertised instrument {instrument_id}",
                run_id=run_id,
                operation_id="lifecycle.provide-instruments",
                instrument_id=instrument_id,
                category=ProblemCategory.PROVIDER_CONTRACT,
            )
        )
    for instrument_id in sorted(set(actual_by_id) - set(advertised)):
        problems.append(
            runtime_problem(
                "instrument_provider_unadvertised_instrument",
                f"provider created unadvertised instrument {instrument_id}",
                run_id=run_id,
                operation_id="lifecycle.provide-instruments",
                instrument_id=instrument_id,
                category=ProblemCategory.PROVIDER_CONTRACT,
            )
        )
    for instrument_id in sorted(set(advertised) & set(actual_by_id)):
        if advertised[instrument_id] != actual_by_id[instrument_id]:
            problems.append(
                runtime_problem(
                    "instrument_description_changed_after_provision",
                    f"instrument {instrument_id} differs from its advertised contract",
                    run_id=run_id,
                    operation_id="lifecycle.provide-instruments",
                    instrument_id=instrument_id,
                    category=ProblemCategory.PROVIDER_CONTRACT,
                )
            )
    return problems


def _interruption_problem(
    error: BaseException,
    *,
    run_id: str,
    operation_id: str,
) -> Problem:
    return runtime_problem(
        "execution_interrupted",
        f"execution interrupted by {type(error).__name__}",
        run_id=run_id,
        operation_id=operation_id,
        category=ProblemCategory.INTERRUPTED,
        details={
            "exception_type": f"{type(error).__module__}.{type(error).__qualname__}"
        },
    )


def _preflight_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", *path),
    )


def _commit_provider_transition(
    journal: ExecutionJournal,
    transition_observer: RuntimeTransitionProjector,
    entry: ExecutionTransition,
    problems: list[Problem],
) -> tuple[bool, BaseException | None]:
    try:
        committed = journal.append(entry)
        transition_observer.observe(committed)
    except Exception as error:
        problems.append(
            problem_from_exception(
                "execution_journal_commit_failed",
                f"failed to journal {entry.operation_id}",
                run_id=entry.run_id,
                operation_id=entry.operation_id,
                error=error,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
            )
        )
        return False, None
    except BaseException as error:
        problems.append(
            _interruption_problem(
                error,
                run_id=entry.run_id,
                operation_id=entry.operation_id,
            )
        )
        return False, error
    return True, None


def _provider_result_evidence(
    *,
    provider_id: str,
    provider_result: InstrumentProviderResult,
    instruments: list[InstrumentDriver],
    problems: list[Problem],
) -> dict[str, JsonValue]:
    instrument_ids = sorted(instrument.instrument_id for instrument in instruments)
    validated_metadata = _PROVIDER_METADATA_ADAPTER.validate_python(
        provider_result.metadata
    )
    metadata = cast(
        "dict[str, JsonValue]",
        _PROVIDER_METADATA_ADAPTER.dump_python(
            validated_metadata,
            mode="json",
        ),
    )
    receipt = {
        "provider_id": provider_id,
        "instrument_ids": instrument_ids,
        "problems": [item.model_dump(mode="json") for item in problems],
        "metadata": metadata,
    }
    evidence = {
        "instrument_ids": instrument_ids,
        "provisioning_receipt": receipt,
        "provisioning_receipt_content_hash": stable_content_hash(receipt),
    }
    return cast("dict[str, JsonValue]", evidence)


def _normalize_provider_description(value: object) -> InstrumentProviderDescription:
    if not isinstance(value, InstrumentProviderDescription):
        msg = (
            "instrument provider describe must return InstrumentProviderDescription, "
            f"got {type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    wire = cast(
        "object",
        _PROVIDER_DESCRIPTION_ADAPTER.dump_python(value, mode="json"),
    )
    return _PROVIDER_DESCRIPTION_ADAPTER.validate_python(wire)

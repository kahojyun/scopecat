"""Durable local orchestration for config-bound execution programs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from scopecat._compiler.bound import BoundPlan
from scopecat._compiler.run_plan import build_run_plan_record
from scopecat._content_identity import stable_content_hash
from scopecat._execution.drivers import (
    cleanup_after_setup_failure,
    describe_instruments,
    diagnostic_from_exception,
    validate_instruments,
)
from scopecat._execution.engine import ExecutionEngine, ExecutionEngineResult
from scopecat._execution.events import (
    ObservedExecutionJournal,
    emit_run_finished,
    emit_run_started,
    observe_payload,
)
from scopecat._execution.evidence import (
    build_execution_manifest,
    build_execution_summary,
    build_instrument_state_evidence,
    execution_summary_ref,
    instrument_state_evidence_ref,
    raw_measurement_schema,
    raw_measurements_ref,
)
from scopecat._execution.journal import ExecutionJournalEntry
from scopecat._execution.lowering import build_execution_program
from scopecat._execution.persistence import (
    validate_measurement_index_shape,
    validate_raw_measurement_dataset,
)
from scopecat._execution.program import ExecutionProgram
from scopecat._execution.validation import validate_execution_program_instruments
from scopecat._measurement_storage import write_measurement_records_path
from scopecat._storage.local import (
    LocalCollectionCommitter,
    LocalExecutionJournal,
    LocalMeasurementCommitter,
    LocalPayloadEvidenceCommitter,
    LocalResourceLeaseManager,
    LocalRunStore,
)
from scopecat.diagnostics import Diagnostic
from scopecat.errors import RunExecutionFailed, ValidationFailed
from scopecat.ids import new_run_id
from scopecat.instruments.events import RuntimeEventSink, RuntimePayloadObserver
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateSnapshot,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionSummary
from scopecat.models.measurement import MeasurementDatasetSchema
from scopecat.models.run import RunConfigSource, RunManifest, RunStatus
from scopecat.models.run_request import RunRequest
from scopecat.planning.validation import has_blocking_diagnostics

_PROVIDER_METADATA_ADAPTER = TypeAdapter(dict[str, JsonValue])
_PROVIDER_DESCRIPTION_ADAPTER = TypeAdapter(InstrumentProviderDescription)


def execute_run(
    *,
    config: ConfigProfileSnapshot,
    plan: BoundPlan,
    request: RunRequest | None,
    instrument_provider: InstrumentProvider,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    """Execute one bound plan with durable acceptance before provisioning.

    The provider is deliberately invoked inside this function: creating live
    driver objects may open connections or reserve hardware, so the run skeleton
    and provider intent journal entry must already exist.
    """

    preflight_diagnostics = list(plan.diagnostics)
    if has_blocking_diagnostics(preflight_diagnostics):
        raise ValidationFailed(preflight_diagnostics)

    run_id = new_run_id()
    storage = LocalRunStore(Path(workspace))
    plan_record = build_run_plan_record(plan)
    planned_manifest = RunManifest(
        run_id=run_id,
        status="planned",
        config_source=config_source,
    )
    storage.write_run_skeleton(
        manifest=planned_manifest,
        request=request,
        plan=plan_record,
        config=config,
    )

    local_journal = LocalExecutionJournal(workspace, run_id=run_id)
    journal = ObservedExecutionJournal(
        local_journal,
        event_sink=event_sink,
        experiment_id=plan.experiment_id,
        point_count=plan.point_count,
    )
    # A run becomes active before any provider lifecycle effect can begin.
    storage.write_manifest(planned_manifest.model_copy(update={"status": "running"}))
    emit_run_started(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=plan.experiment_id,
        point_count=plan.point_count,
        instrument_ids=_planned_instrument_ids(plan),
        output_ids=sorted(plan.expected_output_ids),
    )

    context = InstrumentProviderContext(config=config)
    setup_diagnostics = list(preflight_diagnostics)
    provider_id = (
        f"{type(instrument_provider).__module__}."
        f"{type(instrument_provider).__qualname__}"
    )
    interruption: BaseException | None = None
    try:
        provider_id = instrument_provider.provider_id
    except Exception as error:
        setup_diagnostics.append(
            diagnostic_from_exception(
                "instrument_provider_identity_failed",
                "instrument provider identity lookup failed",
                "instrument_provider.provider_id",
                error,
            )
        )
    except BaseException as error:
        interruption = error
        setup_diagnostics.append(
            _interruption_diagnostic(error, "instrument_provider.provider_id")
        )

    provider_description: InstrumentProviderDescription | None = None
    if not has_blocking_diagnostics(setup_diagnostics) and interruption is None:
        try:
            provider_description = _normalize_provider_description(
                instrument_provider.describe(context)
            )
        except Exception as error:
            setup_diagnostics.append(
                diagnostic_from_exception(
                    "instrument_provider_description_failed",
                    f"instrument provider {provider_id} description failed",
                    "instrument_provider.description",
                    error,
                )
            )
        except BaseException as error:
            interruption = error
            setup_diagnostics.append(
                _interruption_diagnostic(error, "instrument_provider.description")
            )

    instrument_order: tuple[str, ...] = ()
    advertised_descriptions: dict[str, InstrumentDescription] = {}
    if provider_description is not None:
        try:
            setup_diagnostics.extend(provider_description.diagnostics)
            if provider_description.provider_id != provider_id:
                setup_diagnostics.append(
                    _diagnostic(
                        "instrument_provider_id_mismatch",
                        f"provider identity {provider_id!r} does not match "
                        f"description {provider_description.provider_id!r}",
                        "instrument_provider.provider_id",
                    )
                )
            instrument_order = tuple(
                item.instrument_id for item in provider_description.instruments
            )
            advertised_descriptions = {
                item.instrument_id: item for item in provider_description.instruments
            }
            setup_diagnostics.extend(
                _validate_described_instruments(
                    config=config,
                    descriptions=provider_description.instruments,
                )
            )
        except Exception as error:
            setup_diagnostics.append(
                diagnostic_from_exception(
                    "instrument_provider_description_invalid",
                    f"instrument provider {provider_id} description is invalid",
                    "instrument_provider.description",
                    error,
                )
            )
        except BaseException as error:
            interruption = error
            setup_diagnostics.append(
                _interruption_diagnostic(error, "instrument_provider.description")
            )

    program = None
    if (
        provider_description is not None
        and not has_blocking_diagnostics(setup_diagnostics)
        and interruption is None
    ):
        try:
            program = build_execution_program(
                plan,
                instrument_order=instrument_order,
            )
            setup_diagnostics.extend(
                validate_execution_program_instruments(
                    program,
                    descriptions=advertised_descriptions,
                )
            )
        except Exception as error:
            program = None
            setup_diagnostics.append(
                diagnostic_from_exception(
                    "execution_program_lowering_failed",
                    "failed to lower the bound execution plan",
                    "execution_program",
                    error,
                )
            )
        except BaseException as error:
            program = None
            interruption = error
            setup_diagnostics.append(
                _interruption_diagnostic(error, "execution_program")
            )
    result: ExecutionEngineResult | None = None
    if (
        program is None
        or has_blocking_diagnostics(setup_diagnostics)
        or interruption is not None
    ):
        result = _setup_result(
            run_id=run_id,
            experiment_id=plan.experiment_id,
            diagnostics=setup_diagnostics,
            interruption=interruption,
        )
    else:
        lease_manager = LocalResourceLeaseManager(workspace)
        try:
            lease = lease_manager.acquire(program.resource_claims)
            with lease:
                result = _provision_and_execute(
                    run_id=run_id,
                    experiment_id=plan.experiment_id,
                    config=config,
                    context=context,
                    provider=instrument_provider,
                    provider_id=provider_id,
                    advertised_descriptions=advertised_descriptions,
                    program=program,
                    setup_diagnostics=setup_diagnostics,
                    journal=journal,
                    workspace=workspace,
                    payload_observer=payload_observer,
                )
        except Exception as error:
            setup_diagnostics.append(
                diagnostic_from_exception(
                    "resource_lease_failed",
                    "failed to acquire or release execution resources",
                    "execution.resources",
                    error,
                )
            )
            if result is None:
                result = _setup_result(
                    run_id=run_id,
                    experiment_id=plan.experiment_id,
                    diagnostics=setup_diagnostics,
                )
        except BaseException as error:
            diagnostic = _interruption_diagnostic(error, "execution.resources")
            setup_diagnostics.append(diagnostic)
            if result is None:
                result = _setup_result(
                    run_id=run_id,
                    experiment_id=plan.experiment_id,
                    diagnostics=setup_diagnostics,
                    interruption=error,
                )
            else:
                result = replace(
                    result,
                    status="interrupted",
                    diagnostics=(*result.diagnostics, diagnostic),
                    interruption=result.interruption or error,
                )

    assert result is not None

    diagnostics = _execution_diagnostics(
        setup_diagnostics=setup_diagnostics,
        result=result,
        expected_schema=raw_measurement_schema(plan.expected_dataset_schema),
        expected_indices=set(range(plan.point_count)),
    )
    status: RunStatus = (
        "interrupted"
        if result.interruption is not None
        else "unknown"
        if result.uncertain
        else "failed"
        if has_blocking_diagnostics(diagnostics)
        else "completed"
    )
    summary = build_execution_summary(
        result=result,
        status=status,
        instrument_ids=list(instrument_order),
        point_count=plan.point_count,
        diagnostics=diagnostics,
    )
    instrument_state = build_instrument_state_evidence(result)
    manifest = build_execution_manifest(
        run_id=run_id,
        status=status,
        measurements=list(result.measurements),
        expected_schema=raw_measurement_schema(plan.expected_dataset_schema),
        config_source=config_source,
    ).model_copy(update={"created_at": planned_manifest.created_at})

    # Result content first; the terminal manifest is the final commit marker.
    storage.write_model_atomic(run_id, execution_summary_ref(), summary)
    storage.write_model_atomic(
        run_id,
        instrument_state_evidence_ref(),
        instrument_state,
    )
    if result.measurements:
        write_measurement_records_path(
            path=storage.ref_path(run_id, raw_measurements_ref()),
            records=list(result.measurements),
        )
    storage.write_manifest(manifest)
    emit_run_finished(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=plan.experiment_id,
        status=status,
        completed_point_count=result.completed_point_count,
        point_count=plan.point_count,
        measurement_count=len(result.measurements),
        diagnostic_count=len(diagnostics),
        compute_evaluated_node_count=result.compute_evaluated_node_count,
        compute_reused_node_count=result.compute_reused_node_count,
        compute_payload_count=result.compute_payload_count,
    )
    if result.interruption is not None:
        raise result.interruption
    if status != "completed":
        raise RunExecutionFailed(run_id, diagnostics)
    return manifest, summary


def _provision_and_execute(
    *,
    run_id: str,
    experiment_id: str,
    config: ConfigProfileSnapshot,
    context: InstrumentProviderContext,
    provider: InstrumentProvider,
    provider_id: str,
    advertised_descriptions: dict[str, InstrumentDescription],
    program: ExecutionProgram,
    setup_diagnostics: list[Diagnostic],
    journal: ObservedExecutionJournal,
    workspace: str | Path,
    payload_observer: RuntimePayloadObserver | None,
) -> ExecutionEngineResult:
    """Provision, verify, execute, and finalize while the caller holds leases."""

    provider_entry = ExecutionJournalEntry(
        run_id=run_id,
        operation_id="lifecycle.provide-instruments",
        stage="provide_instruments",
        effect="lifecycle",
        state="started",
        summary={
            "provider_id": provider_id,
            "advertised_instrument_ids": list(advertised_descriptions),
        },
    )
    provider_intent_committed, journal_interruption = _append_provider_transition(
        journal,
        provider_entry,
        setup_diagnostics,
    )
    if not provider_intent_committed:
        return _setup_result(
            run_id=run_id,
            experiment_id=experiment_id,
            diagnostics=setup_diagnostics,
            interruption=journal_interruption,
        )

    try:
        provider_result = provider.provide(context)
    except Exception as error:
        diagnostic = diagnostic_from_exception(
            "instrument_provider_failed",
            f"instrument provider {provider_id} failed",
            "instrument_provider",
            error,
        )
        setup_diagnostics.append(diagnostic)
        _, journal_interruption = _append_provider_transition(
            journal,
            provider_entry.model_copy(
                update={"state": "unknown", "diagnostics": [diagnostic]}
            ),
            setup_diagnostics,
        )
        return _setup_result(
            run_id=run_id,
            experiment_id=experiment_id,
            diagnostics=setup_diagnostics,
            uncertain=True,
            interruption=journal_interruption,
        )
    except BaseException as error:
        diagnostic = _interruption_diagnostic(error, "instrument_provider")
        setup_diagnostics.append(diagnostic)
        _, journal_interruption = _append_provider_transition(
            journal,
            provider_entry.model_copy(
                update={"state": "unknown", "diagnostics": [diagnostic]}
            ),
            setup_diagnostics,
        )
        return _setup_result(
            run_id=run_id,
            experiment_id=experiment_id,
            diagnostics=setup_diagnostics,
            uncertain=True,
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
        setup_diagnostics=setup_diagnostics,
        journal=journal,
        workspace=workspace,
        payload_observer=payload_observer,
    )


def _execute_provider_result(
    *,
    run_id: str,
    experiment_id: str,
    config: ConfigProfileSnapshot,
    provider_id: str,
    provider_result: InstrumentProviderResult,
    provider_entry: ExecutionJournalEntry,
    advertised_descriptions: dict[str, InstrumentDescription],
    program: ExecutionProgram,
    setup_diagnostics: list[Diagnostic],
    journal: ObservedExecutionJournal,
    workspace: str | Path,
    payload_observer: RuntimePayloadObserver | None,
) -> ExecutionEngineResult:
    """Own every returned driver until a fully constructed engine takes over."""

    instruments: list[InstrumentDriver] = []
    provider_transition_attempted = False
    engine: ExecutionEngine | None = None
    uncertain = False
    interruption: BaseException | None = None
    try:
        # Ownership is acquired one driver at a time before touching any driver
        # property or provider completion metadata.  A non-conforming iterable
        # that fails part-way through cannot orphan already yielded drivers.
        for instrument in provider_result.drivers:
            instruments.append(instrument)
        provider_diagnostics = list(provider_result.diagnostics)
        setup_diagnostics.extend(provider_diagnostics)
        provider_summary = {
            **provider_entry.summary,
            **_provider_result_evidence(
                provider_id=provider_id,
                provider_result=provider_result,
                instruments=instruments,
                diagnostics=provider_diagnostics,
            ),
        }
        provider_transition_attempted = True
        transition_committed, journal_interruption = _append_provider_transition(
            journal,
            provider_entry.model_copy(
                update={
                    "state": (
                        "failed"
                        if has_blocking_diagnostics(provider_diagnostics)
                        else "completed"
                    ),
                    "diagnostics": provider_diagnostics,
                    "summary": provider_summary,
                }
            ),
            setup_diagnostics,
        )
        if not transition_committed or journal_interruption is not None:
            uncertain = True
            interruption = journal_interruption
        else:
            actual_descriptions: list[InstrumentDescription] = []
            if instruments and not has_blocking_diagnostics(setup_diagnostics):
                setup_diagnostics.extend(
                    validate_instruments(config=config, instruments=instruments)
                )
                actual_descriptions, description_diagnostics = describe_instruments(
                    instruments
                )
                setup_diagnostics.extend(description_diagnostics)
                if not has_blocking_diagnostics(setup_diagnostics):
                    setup_diagnostics.extend(
                        validate_execution_program_instruments(
                            program,
                            descriptions={
                                item.instrument_id: item for item in actual_descriptions
                            },
                        )
                    )
            setup_diagnostics.extend(
                _validate_provided_descriptions(
                    advertised=advertised_descriptions,
                    actual=actual_descriptions,
                )
            )
            if not has_blocking_diagnostics(setup_diagnostics):
                engine = ExecutionEngine(
                    run_id=run_id,
                    program=program,
                    drivers={
                        instrument.instrument_id: instrument
                        for instrument in instruments
                    },
                    descriptions={
                        item.instrument_id: item for item in actual_descriptions
                    },
                    journal=journal,
                    measurements=LocalMeasurementCommitter(workspace, run_id=run_id),
                    readbacks=LocalCollectionCommitter(workspace, run_id=run_id),
                    payloads=LocalPayloadEvidenceCommitter(
                        workspace,
                        run_id=run_id,
                    ),
                    payload_observer=lambda payload: observe_payload(
                        observer=payload_observer,
                        run_id=run_id,
                        experiment_id=experiment_id,
                        payload=payload,
                    ),
                )
    except Exception as error:
        diagnostic = diagnostic_from_exception(
            "instrument_provider_result_invalid",
            f"instrument provider {provider_id} returned an invalid result",
            "instrument_provider.result",
            error,
        )
        setup_diagnostics.append(diagnostic)
        if not provider_transition_attempted:
            _append_provider_transition(
                journal,
                provider_entry.model_copy(
                    update={"state": "failed", "diagnostics": [diagnostic]}
                ),
                setup_diagnostics,
            )
    except BaseException as error:
        diagnostic = _interruption_diagnostic(
            error,
            "instrument_provider.result",
        )
        setup_diagnostics.append(diagnostic)
        if not provider_transition_attempted:
            _append_provider_transition(
                journal,
                provider_entry.model_copy(
                    update={"state": "unknown", "diagnostics": [diagnostic]}
                ),
                setup_diagnostics,
            )
        uncertain = True
        interruption = error

    if engine is not None:
        # Engine construction is the ownership hand-off.  Its run boundary is
        # responsible for abort/cleanup and terminal state capture after effects.
        return engine.run()
    return _finalize_owned_setup(
        run_id=run_id,
        experiment_id=experiment_id,
        instruments=instruments,
        diagnostics=setup_diagnostics,
        journal=journal,
        uncertain=uncertain,
        interruption=interruption,
    )


def _finalize_owned_setup(
    *,
    run_id: str,
    experiment_id: str,
    instruments: list[InstrumentDriver],
    diagnostics: list[Diagnostic],
    journal: ObservedExecutionJournal,
    uncertain: bool = False,
    interruption: BaseException | None = None,
) -> ExecutionEngineResult:
    final_state, cleanup_interruption = cleanup_after_setup_failure(
        instruments,
        diagnostics,
        run_id=run_id,
        journal=journal,
    )
    return _setup_result(
        run_id=run_id,
        experiment_id=experiment_id,
        diagnostics=diagnostics,
        final_state=final_state,
        uncertain=uncertain,
        interruption=(
            interruption if interruption is not None else cleanup_interruption
        ),
    )


def _setup_result(
    *,
    run_id: str,
    experiment_id: str,
    diagnostics: list[Diagnostic],
    final_state: Sequence[InstrumentStateSnapshot] = (),
    uncertain: bool = False,
    interruption: BaseException | None = None,
) -> ExecutionEngineResult:
    return ExecutionEngineResult(
        run_id=run_id,
        experiment_id=experiment_id,
        status=(
            "interrupted"
            if interruption is not None
            else "unknown"
            if uncertain
            else "failed"
        ),
        diagnostics=tuple(diagnostics),
        measurements=(),
        initial_state=(),
        final_state=tuple(final_state),
        points=(),
        uncertain=uncertain,
        interruption=interruption,
    )


def _validate_described_instruments(
    *,
    config: ConfigProfileSnapshot,
    descriptions: tuple[InstrumentDescription, ...],
) -> list[Diagnostic]:
    configured_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    diagnostics: list[Diagnostic] = []
    for description in descriptions:
        if not description.instrument_id:
            diagnostics.append(
                _diagnostic(
                    "instrument_missing_id",
                    "instrument_id must be non-empty",
                    "instruments.instrument_id",
                )
            )
        if not description.implementation_id:
            diagnostics.append(
                _diagnostic(
                    "instrument_missing_implementation_id",
                    "implementation_id must be non-empty",
                    f"instruments.{description.instrument_id}",
                )
            )
        if not description.implementation_version:
            diagnostics.append(
                _diagnostic(
                    "instrument_missing_implementation_version",
                    "implementation_version must be non-empty",
                    f"instruments.{description.instrument_id}",
                )
            )
        if description.instrument_id not in configured_ids:
            diagnostics.append(
                _diagnostic(
                    "instrument_not_in_config",
                    f"instrument {description.instrument_id} is not in config",
                    f"instruments.{description.instrument_id}",
                )
            )
    return diagnostics


def _validate_provided_descriptions(
    *,
    advertised: dict[str, InstrumentDescription],
    actual: list[InstrumentDescription],
) -> list[Diagnostic]:
    actual_by_id = {item.instrument_id: item for item in actual}
    diagnostics: list[Diagnostic] = []
    for instrument_id in sorted(set(advertised) - set(actual_by_id)):
        diagnostics.append(
            _diagnostic(
                "instrument_provider_missing_advertised_instrument",
                f"provider did not create advertised instrument {instrument_id}",
                f"instruments.{instrument_id}",
            )
        )
    for instrument_id in sorted(set(actual_by_id) - set(advertised)):
        diagnostics.append(
            _diagnostic(
                "instrument_provider_unadvertised_instrument",
                f"provider created unadvertised instrument {instrument_id}",
                f"instruments.{instrument_id}",
            )
        )
    for instrument_id in sorted(set(advertised) & set(actual_by_id)):
        if advertised[instrument_id] != actual_by_id[instrument_id]:
            diagnostics.append(
                _diagnostic(
                    "instrument_description_changed_after_provision",
                    f"instrument {instrument_id} differs from its advertised contract",
                    f"instruments.{instrument_id}",
                )
            )
    return diagnostics


def _interruption_diagnostic(error: BaseException, path: str) -> Diagnostic:
    return _diagnostic(
        "execution_interrupted",
        f"execution interrupted by {type(error).__name__}: {error}",
        path,
    )


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


def _execution_diagnostics(
    *,
    setup_diagnostics: list[Diagnostic],
    result: ExecutionEngineResult,
    expected_schema: MeasurementDatasetSchema | None,
    expected_indices: set[int],
) -> list[Diagnostic]:
    diagnostics = [*setup_diagnostics, *result.diagnostics]
    measurements = list(result.measurements)
    diagnostics.extend(
        validate_measurement_index_shape(
            measurements=measurements,
            expected_indices=expected_indices,
            duplicate_code="duplicate_measurement_index",
            duplicate_message="run recorded duplicate measurement",
            unknown_code="unknown_measurement_index",
            unknown_message="run recorded unknown measurement",
            missing_observables_code="missing_observables",
            missing_observables_message="measurement has no observables",
        )
    )
    if not has_blocking_diagnostics(diagnostics):
        diagnostics.extend(
            validate_raw_measurement_dataset(
                records=measurements,
                expected_schema=expected_schema,
                dataset_id="raw-measurements",
            )
        )
    return _deduplicate_diagnostics(diagnostics)


def _deduplicate_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    selected: list[Diagnostic] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for diagnostic in diagnostics:
        key = (
            diagnostic.severity,
            diagnostic.code,
            diagnostic.message,
            diagnostic.path,
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(diagnostic)
    return selected


def _planned_instrument_ids(plan: BoundPlan) -> list[str]:
    return sorted(
        {state.resource_id for point in plan.points for state in point.desired_state}
        | {
            collect.instrument_id
            for point in plan.points
            for collect in point.collect
            if collect.instrument_id is not None
        }
    )


def _append_provider_transition(
    journal: ObservedExecutionJournal,
    entry: ExecutionJournalEntry,
    diagnostics: list[Diagnostic],
) -> tuple[bool, BaseException | None]:
    try:
        journal.append(entry)
    except Exception as error:
        diagnostics.append(
            diagnostic_from_exception(
                "execution_journal_commit_failed",
                f"failed to journal {entry.operation_id}",
                "execution.journal",
                error,
            )
        )
        return False, None
    except BaseException as error:
        diagnostics.append(_interruption_diagnostic(error, "execution.journal"))
        return False, error
    return True, None


def _provider_result_evidence(
    *,
    provider_id: str,
    provider_result: InstrumentProviderResult,
    instruments: list[InstrumentDriver],
    diagnostics: list[Diagnostic],
) -> dict[str, object]:
    instrument_ids = sorted(instrument.instrument_id for instrument in instruments)
    validated_metadata = _PROVIDER_METADATA_ADAPTER.validate_python(
        provider_result.metadata
    )
    metadata = _PROVIDER_METADATA_ADAPTER.dump_python(
        validated_metadata,
        mode="json",
    )
    receipt = {
        "provider_id": provider_id,
        "instrument_ids": instrument_ids,
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
        "metadata": metadata,
    }
    return {
        "instrument_ids": instrument_ids,
        "provisioning_receipt": receipt,
        "provisioning_receipt_content_hash": stable_content_hash(receipt),
    }


def _normalize_provider_description(value: object) -> InstrumentProviderDescription:
    if not isinstance(value, InstrumentProviderDescription):
        msg = (
            "instrument provider describe must return InstrumentProviderDescription, "
            f"got {type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    wire = _PROVIDER_DESCRIPTION_ADAPTER.dump_python(value, mode="json")
    return _PROVIDER_DESCRIPTION_ADAPTER.validate_python(wire)


__all__ = ["execute_run"]

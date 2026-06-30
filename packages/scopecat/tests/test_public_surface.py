from __future__ import annotations

import inspect

import scopecat as sc
import scopecat.authoring as authoring
import scopecat.diagnostics as diagnostics
import scopecat.evaluation as evaluation
import scopecat.execution as execution
import scopecat.experiments as experiments
import scopecat.instruments as instruments
import scopecat.instruments.sdk as native_sdk
import scopecat.models as models
import scopecat.parameters as parameters
import scopecat.planning as planning
import scopecat.processing as processing
import scopecat.relations as relations
import scopecat.results as results
import scopecat.runner as runner
import scopecat.runs as runs
import scopecat.session as session_facade
import scopecat.workflows as workflows
from scopecat.session import TemplateBrowser


def test_root_public_surface_is_user_facing() -> None:
    assert set(sc.__all__) == {
        "Analysis",
        "AnalysisContext",
        "AnalysisExternalRef",
        "AnalysisOutput",
        "AnalysisStep",
        "CandidateConfig",
        "CandidateConfigReview",
        "ComparisonHandle",
        "Data",
        "Experiment",
        "ParameterGuess",
        "PromotedAnalysisStep",
        "OverviewHandle",
        "Run",
        "RunHandle",
        "SavedAnalysis",
        "Workspace",
        "open",
    }

    assert sc.Run is sc.RunHandle
    assert not hasattr(sc, "scan")
    assert not hasattr(sc, "var")
    assert not hasattr(sc, "param")
    assert not hasattr(sc, "iq")
    assert not hasattr(sc, "iq_acquisition")
    assert not hasattr(sc, "linspace")
    assert not hasattr(sc, "points")
    assert not hasattr(sc, "qty")
    assert not hasattr(sc, "opaque_asset")
    assert not hasattr(sc, "AcceptedProposalHandle")
    assert not hasattr(sc, "EvaluationHandle")
    assert not hasattr(sc, "ProcessingHandle")
    assert not hasattr(sc, "ProposalHandle")
    assert not hasattr(sc, "Routine")
    assert not hasattr(sc, "RoutineResult")
    assert not hasattr(sc, "Session")
    assert "routine" not in sc.__all__
    assert "session" not in sc.__all__
    assert {
        "AcquisitionIntent",
        "AroundSweep",
        "AssetBindingIntent",
        "Client",
        "ExperimentBindingIntent",
        "ExperimentDraft",
        "ExperimentRecipe",
        "ExperimentTemplate",
        "ExplicitVariableIntent",
        "ResolvedExperiment",
        "SweepIntent",
        "TemplateBrowser",
        "TemplateRegistry",
        "acquisition",
        "around",
        "asset_binding",
        "asset_ref",
        "bind",
        "bind_each",
        "client",
        "configure",
        "coordinate",
        "derive",
        "diagnostics",
        "experiments",
        "local_overrides",
        "local_scan",
        "new_run_id",
        "observable",
        "observe",
        "param_row",
        "param_ref",
        "parameters",
        "point_dataset",
        "point",
        "recipe",
        "requires",
        "resolve_experiment",
        "relations",
        "results",
        "resource_role",
        "rows",
        "run_experiment",
        "run_id",
        "scan_parameter",
        "shot_dataset",
        "sweep",
        "template",
        "templates",
        "trace",
        "variable",
        "var_ref",
    }.isdisjoint(sc.__all__)
    assert not hasattr(sc, "LegacySource")
    assert not hasattr(authoring, "LegacySource")
    assert not hasattr(authoring, "ExperimentAuthoringInput")
    assert not hasattr(authoring, "LegacyExperimentAuthoringInput")


def test_template_browser_uses_category_filter_vocabulary() -> None:
    signature = inspect.signature(TemplateBrowser.list)

    assert "category" in signature.parameters
    assert "domain" not in signature.parameters


def test_workspace_exposes_gui_read_entries_without_gui_models() -> None:
    assert set(inspect.signature(sc.Workspace.runs).parameters) == {"self"}
    assert "run" in inspect.signature(sc.Workspace.get_run).parameters
    assert set(inspect.signature(sc.Run.comparisons).parameters) == {"self"}
    assert "GuiRun" not in sc.__all__
    assert "Workbench" not in sc.__all__


def test_run_facade_does_not_teach_low_level_step_workflows() -> None:
    assert not hasattr(sc.Run, "process")
    assert not hasattr(sc.Run, "evaluate")
    assert not hasattr(sc.Workspace, "accept")
    assert not hasattr(sc.Workspace, "run_routine")
    assert not hasattr(sc.Workspace, "rerun_from_accepted")
    assert not hasattr(session_facade, "Session")
    assert {
        "AcceptedProposalHandle",
        "EvaluationHandle",
        "ProcessingHandle",
        "ProposalHandle",
        "Routine",
        "RoutineResult",
        "Session",
        "routine",
        "session",
    }.isdisjoint(session_facade.__all__)


def test_authoring_facade_exports_phase5_helper_vocabulary() -> None:
    for name in {
        "bind",
        "derive",
        "sweep",
    }:
        assert name in authoring.__all__
    for name in {"field_binding", "derived", "sweep_around"}:
        assert name not in authoring.__all__
        assert not hasattr(sc, name)


def test_workflows_facade_does_not_export_low_level_runner_helpers() -> None:
    assert {
        "callable_run_executor",
        "ExperimentAuthoringInput",
        "LegacyExperimentAuthoringInput",
        "native_run_executor",
        "EvaluateRunResult",
        "evaluate_run",
        "ProcessRunResult",
        "process_run",
        "runner_adapter_executor",
        "run_mode_executor",
        "start_dry_run",
        "start_native_run",
        "start_runner_adapter_run",
        "start_run",
        "CalibrationRoutine",
        "CalibrationRoutineDescription",
        "CalibrationRoutineResult",
        "CandidateReviewPolicy",
        "describe_calibration_routine",
        "RoutineRunExecutor",
        "RoutineRunStart",
        "run_calibration_routine",
    }.isdisjoint(workflows.__all__)


def test_workflows_facade_exports_candidate_review_config_activation() -> None:
    assert "RegisterAndActivateCandidateReviewResult" in workflows.__all__
    assert "register_and_activate_candidate_review" in workflows.__all__
    assert hasattr(workflows, "register_and_activate_candidate_review")


def test_planning_facade_does_not_export_legacy_planner() -> None:
    assert "build_plan" not in planning.__all__
    assert "build_legacy_plan" not in planning.__all__
    assert "validate_experiment" not in planning.__all__
    assert "validate_plan" not in planning.__all__
    assert "validate_legacy_experiment" not in planning.__all__
    assert "validate_legacy_plan" not in planning.__all__


def test_execution_facade_uses_dry_run_name() -> None:
    assert "execute_dry_run" in execution.__all__
    assert "execute_kernel_dry_run" not in execution.__all__
    assert "execute_legacy_dry_run" not in execution.__all__


def test_runner_facade_exports_context_names() -> None:
    assert "RunnerContext" in runner.__all__
    assert "RunnerAdapterBoundaryManifest" in runner.__all__
    assert "RunnerAdapterRunSnapshot" in runner.__all__
    assert "build_runner_adapter_boundary_manifest" in runner.__all__
    assert not hasattr(runner, "LegacyRunnerContext")
    assert not hasattr(runner, "LegacyRunnerAdapterRunSnapshot")
    assert "execute_runner_adapter" in runner.__all__
    assert "execute_legacy_runner_adapter" not in runner.__all__


def test_native_sdk_exports_context_names() -> None:
    assert "NativeBoundaryManifest" in instruments.__all__
    assert "build_native_boundary_manifest" in instruments.__all__
    assert hasattr(native_sdk, "NativeAcquisitionContext")
    assert hasattr(native_sdk, "NativeInstrumentProviderContext")
    assert not hasattr(native_sdk, "LegacyNativeAcquisitionContext")
    assert not hasattr(native_sdk, "LegacyNativeInstrumentProviderContext")


def test_instruments_facade_hides_legacy_executor() -> None:
    assert "execute_native_run" in instruments.__all__
    assert "execute_legacy_native_run" not in instruments.__all__


def test_processing_and_evaluation_facades_export_context_names() -> None:
    assert "ProcessingContext" in processing.__all__
    assert "EvaluationContext" in evaluation.__all__
    assert "EarlyStopDecision" in evaluation.__all__
    assert "decide_online_convergence" in evaluation.__all__
    assert "MeasurementDatasetInputDiagnostics" not in processing.__all__
    assert "MeasurementDatasetInputDiagnostics" not in evaluation.__all__
    assert not hasattr(processing, "LegacyProcessingContext")
    assert not hasattr(evaluation, "LegacyEvaluationContext")


def test_runs_facade_exports_plan_loader_name() -> None:
    assert "load_plan_snapshot" in runs.__all__
    assert not hasattr(runs, "load_legacy_plan_snapshot")


def test_modules_have_explicit_public_surfaces() -> None:
    assert set(relations.__all__) >= {
        "RelationExpr",
        "ScalarExpr",
        "grid",
        "table",
        "parameter_table",
        "col",
        "param",
    }
    assert set(parameters.__all__) == {
        "ParameterCatalog",
        "ParameterChangeSet",
        "ParameterDerivationSet",
        "ParameterPatch",
        "ParameterState",
        "ParameterTable",
        "ParameterTableColumn",
        "ParameterTableDefinition",
        "ParameterValue",
        "ParameterValueSet",
        "Quantity",
        "ScalarParameterDerivation",
        "TableParameterDerivation",
        "apply_parameter_patches",
        "build_parameter_snapshot",
        "diff_parameter_states",
    }
    assert set(experiments.__all__) >= {
        "DryRunSnapshot",
        "ExperimentSpec",
        "LocalOverrides",
        "PlanSnapshot",
        "ObservationSpec",
        "ParameterPatchPlanRecord",
        "ParameterPatchSpec",
        "ParameterRowRef",
        "ParameterScan",
        "ResultIntent",
        "configure",
        "delete_param_rows",
        "experiment",
        "insert_param_rows",
        "local_overrides",
        "local_scan",
        "observe",
        "param_row",
        "point",
        "plan_experiment",
        "rows",
        "scan_parameter",
        "set_param",
        "set_state",
        "trace",
        "update_param_rows",
    }
    assert "KernelExperimentSpec" not in experiments.__all__
    assert "KernelPlanSnapshot" not in experiments.__all__
    assert "KernelDryRunSnapshot" not in experiments.__all__
    assert "ParameterPatchRecord" not in experiments.__all__
    assert "ParameterPatch" not in experiments.__all__
    removed_derivation_alias = "Parameter" + "Transform" + "Graph"
    assert removed_derivation_alias not in models.__all__
    assert "ParameterPatch" in models.__all__
    assert "ParameterState" in models.__all__
    assert "ParameterValueSet" in models.__all__
    assert "ParameterChangeOperation" not in models.__all__
    assert "Artifact" not in models.__all__
    assert "ArtifactRef" not in models.__all__
    assert "ProcessingJob" not in models.__all__
    assert "DataArrayArtifact" not in models.__all__
    assert "DataArrayDimension" not in models.__all__
    assert "DataArraySchema" not in models.__all__
    assert "DataArrayVariable" not in models.__all__
    assert "DataColumn" not in models.__all__
    assert "DataDType" not in models.__all__
    assert "DataTableArtifact" not in models.__all__
    assert "DataTableSchema" not in models.__all__
    assert "DataVariableRole" not in models.__all__
    assert "ExecutionProfile" not in models.__all__
    assert "ProviderOptionDescription" not in models.__all__
    assert "RunEvent" not in models.__all__
    assert "RunManifest" not in models.__all__
    assert "CalibrationState" not in models.__all__
    assert "ConfigProfile" not in models.__all__
    assert "ConfigProfileSnapshot" not in models.__all__
    assert "ConfigProfileSnapshotSource" not in models.__all__
    assert "DeviceTopology" not in models.__all__
    assert "EnvironmentSpec" not in models.__all__
    assert "InstrumentRegistry" not in models.__all__
    assert "AcquisitionSpec" not in models.__all__
    assert "BindingSpec" not in models.__all__
    assert "ExperimentAsset" not in models.__all__
    assert "ExperimentVariable" not in models.__all__
    assert "Expression" not in models.__all__
    assert "ExperimentSpec" not in models.__all__
    assert "PlanSnapshot" not in models.__all__
    assert "DryRunSnapshot" not in models.__all__
    assert "SweepSpec" not in models.__all__
    assert "Diagnostic" not in models.__all__
    assert "DiagnosticSeverity" not in models.__all__
    assert "MeasurementDataset" not in models.__all__
    assert "MeasurementDatasetInputDiagnostics" not in models.__all__
    assert "MeasurementDatasetRole" not in models.__all__
    assert "MeasurementDatasetSchema" not in models.__all__
    assert "MeasurementDimension" not in models.__all__
    assert "MeasurementRecord" not in models.__all__
    assert "MeasurementVariable" not in models.__all__
    assert "LegacyPlanSnapshot" not in models.__all__
    assert "LegacyDryRunSnapshot" not in models.__all__
    assert "ParameterDefinition" not in models.__all__
    assert "SystemSpec" not in models.__all__
    assert "build_parameter_snapshot" not in models.__all__


def test_results_facade_exports_result_contracts() -> None:
    assert set(results.__all__) == {
        "ArtifactChunk",
        "ArtifactAvailabilityReport",
        "ArtifactRequirement",
        "AttemptValue",
        "ChunkedArtifactManifest",
        "MeasurementDType",
        "MeasurementDataset",
        "MeasurementDatasetInputDiagnostics",
        "MeasurementDatasetRole",
        "MeasurementDatasetSchema",
        "MeasurementDimension",
        "MeasurementRecord",
        "MeasurementSink",
        "MeasurementVariable",
        "MeasurementVariableRole",
        "PointArtifactStatus",
        "PointAttemptSummary",
        "assemble_chunked_artifact",
        "build_measurement_dataset_artifact_metadata",
        "evaluate_artifact_availability",
        "infer_measurement_dataset_schema",
        "measurement_dataset_artifact_metadata",
        "summarize_point_attempts",
        "validate_measurement_records_against_schema",
    }
    assert runner.MeasurementSink is results.MeasurementSink


def test_diagnostics_facade_exports_shared_diagnostic_contracts() -> None:
    assert set(diagnostics.__all__) == {"Diagnostic", "DiagnosticSeverity"}
    assert diagnostics.Diagnostic.model_fields.keys() == {
        "severity",
        "code",
        "message",
        "path",
    }

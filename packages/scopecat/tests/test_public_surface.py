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
import scopecat.processing as processing
import scopecat.relations as relations
import scopecat.results as results
import scopecat.runner as runner
import scopecat.runs as runs
import scopecat.workflows as workflows


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


def test_workspace_exposes_run_read_entries() -> None:
    assert set(inspect.signature(sc.Workspace.runs).parameters) == {"self"}
    assert "run" in inspect.signature(sc.Workspace.get_run).parameters
    assert set(inspect.signature(sc.Run.comparisons).parameters) == {"self"}


def test_authoring_facade_exports_current_helper_vocabulary() -> None:
    for name in {
        "bind",
        "derive",
        "sweep",
    }:
        assert name in authoring.__all__


def test_workflows_facade_exports_candidate_review_config_activation() -> None:
    assert "RegisterAndActivateCandidateReviewResult" in workflows.__all__
    assert "register_and_activate_candidate_review" in workflows.__all__
    assert hasattr(workflows, "register_and_activate_candidate_review")


def test_execution_facade_exports_dry_run_entry() -> None:
    assert "execute_dry_run" in execution.__all__


def test_runner_facade_exports_context_names() -> None:
    assert "RunnerContext" in runner.__all__
    assert "RunnerAdapterBoundaryManifest" in runner.__all__
    assert "RunnerAdapterRunSnapshot" in runner.__all__
    assert "build_runner_adapter_boundary_manifest" in runner.__all__
    assert "execute_runner_adapter" in runner.__all__


def test_instruments_facade_exports_native_boundary_names() -> None:
    assert "NativeBoundaryManifest" in instruments.__all__
    assert "build_native_boundary_manifest" in instruments.__all__
    assert "execute_native_run" in instruments.__all__
    assert hasattr(native_sdk, "NativeAcquisitionContext")
    assert hasattr(native_sdk, "NativeInstrumentProviderContext")


def test_processing_and_evaluation_facades_export_context_names() -> None:
    assert "ProcessingContext" in processing.__all__
    assert "EvaluationContext" in evaluation.__all__
    assert "EarlyStopDecision" in evaluation.__all__
    assert "decide_online_convergence" in evaluation.__all__


def test_runs_facade_exports_plan_loader_name() -> None:
    assert "load_plan_snapshot" in runs.__all__


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
    assert set(models.__all__) == {
        "ParameterBuildSnapshot",
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
    }


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

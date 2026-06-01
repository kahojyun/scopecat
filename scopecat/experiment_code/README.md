# Experiment Code Module

Route-local engineering prototype module for the accepted experiment-code
chain:

```text
recorded code context
  -> code snapshot record
  -> managed code version
  -> workspace materialization intent
  -> approved workspace materialization
  -> editable-folder observation
  -> reference-based manual rerun preparation
```

This module promotes the validated discovery candidates into the
`scopecat.experiment_code` boundary without extracting shared core models. The
promoted boundary is owned by
[`../../docs/architecture/experiment-code/engineering-prototype-promotion-decision.md`](../../docs/architecture/experiment-code/engineering-prototype-promotion-decision.md).

The recording layer represents explicit external code roots, entrypoints,
included files, capture states, declared context references, and code snapshot
records. It does not read source files, inspect Git state, scan unrecorded
folders, import code, execute code, restore environments, materialize
workspaces, or define workflow/DAG contracts.

The managed-version layer promotes declared code snapshot records into
managed-version summaries with stable identity, inventory, and integrity hints.
It remains record-only: checksums are review facts, not a storage backend,
archive contract, restore guarantee, runnable context, or Git replacement.

The materialization layers first project side-effect-free intent summaries,
then perform one bounded approved write into a caller-provided workspace root.
Approved materialization refuses overwrites and does not restore environments,
import code, execute code, inspect Git, merge workspaces, or delete files.

The editable-observation layer reads a selected editable workspace against a
selected managed version and reports digest, size, missing, redacted,
unavailable, changed, and extra-file findings. It does not perform semantic
source diff, Git diagnostics, environment readiness, code import, code
execution, or workspace mutation.

The rerun-preparation layer seeds a proposed manual rerun context from an
explicitly selected reference measurement and family-owned context links. It
does not control hardware, write parameters, mutate setup bindings, sync
environments, import code, execute code, correct drift, infer cause, guarantee
reproducibility, or define a shared context schema.

The output posture is local `review_summary` / local review projection. It is
not a portable, public, or export artifact.

## API Surface

Current local surface:

- `ExperimentCodeRecordingRequest.from_dict(...)`;
- `summarize_experiment_code_recording(...)`;
- `ExperimentCodeRecordingResult.to_dict()`;
- `build_experiment_code_recording_summary(...)`;
- `ManagedCodeVersionRequest.from_dict(...)`;
- `summarize_managed_code_version(...)`;
- `ManagedCodeVersionResult.to_dict()`;
- `build_managed_code_version_summary(...)`;
- `WorkspaceMaterializationIntentRequest.from_dict(...)`;
- `plan_workspace_materialization(...)`;
- `WorkspaceMaterializationIntentResult.to_dict()`;
- `build_workspace_materialization_intent_summary(...)`;
- `WorkspaceMaterializationRequest.from_dict(...)`;
- `execute_workspace_materialization(...)`;
- `WorkspaceMaterializationResult.to_dict()`;
- `materialize_workspace(...)`;
- `EditableFolderObservationRequest.from_dict(...)`;
- `observe_editable_folder(...)`;
- `EditableFolderObservationResult.to_dict()`;
- `build_editable_folder_observation_summary(...)`;
- `ReferenceBasedRerunPreparationRequest.from_dict(...)`;
- `prepare_reference_based_rerun(...)`;
- `ReferenceBasedRerunPreparationResult.to_dict()`;
- `build_reference_based_rerun_preparation_summary(...)`.

The typed request/result objects are the route-local engineering objects. Raw
dictionary builders remain only as edge adapters for fixture parity and current
callers. Modules with leading underscores are private implementation details.

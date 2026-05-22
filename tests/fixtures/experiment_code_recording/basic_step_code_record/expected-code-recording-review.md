# Experiment Code Recording Review

## Recording Policy

The early-adoption recording path is minimal and explicit-include-based.

Scopecat records only the files or context references the user explicitly
includes. It does not treat every file under the recorded folder as part of the
code version, and it does not scan unrecorded files to create extra warnings.

Internal Git state is not inspected in this fixture.

## Recorded Context

- Recorded root: `external-code-root-readout-demo`
- Entrypoint: `readout_calibration_entrypoint.ipynb`
- Entrypoint kind: notebook
- Recorded form: source without notebook outputs

The recorded context includes three files:

- `readout_calibration_entrypoint.ipynb`
- `experiment_session_setup.ipynb`
- `helpers/record_measurement_context.py`

Notebook outputs are stripped before recording. Checkpoints, caches, backups,
and other unlisted files are not recorded unless the user explicitly adds them
to the include list.

## Runtime And Mutation Attention

This fixture does not import, execute, or statically analyze recorded code.
Mutation capability is therefore recorded as not analyzed.

Recording does not grant execution permission.

## Captured Code Version Record

`code-version-record-0001` is a point-in-time code-version record for
future Scopecat-managed code versioning. The calibration-step record defines
its current root, entrypoint, include list, notebook output-stripping policy,
and declared environment profile reference.

This fixture does not decide managed workspace storage, Git replacement
implementation, internal Git analysis, default record-all file tracking,
package management, environment ownership, environment restoration,
saved-version selection or loading, execution, workflow DAGs, component-level
versioning, generated artifact regeneration, or GUI design.

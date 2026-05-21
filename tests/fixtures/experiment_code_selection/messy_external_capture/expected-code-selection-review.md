# Experiment Code Selection Review

## Capture Policy

The early-adoption capture path is minimal and whitelist-based.

Scopecat records only the files or context references the user explicitly
selects. It does not treat every file under the selected folder as part of the
code version, and it does not scan unselected files to create extra warnings.

Internal Git state is not inspected in this fixture.

## Selected Context

- Selected root: `external-code-root-readout-demo`
- Entrypoint: `readout_calibration_entrypoint.ipynb`
- Entrypoint kind: notebook
- Recorded form: source without notebook outputs

The selected context records three whitelisted files:

- `readout_calibration_entrypoint.ipynb`
- `experiment_session_setup.ipynb`
- `helpers/record_measurement_context.py`

Notebook outputs are stripped before recording. Checkpoints, caches, backups,
and other unlisted files are not recorded unless the user explicitly adds them
to the whitelist.

## Runtime And Mutation Attention

This fixture does not import, execute, or statically analyze selected code.
Mutation capability is therefore recorded as not analyzed.

Selection and capture do not grant execution permission.

## Captured Version Candidate

`code-version-candidate-0001` is a candidate for future Scopecat-managed code
versioning. It records the selected root, entrypoint, whitelist, notebook
output-stripping policy, and declared environment profile reference.

This fixture does not decide managed workspace storage, Git replacement
implementation, internal Git analysis, default record-all file tracking,
package management, environment ownership, execution, workflow DAGs,
component-level versioning, generated artifact regeneration, or GUI design.

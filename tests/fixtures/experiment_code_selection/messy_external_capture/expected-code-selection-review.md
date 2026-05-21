# Experiment Code Selection Review

## Selected Context

- Selected root: `external-code-root-braid-redacted`
- Entrypoint: `Braid_cali_new.ipynb`
- Entrypoint kind: notebook
- Selection basis: user-declared code context, not notebook execution or
  import-time inspection.

The selected context includes helper roots for experiment helpers,
pulse/gate helpers, and plotting/analysis helpers. Checkpoints and caches are
excluded by policy. The visible backup notebook remains ambiguity evidence,
not proof that it is wrong or should be selected.

## Version Evidence

Git is observed evidence only. The external code root has dirty Git state, and
the included `mqplot` helper root has its own dirty nested repository state.

Scopecat should preserve this as selected-code context and attention metadata.
It should not require the user to understand branch, merge, push, pull, or
submodule workflows before the selection can be useful.

## Generated Companions

The selected context links generated companions such as line info and circuit
JSON as observed or optional artifacts.

The fixture does not regenerate these companions and does not validate the
project build pipeline.

## Runtime And Mutation Attention

The selected code carries environment hints for a local Python environment,
LabRAD/Data Vault service assumptions, and MMCS/VISA-style hardware-stack
assumptions.

The selected entrypoint context is marked hardware-active and
parameter-mutating. This is an attention state. It does not grant execution
permission.

## Captured Version Candidate

`code-version-candidate-0001` is a candidate for future Scopecat-managed code
versioning. It records the selected root, entrypoint, included helper roots,
excluded classifications, and visible non-selected variants.

This fixture does not decide managed workspace storage, Git replacement
implementation, package management, environment ownership, execution, workflow
DAGs, component-level versioning, generated artifact regeneration, or GUI
design.

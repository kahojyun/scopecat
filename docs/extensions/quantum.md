# Extend quantum workflows

`scopecat-quantum` supplies hardware-independent logical gates, mixed gate and
pulse programs, implementation binding, and the checked target-compiler
boundary. A lab integration owns its parameters, wiring, compiler inputs,
runtime, and response model.

Start with the [package guide](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-quantum/README.md),
then inspect the reference lab's
[quantum compilation integration](https://github.com/scopecat-project/scopecat/tree/main/examples/reference_lab/src/reference_lab/quantum_compilation)
and
[list-mode target](https://github.com/scopecat-project/scopecat/tree/main/examples/reference_lab/src/reference_lab/targets/list_mode).

Logical point and product identity must not depend on physical batching. The
target may partition compilation, upload, shots, and acquisition inside its
declared capacity while retaining the authored measurement schema and lineage.

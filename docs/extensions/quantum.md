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

## Cache opaque target setup by content

A target that uploads reusable device content may declare connection-owned
residency on its prepared execution:

```python
from scopecat.sdk.domain import (
    DomainResidencyAddress,
    DomainResidencyRequirement,
)

residency = DomainResidencyRequirement(
    address=DomainResidencyAddress(
        instrument_id="controller",
        slot_id="readout-program",
    ),
    content_fingerprint=program_fingerprint,
)

return preparation.build(
    ...,
    setup=setup,
    setup_residency_requirements=(residency,),
)
```

The fingerprint must cover device-effective setup content but exclude physical
batch ordinals, logical point identities, and result mappings. Scopecat runs
`setup` when the current slot differs, then retains that knowledge for the live
run connection. A later host effect on the same physical instrument
conservatively invalidates its opaque slots; effects on an independently routed
LO source do not invalidate a controller program. Targets may also declare
explicit setup or realtime residency invalidations.

Residency is not an instrument interface property, device readback, or durable
resume proof. Losing the connection loses the knowledge. The driver remains the
authority that performs an idempotent ensure and invalidates any lower-level
cache when its device session is reset.

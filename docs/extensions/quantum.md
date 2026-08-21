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

Residency also does not imply archival. Scopecat does not automatically publish
compiled programs, waveform payloads, or a run-level catalog of their
fingerprints. Many useful workloads intentionally create large or random
one-off sequences, and a cache identity is not evidence that users need the
content after the connection closes. When reproducibility requires a random
logical sequence, authors should make its seed or selected logical sequence an
experiment input and record that value with the results. A canonical pulse,
compiled artifact, or inspection is retained only through an explicit artifact
publication chosen by the workflow that will consume it.

## Choose transition evidence by recovery value

Prepared executions use write-ahead transition persistence by default. Their
invocation is durable before setup or realtime start, and their terminal
receipt is durable before result realization. Externally managed jobs for which
the latest submitted identity must survive an executor loss should retain this
mode.

A synchronous target may instead amortize transition transport and SQLite
transactions when losing the latest small progress window is inexpensive:

```python
return preparation.build(
    ...,
    transition_policy="batched",
)
```

Batched transitions retain their order and are appended in count-bounded atomic
groups; elapsed point time does not turn a slow hardware sweep back into one
storage transaction per point. A pending checkpoint always forces the
invocation and checkpoint to be durable before the target is resumed, and the
final pending group is flushed before instruments are released. A hard executor
loss can omit the latest unflushed group; a normally terminated run still
flushes its complete transition ledger. The run terminal records only a compact
summary and whether those details are complete, so a dense synchronous sweep
does not duplicate every target attempt into one large JSON object. This setting
changes evidence durability, not hardware ordering, target batching, or
ownership of an independently routed LO.

A synchronous target whose successful calls are cheap to repeat and already
represented by measurement coverage may omit its normal lifecycle ledger:

```python
return preparation.build(
    ...,
    transition_policy="abnormal_only",
)
```

This policy writes no invocation or terminal row for an ordinary synchronous
success. A negative receipt is retained together with its complete invocation;
an interruption without a receipt retains the invocation alone, and a completed
receipt is retained if host result realization then fails. If the runtime
does return a checkpoint, Scopecat promotes that execution to the complete
ledger before `resume` and later closes it with its terminal receipt. The compact
run evidence lists the policies it observed, so an empty current-job projection
is distinguishable from missing required details.

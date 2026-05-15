# JC-001 Journey Selection Note

## Status

Historical selection record. The active accepted boundary lives in
[`decisions/passive-evidence-view.md`](decisions/passive-evidence-view.md).

## Why This Journey Was Selected

`JC-001` was selected because it tested high-value evidence recovery without
requiring Scopecat to own execution, hardware, environment management,
write-back, rollback, old-history import, or lab truth.

The selected fixture shape was a small redacted configuration bundle:

```text
compact root config files
  -> broader runtime-selected setting bundle
  -> generated or copied sidecars
  -> variant and backup evidence
  -> non-executed code-shaped clues
```

The key product bet was that a user can get value from passive explanation of
ordinary existing files before Scopecat records or controls the experiment.

## Acceptance Pressure

| Pressure | Reason it mattered |
| --- | --- |
| `PN-002` | Selected context was ambiguous across root config, runtime settings, generated sidecars, copied snapshots, and variants. |
| `PN-006` | Code-shaped evidence could explain settings selection and derivation without managed execution. |
| `PN-005` | Readiness hints mattered before hardware execution, but only as static evidence. |
| `PN-001` | A compact config or run-bound snapshot alone could not explain the bundle without companion artifacts and provenance. |

## Selection Guardrails

The journey had to keep artifacts as evidence rather than truth, preserve
observed/inferred/generated/copied/missing distinctions, expose conflicts, and
stay public-safe.

The journey explicitly rejected code execution, notebook execution, driver or
hardware contact, package installation, environment mutation, write-back,
repair, rollback, old-history import, full ELN/report scope, and authoritative
ownership of parameters, setup, code execution, notebook state, physical truth,
or arbitrary legacy-file truth.

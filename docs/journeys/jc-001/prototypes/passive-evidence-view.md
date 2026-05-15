# JC-001 Passive Evidence View Prototype

## Status

Fixture validated; continue as prototype script. This is not a subsystem spec,
product UI design, storage schema, parser framework, support-export policy,
execution runner, or hardware integration plan.

## Purpose

Record the fixture-backed validation for the accepted passive evidence-view
boundary in
[`../decisions/passive-evidence-view.md`](../decisions/passive-evidence-view.md).

Current implementation:

- [`../../../../prototypes/jc001_passive_evidence_view.py`](../../../../prototypes/jc001_passive_evidence_view.py)
- [`../../../../tests/test_jc001_passive_evidence_view.py`](../../../../tests/test_jc001_passive_evidence_view.py)
- `tests/fixtures/jc001-layered-config-bundle/`
- `tests/fixtures/jc001-minimal-unknown/`

Validation command from the repository root:

```sh
python3 -m unittest tests.test_jc001_passive_evidence_view
```

## Prototype Goal

Given one committed public-safe fixture directory and one caller-provided
output directory, produce:

- `evidence-view.json`;
- `evidence-view.md`.

The output should let a user answer:

- what files appear to matter;
- why each artifact matters;
- which artifacts appear selected, generated, copied, variant, setup, unknown,
  or code-shaped;
- which artifacts conflict or preserve backup ambiguity;
- which useful facts are missing;
- which source details are public-safe or redaction-sensitive;
- what should be checked next before analysis, handoff, or reuse.

The prototype must preserve ambiguity. It must not choose authoritative
configuration, silently hide conflicts, imply hardware truth, execute code, or
mutate the input fixture.

## Inputs And Outputs

Accepted inputs:

- one fixture manifest;
- manifest-listed JSON artifacts;
- static code text artifacts;
- opaque non-JSON artifacts preserved for inventory-only handling;
- one output directory outside the fixture.

Fixed outputs:

- `evidence-view.json`;
- `evidence-view.md`.

Detailed manifest, public ID, redaction-handle, fixture-local path, and public
JSON/Markdown rules are owned by
[`../contracts/manifest-and-public-output.md`](../contracts/manifest-and-public-output.md).

## Validated Behavior

The two fixtures validate that the prototype can:

- emit the accepted report sections from
  [`../contracts/evidence-view.md`](../contracts/evidence-view.md);
- include all manifest-listed artifacts in the role inventory;
- normalize roles while preserving `unknown`;
- represent anchor, selected-context, generated, copied, code-reference,
  variant, backup, missing-fact, conflict, and redaction relations;
- preserve root/selected-context drift, setup-context drift, partial snapshot
  ambiguity, and zero-conflict cases;
- report missing facts conditionally based on observed artifact families;
- represent static readiness hints without accepting managed execution;
- read code artifacts as text only;
- reject output directories inside the input fixture;
- reject paths that escape the fixture root;
- convert fixture, JSON, read, and write errors into prototype-scoped errors;
- run from a clean checkout with stdlib tooling.

The prototype also validates public-output behavior: non-public artifact
labels, bundle metadata, redaction-policy metadata, and source-derived status
text are redacted in Markdown and JSON while role and relation existence remain
visible.

## Fixture Strategy

Use tiny committed public-safe fixtures. They must not include real paths,
usernames, hardware identifiers, network addresses, calibration values,
lab-specific labels, or large notebook content.

Committing fixtures keeps clean-checkout validation possible and makes the
artifact shapes visible. It does not imply arbitrary fixture import, shipped
sample data, or public documentation examples.

## Validated Boundary

| Check | Pass condition |
| --- | --- |
| Read-only behavior | The prototype does not modify input fixtures and rejects output inside the fixture. |
| No execution | Code artifacts are text-only evidence. |
| Role inventory | Every manifest-listed artifact appears with a normalized role or `unknown`. |
| Relation coverage | Accepted relation types can be represented. |
| Conflict visibility | Drift and ambiguity stay visible. |
| Missing facts | Useful gaps remain explicit but are not required inputs. |
| Sharing boundary | Public-safe output preserves evidence role and relation existence while redacting unsafe details. |
| No authority claim | The report does not declare selected context, registry, setup, or code authoritative. |

## Reopen When

Reopen prototype scope when:

- a validated boundary check fails;
- a new fixture family reveals a role, relation, conflict, missing fact, or
  sharing shape the prototype cannot represent;
- another journey needs to reuse the same evidence-view behavior;
- a user-facing command surface needs this behavior.

Otherwise, treat new pressure as input for a later journey, baseline note, or
evidence-backed decision.

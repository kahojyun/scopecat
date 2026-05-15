# JC-001 Evidence View Contract

## Status

Accepted at fixture scale for the `JC-001` passive evidence-view prototype.
This is not a general domain model, storage schema, parser framework, UI spec,
or subsystem boundary.

## Purpose

Define the minimal vocabulary and report shape that the accepted passive
evidence view depends on. Detailed public identity and redaction rules live in
[`manifest-and-public-output.md`](manifest-and-public-output.md).

## Scope

The evidence view explains one bounded work bundle by reading fixture-listed
artifacts and static code text. It preserves roles, relations, conflicts,
missing facts, and sharing boundaries. It does not execute code, inspect live
hardware, install dependencies, repair files, choose authoritative truth, or
generalize to arbitrary legacy folders.

## Minimal Concepts

| Concept | Meaning in this slice |
| --- | --- |
| Work bundle | The bounded set of files and references being explained together. |
| Artifact | A file, reference, or synthetic fixture item that may carry evidence. |
| Artifact role | The reason an artifact matters to the user. |
| Evidence handling | Whether a fact is observed, inferred, generated, copied, user-declared, unchecked, unsafe-to-inspect, or missing. |
| Relation | A directed explanation link between artifacts, the bundle, or missing facts. |
| Conflict | A visible disagreement or ambiguous relation that the report must not silently resolve. |
| Sharing boundary | The disclosure handling for an artifact, field, or report section. |

## Role Vocabulary

The accepted fixture vocabulary is intentionally small:

- `anchor`;
- `selected context`;
- `generated sidecar`;
- `copied snapshot`;
- `variant`;
- `code reference`;
- `setup evidence`;
- `readiness hint`;
- `unknown`;
- `fixture-authored`.

`Generated sidecar` is fixture wording for legacy colocated artifacts. Broader
product docs should prefer `companion artifact` unless describing this fixture
role.

## Relation Vocabulary

The accepted fixture relation types are:

- `anchors`;
- `appears-selected-for`;
- `generated-from`;
- `copied-from`;
- `references-code`;
- `has-variant`;
- `has-backup`;
- `missing-fact`;
- `conflicts-with`;
- `redacts`.

These relations explain evidence. They do not assign source-of-record
authority or decide scientific validity.

## Report Shape

The Markdown report should preserve these sections:

1. Bundle summary.
2. Artifact-role inventory.
3. Selected-context explanation.
4. Generated and copied relation summary.
5. Code-reference summary.
6. Static readiness hint summary.
7. Variant, backup, and unknown artifact summary.
8. Conflict and missing-fact report.
9. Sharing-boundary summary.
10. Next checks.

The report should avoid a single trust score. It should show the specific
reasons a bundle is explainable, ambiguous, stale, incomplete, or unsafe to
share.

## Deferred

Later journeys or decisions must own:

- internal-safe, external-support-safe, and unsafe-to-share policy;
- stable product API or storage schema;
- notebook parsing or execution;
- binary payload inspection;
- code identity, environment solving, or managed execution;
- known-good comparison or scientific equivalence;
- hardware/setup verification or mutation.

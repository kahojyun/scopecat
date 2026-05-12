# JC-001 Passive Evidence View Prototype Scope

## Status

Ready for implementation spike; fixture strategy selected.

## Purpose

Define the first implementation-facing prototype for the accepted passive
evidence-view boundary in
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md).

This scope turns the validated static-analysis spike into a small prototype
target. It is not a subsystem spec, product UI design, storage schema, parser
framework, support-export policy, execution runner, or hardware integration
plan.

## Prototype Goal

Build the smallest read-only prototype that can open the `JC-001` synthetic
fixture and produce an evidence view with:

- artifact-role inventory;
- selected-context explanation;
- generated-sidecar and copied-snapshot relations;
- static code-reference summary;
- variant and backup ambiguity;
- conflict report;
- missing producer-fact report;
- sharing-boundary summary;
- next-check recommendations.

The prototype should prove that the accepted evidence-view boundary can move
from research spike output to project-owned implementation without widening
scope.

## User-Facing Behavior

Given a bundle path, the prototype produces a structured evidence view and a
human-readable report.

The output should help a user answer:

- What files appear to matter?
- Why does each artifact matter?
- Which artifacts appear selected, generated, copied, variant, backup, setup,
  or code-shaped evidence?
- Which artifacts conflict?
- Which producer facts are missing?
- Which facts are public-safe versus internal-safe?
- What should be checked next before analysis, handoff, or reuse?

The output must preserve ambiguity. It should not choose an authoritative
configuration, silently hide conflicts, or imply hardware truth.

## Prototype Inputs

Required input:

- one `JC-001` synthetic fixture directory;
- fixture manifest;
- JSON artifacts listed by the manifest;
- static code text artifacts listed by the manifest.

Optional input for this prototype:

- a caller-provided output path;
- a caller-selected report format from the supported prototype outputs.

Out of scope:

- arbitrary legacy folders;
- notebooks;
- binary artifacts beyond safe categorization;
- hidden global config;
- network sources;
- live environment inspection.

## Prototype Outputs

The prototype should produce:

- `evidence-view.json` as the structured output;
- `evidence-view.md` as a readable report.

The structured output should use the first-wedge vocabulary from
[`jc-001-concepts-and-contracts.md`](jc-001-concepts-and-contracts.md):

- artifact roles: `anchor`, `selected context`, `generated sidecar`,
  `copied snapshot`, `variant`, `backup`, `code reference`, `setup evidence`,
  `readiness hint`, `unknown`, and fixture/tooling-only labels when needed;
- relation types: `anchors`, `appears-selected-for`, `generated-from`,
  `copied-from`, `references-code`, `has-variant`, `has-backup`,
  `missing-fact`, `conflicts-with`, and `redacts`;
- evidence handling: observed, inferred, generated, copied, user-declared,
  unchecked, unsafe-to-inspect, and missing;
- sharing boundaries: internal-safe, public-safe, external-support-safe,
  redaction-sensitive, unsafe-to-share, or fixture-specific public synthetic
  labels.

The Markdown report should include the nine evidence-view sections already
accepted by the concepts document:

1. Bundle summary.
2. Artifact-role inventory.
3. Selected-context explanation.
4. Generated and copied relation summary.
5. Code-reference summary.
6. Variant, backup, and unknown artifact summary.
7. Conflict and missing-fact report.
8. Sharing-boundary summary.
9. Next checks.

## Minimal Implementation Shape

Because the repository currently has no product code layout, the first
implementation should stay deliberately small:

- one prototype entry point that accepts a fixture directory and output
  directory;
- one analyzer path that reads the manifest, JSON files, and static code text;
- one evidence-view builder that emits structured records;
- one Markdown renderer;
- focused fixture-level tests or snapshot checks.

The implementation may reuse the non-public research spike as a behavioral
reference, but the project-owned prototype should not depend on a local
absolute path or on the research repository being present.

## Fixture Strategy

Decision: the first implementation spike should commit a tiny public-safe
fixture with the prototype tests.

This choice optimizes for a portable clean-checkout run. The prototype should
not depend on the non-public research workspace, local absolute paths, or a
generated fixture that hides the artifact shapes the journey is meant to
exercise.

Rejected alternatives:

| Strategy | Use when | Tradeoff |
| --- | --- | --- |
| Require a caller-provided fixture path | The prototype should avoid committing any fixture data yet. | Keeps the repo smaller, but automated tests need a fixture path or generated fixture. |
| Generate the fixture in tests | The prototype should keep fixture data close to test intent. | Reduces checked-in data, but fixture generation can hide readability problems. |

The committed fixture should be derived from the existing synthetic fixture and
kept intentionally small. It must not include real paths, usernames, hardware
identifiers, network addresses, calibration values, lab-specific labels, or
large notebook content.

Recommended implementation location:

```text
tests/fixtures/jc001-braid-config/
```

That location is intentionally test-owned until the project has a broader
fixture or sample-data policy. It should not imply that fixture import,
shipping sample data, or public documentation examples have been accepted.

## Acceptance Checks

| Check | Pass condition |
| --- | --- |
| Read-only behavior | Running the prototype does not modify input fixture files. |
| No execution | The prototype reads code artifacts as text and never imports, executes, installs, or shells out to fixture code. |
| Role inventory | The evidence view contains every manifest-listed artifact with a normalized role or explicit `unknown`. |
| Relation coverage | The evidence view can represent anchor, selected-context, generated, copied, code-reference, variant, backup, missing-fact, conflict, and redaction relations. |
| Conflict visibility | Root/selected context drift, setup-context drift, and partial snapshot ambiguity remain visible. |
| Missing facts | Preferred anchor, selected settings authority, generated sidecar freshness, snapshot coverage, and code identity gaps remain explicit. |
| Sharing boundary | Public-safe output preserves artifact roles and relation existence without leaking sensitive details. |
| No authority claim | The report never declares a selected context, registry, setup, or code reference authoritative unless producer facts explicitly say so. |
| Portable run | The prototype can run from a clean checkout using only documented inputs, committed test fixture data, and local tooling. |

## Non-Goals

Do not build these in the first prototype:

- package/plugin architecture;
- database or durable storage;
- product UI;
- background service;
- notebook parser or executor;
- hardware, driver, or environment integration;
- write-back, repair, normalization, rollback, or calibration mutation;
- general legacy importer;
- support-export redaction workflow;
- source-of-record authority model;
- numeric confidence score.

## Implementation Risks

| Risk | Handling |
| --- | --- |
| Prototype becomes a general parser too early. | Keep the fixture strategy explicit and reject arbitrary legacy folder claims. |
| Static code references look like executable provenance. | Label all code evidence as text-only and not executed. |
| Public-safe view loses diagnostic value. | Preserve role and relation existence even when details are redacted. |
| Producer facts get treated as required inputs. | Treat them as missing-fact output until a later write-side decision exists. |
| Test fixture drifts from the accepted journey. | Keep acceptance checks tied to `JC-001` and update this scope if the journey changes. |

## Next Step

Start the implementation spike with a small committed public-safe test fixture,
a read-only analyzer, and JSON/Markdown output. Validate it against the
`JC-001` fixture-sized acceptance checks above.

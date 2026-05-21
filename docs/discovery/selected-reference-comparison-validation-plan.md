# Selected Reference Comparison Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a first fixture boundary for selected-reference comparison.
It does not accept a final comparison engine, equivalence score, known-good
contract, setup truth contract, scientific-validity claim, raw-data comparison,
fit-quality comparison, or GUI design.

## Source Material

The first fixture should build on already validated discovery pressure:

- selected measurement export for explicit selection and non-recursive context;
- running measurement inspection for declared preview metadata;
- parameter state management for selected parameter-state references;
- setup binding for selected setup-binding and station-registry references;
- the selected-reference problem brief for finding vocabulary and
  scientific-comparability limits.

## Validation Question

Can Scopecat show useful context differences between a current measurement and
a user-selected reference without claiming the reference is known-good,
explaining the data difference, or proving scientific comparability?

First fixture:

- `tests/fixtures/selected_reference_comparison/basic_context_compare/`

## Concept Boundary

The first selected-reference boundary should distinguish:

| Concept | Meaning In This Plan |
| --- | --- |
| Current measurement | The measurement the user is inspecting or trying to understand now. |
| Selected reference | A user-chosen comparison anchor, such as last-working, best-observed, known-good, or simply relevant. The first fixture does not claim known-good. |
| Named input snapshot | Run-start context such as parameter state, setup binding, or station registry reference. |
| Declared preview metadata | Shape and role metadata sufficient to say whether a quick visual comparison is plausible. |
| Comparison finding | A precise finding label: changed, missing, unverified, redacted, unlinked, same-observed, or not-compared. |

The fixture compares declared context. It should not inspect raw data, execute
code, score equivalence, validate scientific comparability, or infer physical
setup truth.

## First Fixture Shape

The first fixture should stay small:

- one current measurement;
- one selected reference measurement;
- a reference reason such as `last_working_reference`;
- explicit `known_good_claim: not_claimed`;
- matching experiment/sample/cooldown labels;
- named input snapshots for parameter state, setup binding, and station
  registry on both sides;
- same-observed setup binding;
- changed parameter state;
- same declared preview metadata;
- one missing current fit artifact;
- one unlinked reference analysis note;
- one unverified declared sample fact;
- one redacted station connection fact;
- one not-compared scientific-equivalence finding.

## Expected Output

Expected review output should let a reviewer answer:

- why the reference was selected;
- whether known-good or scientific comparability is claimed;
- which named input snapshots changed or matched;
- whether declared preview metadata matches;
- what is missing, unlinked, unverified, redacted, same-observed, changed, or
  not compared;
- that findings are context comparison results, not cause attribution.

## Out Of Scope

This plan does not earn:

- final comparison engine;
- known-good reference contract;
- scientific comparability or equivalence scoring;
- setup truth;
- automatic cause attribution;
- raw-data or waveform comparison;
- fit-quality comparison;
- shared run-context framework;
- GUI design.

## Current Recommendation

Create one fixture and expected output before writing any implementation
candidate. The first goal is to validate the comparison-report boundary and
finding vocabulary, not to build a comparison engine.

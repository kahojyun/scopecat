# JC-001 Static Analysis Spike

## Status

Ready; promoted by accepted decision.

## Question

Can a narrow static analyzer generate the `JC-001` evidence view from the
synthetic fixture while preserving roles, relations, conflicts, missing facts,
and sharing boundaries, without executing code or mutating source files?

This spike is scoped by
[`jc-001-concepts-and-contracts.md`](jc-001-concepts-and-contracts.md). It is
not a product parser framework, storage schema, execution runner, fixture
importer, hardware verifier, or public export policy.

## Method

The spike used the public-safe synthetic fixture and produced an evidence view
from:

- the fixture manifest;
- JSON artifact shapes and declared relation hints;
- static code text clues from illustrative pseudocode;
- fixture redaction policy.

The analyzer did not:

- import or execute fixture code;
- install dependencies;
- inspect hardware or live environment state;
- write back to the fixture;
- infer source-of-record truth;
- expose real paths, user names, hardware identifiers, or calibration values.

The non-public research workspace contains the spike analyzer and generated
`JSON`/Markdown evidence-view outputs under its `jc001-static-analysis` spike
directory.

## Result

Yes. The static analyzer generated an evidence view that preserves the minimum
contract surface:

| Required item | Result |
| --- | --- |
| Artifact roles | Preserved from the manifest and normalized to the first-wedge vocabulary. |
| Relations | Preserved as `anchors`, `appears-selected-for`, `generated-from`, `copied-from`, `references-code`, `has-variant`, `has-backup`, `conflicts-with`, `missing-fact`, and `redacts`. |
| Conflicts | Preserved as visible user-facing ambiguity instead of automatic winner selection. |
| Missing facts | Preserved as producer-side gaps, not fabricated truth. |
| Sharing boundaries | Preserved as public-safe synthetic labels plus explicit redaction behavior. |
| Execution boundary | Preserved: the analyzer reads JSON and code text only. |
| Mutation boundary | Preserved: the analyzer does not modify the fixture. |

The generated evidence view found:

- two anchor candidates;
- one selected-context candidate and one setup-context candidate;
- two generated sidecars;
- one copied snapshot;
- one manifest-only variant artifact with backup ambiguity expressed through
  relation-level evidence;
- two code-reference artifacts;
- three conflicts;
- five missing producer facts.

## Decision Impact

This validates the first wedge at spike level:

```text
existing work bundle
  -> static artifact-role inventory
  -> evidence relations
  -> conflict and missing-fact report
  -> sharing-safe evidence view
```

The validated decision is narrow: passive explanation can be useful before new
write flows, managed execution, hardware integration, known-good comparison,
or full Parameter Memory ownership.

The spike also confirms that read-side explanation creates concrete
producer-side requirements later:

- preferred bundle anchor;
- selected settings path and selection reason;
- generated sidecar source, generation time, and invalidation rule;
- run-bound snapshot coverage;
- code origin or immutable code reference.

These are write-capability implications, not requirements to build the write
path first.

## Limits

The spike does not validate:

- arbitrary legacy folder parsing;
- notebook processing;
- opaque binary handling;
- general schema inference;
- source-of-record authority;
- hardware truth;
- environment readiness;
- product UI;
- durable storage;
- support-boundary export policy.

The analyzer relied on a synthetic fixture manifest and simple JSON/text clues.
That is enough for the first decision, but not enough to claim a general bundle
import system.

## Follow-Up

Promoted by
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md),
which owns the accepted scope, deferred boundary, and future producer-fact
decision prompts.

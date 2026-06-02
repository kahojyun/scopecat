# Handoff Package Route Consolidation

## Status

Retired discovery route synthesis.

Decision status: retired.

This directory is historical discovery memory. It harvested handoff-package
validation work into a route-level view before the handoff engineering
prototype and durable Measurement Records import route became the live owners.
It does not accept a final package format, stable SDK, GUI contract, storage
import API, dataframe dependency, plotting library, archive format, signature
model, or shared measurement-record domain model.

For current implementation boundaries, use
[`handoff.md`](../../../engineering/prototype-boundaries/handoff.md),
[`handoff-durable-import-storage.md`](../../../engineering/prototype-boundaries/handoff-durable-import-storage.md),
and [`src/scopecat/handoff/README.md`](../../../../src/scopecat/handoff/README.md).
Keep validation evidence and retired route discovery synthesis here; keep
implementation-boundary guidance in the engineering prototype-boundary and module docs.

## Route Shape

The validated handoff-package posture is **open before import**:

```text
write package
  -> carry package directory
  -> preview manifest
  -> open/read package
  -> inspect plot/table/context locally
  -> optionally observe integrity
  -> optionally adapt one measurement into durable Measurement Records import
```

The package directory is the carried artifact. Local receipts, summaries,
inspection artifacts, SDK/view objects, and GUI-oriented projections are local
review surfaces around that artifact unless a future slice explicitly promotes
one of them to portable output.

## Historical Validation Map

| Track | Current slices | Earned responsibility |
| --- | --- | --- |
| Producer | Writer | Materialize one directory-shaped package from explicit selected-measurement facts. |
| Producer compatibility | Round trip | Prove current writer output can be previewed, opened, and consumed by the current reader route. |
| Receiving orientation | Contents preview | Read package manifest facts for quick orientation before file reads, integrity checks, or import. |
| Read-only package use | Opener, read view | Open a directory package, validate manifest shape, load declared primary CSV data for preview-ready measurements, and expose table/plot facts. |
| Python-facing pressure | SDK view model | Test notebook-style object access, optional dataframe adapters, plot specs, and reserved read-only analysis/fit extension points. |
| Preview/view pressure | Preview shape view, visual review, GUI view state, visual artifact, preview consumption, route pressure fixture | Test declared preview metadata, plot-first local review, GUI-ready local state, table drilldown, richer fixture pressure, and local static review output without accepting live GUI or plotting architecture. |
| Receiving composition | Inspection workflow, receiving workflow | Compose existing local review, integrity observation, and approved acceptance in the intended order. |
| Integrity observation | Integrity observation | Compare package-local observed sha256/byte-size facts to declared package facts where present. |
| Receiving mutation | Durable import adapter | Adapt one reviewed package measurement into Measurement Records durable new-record import after explicit approval, without accepting existing-record update, batch import, or conflict policy beyond no-overwrite. |
| Route-local support | Handoff package route contracts | Share repeated handoff-specific identity, package-path, preview-ready, and continuity checks where the same semantics already recur. |

## Engineering Coverage

Freezing the validation results does not mean every discovery candidate became a
live engineering surface. Use this matrix when deciding whether to update an
old validation result, the prototype-boundary notes, or the module README.

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Writer, contents preview, opener, read view, tables, integrity observation, inspection artifact, receiving gate, import plan, durable import adapter, package workflow | Promoted into route-local engineering code. The implementation may harden internals beyond the original candidate, but the live boundary belongs to the module and prototype-boundary docs. | [`src/scopecat/handoff/README.md`](../../../../src/scopecat/handoff/README.md), [`handoff.md`](../../../engineering/prototype-boundaries/handoff.md), [`handoff-durable-import-storage.md`](../../../engineering/prototype-boundaries/handoff-durable-import-storage.md) |
| Round trip and route-pressure fixtures | Partially retained as compatibility and fixture pressure. They inform engineering tests and accepted route posture, but they are not separate live product APIs. | Engineering tests plus this route README; validation results stay historical. |
| Preview shape view, preview consumption, visual review, GUI view state, SDK view model, SDK ergonomics | Retained as UX/API pressure only. Some concepts are reflected in `HandoffPackage`, `HandoffTable`, `HandoffPlotSeries`, and `build_inspection_html(...)`, but no final GUI state API, SDK view model, pandas/numpy adapter contract, or plotting layer has been promoted. | Historical validation results and future narrower decisions if a concrete workflow reopens them. |
| Candidate acceptance/storage layout | Retained only as historical engineering evidence for the first candidate storage acceptance mutation, not as the current top-level handoff API, final storage architecture, archive format, existing-record update, or conflict policy. | [`handoff-candidate-storage-acceptance.md`](../../../engineering/archive/handoff-candidate-storage-acceptance.md) |

## Accepted Local Baseline

The handoff engineering prototype has been promoted as the accepted local
implementation baseline, and later durable-import work replaced the old
candidate storage path for active import. This discovery note does not track
the live API inventory. Current accepted implementation boundaries live in the
architecture promotion and durable import decisions, and current exported API
details live in the module README.

Use
[`prototype-plan.md`](../../../engineering/archive/handoff-prototype-plan.md)
for the frozen historical prototype objective, scope, fixture policy, stop
conditions, and promotion criteria.

Use
[`prototype-readiness.md`](../../../engineering/archive/handoff-prototype-readiness.md)
for the frozen stop-criteria checkpoint that ended the prototype line.

Use
[`handoff.md`](../../../engineering/prototype-boundaries/handoff.md)
for the canonical accepted implementation boundary and next decision gate.

Use [`../../../../src/scopecat/handoff/README.md`](../../../../src/scopecat/handoff/README.md)
for the current route-local Python API surface.

## Artifact Boundary

| Surface | Boundary posture | Redaction/reference responsibility |
| --- | --- | --- |
| Package directory | Portable package artifact | Owns portable package topology, package-relative references, and package/public projection. |
| `package-manifest.json` | Portable contract/index inside the package | Must use managed identifiers and package-relative references; local display paths stay out unless explicitly accepted. |
| Copied package members | Portable package contents | Must match declared package topology and integrity facts where declared by the writer. |
| Writer return value | Local review receipt | May retain local operation facts needed for engineering review; not carried as package content. |
| Contents preview/open/read summaries | Local review/runtime projections | Validate managed references they expose, but do not become portable/public outputs. |
| SDK/view objects | Local runtime objects | May preserve useful user-facing facts; final names and dataframe dependency remain deferred. |
| Visual review/GUI state/static artifact | Local review surface | Escape rendered dynamic text and constrain structural positions where rendering occurs; broad runtime redaction is not required merely because it is visible locally. |
| Acceptance receipt | Local mutation receipt | Records what was accepted into local storage; it is not a package member or public report. |

## Stable Route Concepts

These concepts have enough repeated pressure to carry forward in handoff work:

- package identity and package-directory identity continuity;
- selected measurement identity and non-empty selected-measurement packages;
- canonical package primary data topology,
  `measurements/{measurement_record_id}/primary.csv`;
- declared preview metadata as the trusted first preview path;
- package-local primary table facts as string-valued, rectangular, local read
  facts;
- plot-first local review as the first experimental-user inspection posture;
- linked context as reference-only until a separate payload-packaging contract
  is earned;
- integrity observation as separate from authenticity, signatures, archive
  validation, and acceptance;
- explicit approval before receiving-side storage mutation;
- local review summaries as useful program state, not portable artifacts by
  default.

## Still Candidate-Local

Keep these concepts local to their current candidates until a narrower
implementation need makes them worth promoting:

- final public SDK names and package-open API beyond the accepted local
  `open_package(package_dir)` entrypoint;
- pandas/numpy adapter behavior and hard dataframe dependencies;
- live GUI routing, component hierarchy, and interactive selection;
- production plotting library and publication-grade rendering;
- scan-shape schema, automatic shape inference, trace opening, and array API;
- analysis/fit result model, fit execution, uncertainty, and write-back;
- archive extraction, package signatures, authenticity, and concurrent
  package-root mutation;
- final storage import API, existing-record updates, and storage schema;
- recursive linked-context traversal or linked-context payload import;
- shared measurement-record domain model.

## Test And Fixture Posture

Future handoff tests should prefer route behavior over restating low-level
primitive behavior:

- keep tests that prove route order, continuity, boundary separation, local vs
  portable posture, and user-visible review behavior;
- keep one negative test per new managed field category or boundary narrowing;
- avoid duplicating contract-primitive tests in every slice once a route-local
  helper owns identical semantics;
- add richer package fixtures only when they pressure a real reader UX case,
  such as multi-plot selection, no-plot table drilldown, degraded preview, or
  visible-but-not-packaged context;
- keep repository fixtures small and repository-safe; do not convert every
  discovery output into a portable/public output.

## Completed Focused Follow-Ups

- **Minimal GUI view-state candidate**: validated in
  [`gui-view-state-validation-result.md`](../../slices/measurement-records/handoff/gui-view-state-validation-result.md).
  Further GUI work should now require a new interaction, rendering, or product
  layout question rather than repeating route-level state projection.
- **Richer package fixture pressure**: validated in
  [`route-pressure-validation-result.md`](../../slices/measurement-records/handoff/route-pressure-validation-result.md).
  The route now has repository-safe pressure for multi-plot, table-only,
  shared linked-context, degraded-preview, and optional digest/size cases
  without creating another handoff implementation layer.
- **SDK ergonomics spike**: validated in
  [`sdk-ergonomics-spike-validation-result.md`](../../slices/measurement-records/handoff/sdk-ergonomics-spike-validation-result.md).
  Notebook-style use can discover measurements, get dataframe-like tables,
  get declared plot records/arrays, and keep context visible without adding
  hard pandas/numpy dependencies or finalizing the public SDK.

## Historical Next Work

The handoff discovery route is retired as current guidance. Use this directory
only as historical route synthesis and link-preserving validation context.
Current handoff implementation work should start from the architecture and
module docs named in the status section.

Do not add another handoff slice merely to restate package identity, preview
metadata, dataframe deferral, GUI deferral, or redaction boundaries. Those are
now historical route-level conclusions unless a new user workflow challenges
the accepted implementation boundary.

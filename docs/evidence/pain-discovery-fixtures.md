# Pain-Discovery Fixture Drafts

## Status

Draft validation fixtures. These are not accepted journey candidates,
contracts, schemas, product requirements, or architecture decisions.

## Purpose

These fixtures test whether several solution-shaped ideas in the evidence
inventory are real user pains, enabling capabilities, or premature design.

The main ideas under review are:

- managed execution;
- code registry or automatic code version management;
- batch or queue intent;
- explicit recording versus arbitrary code inference;
- migration support for legacy sidecars and hand-built artifact bundles.

Each fixture is public-safe and synthetic. The fixtures are intentionally small
so the user can critique the pain framing before implementation details harden.

## Fixture Set

| Fixture | Path | Main question |
| --- | --- | --- |
| Batch intent and outcome | `tests/fixtures/pain-discovery-batch-intent-outcome/` | Is the pain execution ownership, or reviewable batch intent/outcome/failure policy? |
| Code snapshot and explicit record | `tests/fixtures/pain-discovery-code-snapshot-explicit-record/` | Is a simple code snapshot plus explicit run record enough before a code registry exists? |
| Measurement record and attachments | `tests/fixtures/pain-discovery-measurement-data-attachments/` | Which outputs should become system-managed measurement data, and which remain attached artifacts? |

## Fixture 1: Batch Intent And Outcome

### Pain Tested

Notebook or IPython can already run multiple cells, but it gives weak support
for reviewing intended task order, continuing independent work after a failure,
recording retry policy, and using idle time for lower-priority calibration.

### Current Workaround

Users queue notebook cells, write loops manually, copy parameters into side
files, and decide after the fact which outputs correspond to which planned
task.

### Input Artifacts

- `batch-intent.json`: declared task list, priorities, dependencies, failure
  policy, review gates, and expected outputs.
- `outcome-log.json`: actual task statuses and links to produced records.
- `records/*.json`: tiny measurement or proposal records produced by tasks.

### Expected Scopecat Output

Scopecat should show intended versus actual execution, which failure did not
block independent tasks, which task waited for human review, and which
calibration result is only a proposal.

### Explicit Unknowns

The fixture does not prove Scopecat must own scheduling, retries, resource
locking, hardware execution, or priority arbitration. It only tests whether the
manifest and outcome record are useful enough before those capabilities exist.

### Success Criteria

The user can review the batch before leaving the lab and later understand which
tasks ran, failed, continued, waited for review, or produced proposals.

## Fixture 2: Code Snapshot And Explicit Record

### Pain Tested

Non-git users manage experiment code through copied folders, renamed files,
comments, and notebook copies. The pain may be code identity and selected
entrypoint, not a full code registry.

### Current Workaround

Users copy whole notebooks beside data, but a long notebook does not tell which
cell or function actually produced a result.

### Input Artifacts

- inert text-only code files;
- two code snapshot manifests with hashes and version notes;
- one run record that explicitly names the selected template and snapshot;
- notebook-cell evidence that is marked ambiguous unless explicitly recorded.

### Expected Scopecat Output

Scopecat should show which template snapshot was explicitly used, what helper
files were included, and what remains unknown because it was not recorded.

### Explicit Unknowns

Scopecat should not infer arbitrary notebook state, import code, execute code,
resolve a full dependency graph, or decide which copied file is canonical.

### Success Criteria

The user can decide whether code snapshot and explicit entrypoint recording
solve most provenance pain before designing a code registry or managed runner.

## Fixture 3: Measurement Record And Attachments

### Pain Tested

Legacy Data Vault-like constraints force raw-ish measurement sidecars into
nearby files. Future Scopecat records may need a cleaner system-managed
measurement table plus metadata, while cross-run analysis outputs may remain
attachments.

### Current Workaround

Users write extra files next to `NNNNN - <name>` style folders or attach
derived files without a stable source relation.

### Input Artifacts

- one primary dataframe-like measurement CSV;
- metadata with axes, units, task relation, and context refs;
- attached derived summary and inert plot placeholder;
- attachment roles and source-run relations.

### Expected Scopecat Output

Scopecat should treat the primary table as system-managed measurement data,
while treating derived outputs as role-labeled attachments linked to sources.

### Explicit Unknowns

The fixture does not validate universal parsing for arbitrary binary files,
publication workflows, analysis reruns, or a final storage/API schema.

### Success Criteria

The user can separate "measurement data format Scopecat should own" from
"artifact attachments Scopecat should catalog and link."

## Review Questions

Use these prompts when reviewing the fixtures:

1. Which fixture reflects a real experiment episode most closely?
2. Which fixture still smuggles in a solution you are not confident about?
3. Which fields are necessary before leaving the lab, and which are only useful
   after something goes wrong?
4. Which fields should be produced by user code explicitly rather than inferred?
5. Which behavior would make Scopecat too close to a runner, code registry,
   deployment manager, or report generator too early?

# Brownfield Current-State Assessment

## Status

Current as-is assessment for Scopecat's brownfield adoption context.

## Purpose

Describe the existing lab workflow and artifact reality that Scopecat must
adopt around.

This document intentionally records patterns, not private local file listings.
The local sample corpus is used as a current-state reference, but stable docs
should avoid carrying private paths, hostnames, lab identifiers, or full raw
file inventories.

## Current-State Architecture

The current environment is a LabRAD/Data Vault-era experiment-code workspace,
not a clean product integration surface. Its architecture is notebook-led,
service-coupled, and file-context-heavy: experiment code, hardware runners,
parameter files, generated setup state, measurement rows, and analysis
artifacts all participate in the practical system of record.

Runtime spine:

```mermaid
flowchart LR
  Notebook["Notebook or script entrypoint"]
  Context["Active context files"]
  Runtime["Runner and driver layer"]
  Devices["Instrument and board devices"]
  Storage["Data Vault-style storage"]
  Review["Analysis and review workspace"]

  Notebook --> Context --> Runtime --> Devices
  Notebook --> Storage
  Runtime --> Storage --> Review
```

Context and artifact surfaces:

```mermaid
flowchart LR
  Manual["Human-maintained notes, wiring sheets, labels, ID lists"]
  Params["Parameter, registry, and setup files"]
  Generated["Generated chip, line, pulse, and setup companions"]
  Snapshots["Run-adjacent snapshots and dated variants"]
  Primary["Primary or partial measurement rows and companions"]
  Derived["Derived arrays, plots, workbooks, decks, reports"]
  Selected["Selected IDs, references, and role-labeled sets"]

  Manual --> Params --> Generated
  Params --> Snapshots
  Primary --> Derived --> Selected
  Manual --> Selected
  Snapshots --> Selected
```

Transfer shape:

```mermaid
flowchart LR
  Source["Control or analysis computer"]
  Bundle["Copied folder, shared export, or handoff bundle"]
  Receiver["Other computer or collaborator workspace"]
  Gaps["Portability gaps: local paths, service assumptions, missing companions"]

  Source --> Bundle --> Receiver
  Bundle --> Gaps
```

### Existing Services And Modules

Observed service and module families include:

- operator notebooks for calibration, setup inspection, plotting, analysis,
  selected-ID reopen, and practical run orchestration;
- experiment scripts and wrappers that initialize runner-facing state, prepare
  datasets, execute grid or generator sweeps, and perform cleanup;
- utility modules for dataset creation, sweep execution, unit handling,
  parameter loading, generated setup construction, plotting, and data reopen;
- active parameter and registry JSON files, generated chip/line/pulse
  companions, and wiring/setup workbooks used together as setup context;
- human-maintained setup and workflow context, including notes, labels,
  workbooks, selected-ID lists, and folder naming conventions;
- instrument-driver and runner modules that coordinate device state, waveform
  updates, local services, and hardware-facing calls;
- Data Vault-style storage services and files for dataset metadata, numeric
  IDs, row append, and later reopen;
- analysis and reporting artifacts such as arrays, notebooks, plots,
  workbooks, presentations, reports, archives, backups, and copied folders.

This is a coupled workspace architecture. The practical module boundary is
often "whatever the notebook imported and the operator remembered," not a
declared package API or deployable service boundary.

### Data Flows

```mermaid
sequenceDiagram
  participant User as Operator notebook
  participant Code as Experiment wrapper
  participant Params as Parameter, registry, and setup files
  participant Gen as Generated setup state
  participant Run as Runner and drivers
  participant Sweep as Sweep loop
  participant DV as Data Vault
  participant Live as Live grapher or plotting surface
  participant Review as Analysis and handoff artifacts
  participant Bundle as Copied or shared bundle
  participant Receiver as Other computer

  User->>Code: select experiment, target, sweep, and options
  Code->>Params: read active parameter and registry context
  Params->>Gen: derive chip, line, pulse, and setup companions
  Code->>DV: declare dataset axes, dependents, metadata, and path context
  Code->>Run: initialize runner-facing devices and waveforms
  Code->>Sweep: start grid or generator sweep with function and dataset
  Sweep->>Run: execute each point or generator step
  Run-->>Sweep: return acquired or processed point data
  Sweep->>DV: append rows or chunks
  DV-->>Live: expose appended rows for live inspection
  alt Operator interrupts an unpromising run
    User-->>Sweep: interrupt or stop sweep
    Sweep->>DV: leave partial rows and incomplete lifecycle evidence
  else Run continues
    Sweep->>DV: keep appending rows until completion
  end
  Params->>Review: copy or preserve run-adjacent snapshots
  DV->>Review: reopen selected numeric IDs and primary rows
  User->>Review: create plots, arrays, workbooks, reports, and notes
  User->>Bundle: copy selected data, context, and derived artifacts
  Bundle-->>Receiver: inspect or continue analysis with portability gaps
  opt Calibration or tuning feedback
    Review->>Params: propose or directly write parameter changes
    Params->>Gen: regenerate setup companions for later runs
  end
```

The main current-state flows are:

- run preparation: notebook/script selection -> config imports -> parameter,
  registry, and setup reads -> generated setup companions -> runner/device
  setup;
- measurement recording: wrapper prepares Data Vault metadata -> sweep loop
  runs points -> rows or chunks are appended -> partial data may exist after
  abort or interruption;
- live inspection and early stop: appended rows can be inspected through live
  graphing or plotting surfaces, and operators may interrupt unpromising runs
  before the intended scan completes;
- parameter context preservation: active JSON may be copied near a run, saved
  as a dated variant, diffed through helper code, or overwritten by calibration
  paths;
- analysis and handoff: selected numeric IDs and session/path context are used
  to reopen data, then notebooks and helpers produce derived arrays, plots,
  reports, workbooks, and sharing material;
- computer-to-computer transfer: useful results may be copied as folders,
  shared exports, or ad hoc bundles, where local paths, service assumptions,
  missing companions, and unclear source identity become receiver-side
  inspection problems;
- calibration or tuning feedback: review and analysis can become proposed or
  direct parameter changes, which then affect generated setup companions and
  later runs.

### Integrations

Current integrations are mostly implicit and local:

- LabRAD/Data Vault provides live dataset creation, row append, metadata, and
  selected-run reopen behavior;
- instrument services and drivers provide board control, LO/DC
  source control, ADC/DAC channel behavior, waveform upload, trigger handling,
  and cleanup;
- LabRAD unit/value semantics appear in sweep and experiment code;
- local Python/Jupyter imports, private helper packages, and local path
  assumptions connect notebooks to scripts, data directories, and generated
  files;
- workbook and registry generators connect physical wiring/setup information
  to generated runtime-facing mappings;
- manually maintained notes, workbook tabs, folder names, selected-ID lists,
  and labels act as context sources but are not stable machine-readable
  contracts;
- optional local persistence helpers, lock-like files, and backup folders act
  as informal versioning or edit-state evidence.

### Deployment And Runtime Shape

The existing system appears to run as an operator-managed workstation workflow:

- an operator starts local services, opens a Jupyter environment, and runs
  notebooks or scripts from an editable workspace;
- the code assumes service availability, local data directories, local helper
  imports, and hardware-driver access rather than a sealed application
  deployment;
- notebooks and scripts can be both review surfaces and hardware-active
  entrypoints;
- state lives across active JSON, generated temp companions, Data Vault files,
  notebooks, output artifacts, service state, and hardware state;
- selected work can move to another computer through copied folders, shared
  storage, or manually assembled bundles rather than a declared portable
  package;
- copied workspaces, nested repositories, backups, caches, checkpoints, and
  dated variants make deployment identity and selected-code identity ambiguous.

### Known Limitations And Technical Debt

- Artifact and authority ambiguity: tables, Data Vault-style metadata, NumPy
  arrays, JSON records, notebooks, workbooks, reports, generated companions,
  sidecars, backups, lock-like files, and dated variants can all appear useful
  without declaring which source is authoritative.
- Runtime coupling: measurement recording and later data access depend on
  LabRAD/Data Vault semantics, local services, session/path conventions,
  numeric IDs, runner code, driver timing, device state, abort behavior,
  cleanup, and recovery habits.
- Active-code risk: existing scripts and notebooks can be hardware-active,
  parameter-mutating, or environment-dependent, so treating them as passive
  artifacts can be unsafe or misleading.
- Parameter and setup drift: active parameter JSON, generated companions,
  human-maintained workbooks, notes, labels, selected-ID lists, and folder
  conventions can drift from each other while still shaping run interpretation.
- Lifecycle ambiguity: lazy dataset creation, row buffering workarounds,
  controlled aborts, partial data, suppressed artifacts, and stale generated
  files blur complete versus partial versus invalid state.
- Handoff and portability fragility: selected IDs, derived arrays, figures,
  reports, notebooks, local paths, service names, host details, instrument
  addresses, helper imports, and missing companions can all become receiver-side
  gaps when work moves between computers or collaborators.

## Current User Work Patterns

### Recording Runs

Runs are recorded by experiment scripts into Data Vault-style storage and
nearby run-adjacent files, with notebooks and local folders often adding output
or context around the recorded data. Numeric IDs are generated as part of that
recording/storage process.

Current pressure:

- source identity, operator intent, primary data, transformed data, and context
  references are often inferred from nearby files and naming conventions;
- a useful run can leave evidence as a Data Vault-style dataset, generated
  numeric ID, folder, notebook output, dated table, or nearby artifact;
- run meaning depends on nearby parameter snapshots, setup references, generated
  companions, analysis outputs, and notebook-local choices.

### Selecting Measurements For Sharing

Users often need to identify a useful run or result from a mixture of data
files, notebooks, sidecar notes, reports, and folder structure.

Current pressure:

- useful measurement identity is inferred from filenames, folders, notebook
  cells, IDs, or human memory;
- transformed data and primary data can be hard to distinguish later;
- moving a result to another computer or collaborator risks losing context;
- the receiver may need to trust folder residue before they can inspect the
  data.

### Checking Context Before A Run

Users inspect parameter files, setup notes, wiring spreadsheets, code folders,
and environment state before running.

Current pressure:

- selected pre-run context is not gathered into one stable, reviewable place;
- existing systems remain authoritative for hardware apply and run start;
- evidence about readiness is scattered;
- notebooks and local scripts can hide which context was actually used.

### Maintaining Parameter And Setup Files

Users maintain parameter, registry, wiring, and setup snapshots as practical
working artifacts across run preparation, calibration, and later analysis.

Current pressure:

- multiple dated or variant parameter and registry files can coexist;
- lock files or sidecar files may indicate local editing or runtime state, but
  they do not by themselves prove current hardware state;
- setup and wiring context often lives in workbooks or notes outside the
  scripts that consume parameters;
- users may need to inspect history, compare variants, or plot parameter changes
  before they can decide which files matter for a run or analysis step.

### Checking Instrument And Service Readiness

Users often check whether instruments, services, drivers, environments, or
helper processes are ready enough before they trust a run.

Current pressure:

- readiness checks may live in scripts, notebooks, GUIs, logs, or operator
  habits rather than a stable review surface;
- failure recovery can require local knowledge about drivers, services,
  hardware state, or lab-specific restart order;
- readiness evidence is bounded and local; it does not by itself prove hardware
  safety or define recovery authority.

### Continuing Calibration Work

Calibration work often depends on interrupted notebook state, fit previews,
manual actions, proposed writes, and downstream blocking decisions.

Current pressure:

- continuation state is difficult to inspect after interruption;
- proposed writes and accepted writes can be separated from later measurement
  context;
- fit review and retry decisions often remain notebook-local or implicit;
- execution, write-back, and hardware-control concerns are entangled in the
  existing notebooks, scripts, drivers, and operator habits.

### Inspecting Running Measurements

Long-running measurements may expose partial data or progress through scripts,
temporary files, plots, or notebook output.

Current pressure:

- partial-but-useful data can be available before full completion;
- readiness and completeness are not always explicit;
- monitoring needs are real, but execution and scan control remain owned by the
  measurement code.

### Reviewing Completed Results

After a run, users often reopen stored rows or selected numeric IDs, browse
manually managed folders, analyze data, plot selected series, summarize, and
report selected results before deciding whether the data is worth preserving,
comparing, or handing off.

Current pressure:

- finding the relevant result can depend on folder names, notebook residue,
  sidecars, reports, plots, and memory rather than a records browser;
- reopening can require the original session/path context, helper code, local
  services, and operator memory, not only the stored rows;
- analysis artifacts can be mixed with primary data, transformed data,
  notebooks, figures, reports, and presentation material;
- selected "useful" results may be identified after several exploratory plots
  or notebook edits;
- later handoff or comparison depends on knowing which data is primary, which
  artifacts are derived, which review notes matter, and which context is
  missing;
- static reports or presentations can be useful review evidence, but they can
  hide which source data, transformations, and operator decisions produced the
  final result.

### Reconstructing A Reference Or Rerun

Users reconstruct a prior or known-good run by combining reference selection,
code context, parameter/setup context, and local environment evidence.

Current pressure:

- the code that mattered for a run may not be a clean Git commit;
- notebooks, helper modules, and generated environment files may all be
  relevant;
- a folder can be useful evidence without being a trustworthy execution
  environment;
- changed, missing, unverified, and not-compared facts are easy to collapse
  into vague gap language;
- reference goodness is user/domain judgment, not something Scopecat should
  claim by default;
- objective comparison needs declared context boundaries;
- reconstructing a rerun requires deciding which records, files, code folders,
  parameters, setup references, and generated artifacts still apply.

## Update Rule

Update this assessment when a new current-state pattern changes Scopecat's
brownfield assumptions.

Do not use this document to track target journeys, adoption paths, validation
maturity, implementation entrypoints, tests, or raw local file inventories.

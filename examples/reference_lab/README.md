# Scopecat Reference Lab

The reference lab is Scopecat's single runnable gallery: one four-qubit project
with virtual RF and DC sources, temperature monitor, VNA, three shared LOs, two
bare AWGs, a bare digitizer, timing controller, and oscilloscope. Its fourteen
devices and six reviewed parameter tables exercise direct control, experiments,
quantum compilation, measurement analysis, and configuration history through
the same daemon.

The compiler lowers logical drive, readout, and acquisition signals to physical
I/Q buffers and digitizer programs. Its runtime submits typed batches through
the same worker-owned bare instruments used by direct diagnostic workflows, so
both paths share physical claims and evidence. The deterministic virtual plant
feeds responses into this normal device path.

## Start the lab

From the repository root, build the source-checkout UI once and start the
project:

```sh
cd apps/scopecat-ui
pnpm install --frozen-lockfile
pnpm run build
cd ../..
uv run scopecat config check examples/reference_lab
uv run scopecat start examples/reference_lab --static-dir apps/scopecat-ui/dist
uv run scopecat open examples/reference_lab
```

The daemon chooses a loopback port and records it inside the project. Every
notebook discovers the same daemon automatically. Run a recipe in another
terminal, for example:

```sh
uv run python examples/reference_lab/notebooks/10_direct_control.py
```

The virtual world is deterministic: enabled flux bias moves the VNA notch and
changes mixing-chamber telemetry. Experiments use logical capabilities and can
be routed to compatible real devices.

## Gallery

The scripts are ordinary Python with `# %%` cells and can be followed in order.

| Script | Demonstrates |
|---|---|
| `00_lab_tour.py` | Shared inventory, routing, and parameter rows |
| `10_direct_control.py` | Live typed clients and multi-device reservation without an experiment run |
| `20_flux_spectroscopy.py` | Bias scan, complex traces, fit artifacts, and a parameter proposal |
| `21_scan_shapes.py` | Ordered point clouds, duplicate points, repeat, and snake traversal |
| `22_channel_map.py` | Physical I/Q, shared readout, demodulator, and DC channel routes |
| `23_q0_ramsey.py` | First quantum delay scan |
| `24_flux_ramsey.py` | Host DC bias composed with a quantum delay scan |
| `25_entity_routed_ramsey.py` | Point-local entity selection over reusable quantum work |
| `26_parallel_multiplexed_ramsey.py` | Parallel drives, shared readout, and two demodulation results |
| `27_channel_timing_candidate.py` | Reviewed timing candidate used by a pinned run |
| `28_channel_conflict_diagnostic.py` | Precise conflict on an overlapping physical drive route |
| `29_channel_unavailable.py` | Entity-axis IQ traces, identity selection, provenance, and one unavailable demodulation channel |
| `30_drag_calibration.py` | Calibration, analysis, candidate check, acceptance, production use, and undo |
| `32_quantum_program_inspection.py` | Typed quantum structure without hardware execution |
| `33_multichannel_dc_bias.py` | Profile/calibration join across two multichannel DC sources |
| `34_xy_lo_sweep.py` | Shared LO scan, signed IF waveforms, shared clocks, and derived carrier records |
| `35_awg_output_monitor.py` | Entityless AWG/scope diagnostic with temporary cable intent |
| `36_q0_fixed_if_lo_sweep.py` | Host-controlled LO scan bounding a fixed-IF domain program |
| `40_measurement_workbench.py` | Selection, grouping, Xarray, Arrow, and paged reads |
| `50_ragged_scope_capture.py` | Point-varying oscilloscope record length and ragged waveform slicing |

## Source map

| Path | Responsibility |
|---|---|
| `config/system-infrastructure.json` | Device inventory, target capabilities, physical routes, components, and connection policy |
| `src/reference_lab/parameters.py` | Six reviewed calibration and profile schemas |
| `src/reference_lab/quantum_compilation/` | Lab pulse recipes and point-effective compiler inputs |
| `src/reference_lab/targets/list_mode/` | Physical target model, compiler, preparation, runtime, and IQ semantics |
| `src/reference_lab/physical_policies.py` | Lab-owned IQ-offset coupling and host preparation policy |
| `src/reference_lab/provider.py` | Bare virtual device provider and coupled AWG/scope world |
| `src/reference_lab/virtual_lab/` | Injected deterministic quantum plant adapter |
| `src/reference_lab/workflows/` | Copyable experiment, analysis, and production workflows |
| `notebooks/` | User-facing recipes and their intent |
| `tests/` | Daemon, worker, target, storage, analysis, and configuration checks |

Configuration revisions are immutable. Instrument connections and startup state
belong to system configuration, reviewed scientific values belong to parameter
tables, and temporary scan axes belong to experiment invocations.

## Physical conventions shown by the lab

- Routing mounts shared LO, clock, trigger, and bank state on physical component
  owners. Equal requests coalesce at those addresses, while channel outputs stay
  independently addressable. Whole instruments remain the scheduler claim.
- External LOs are host-controlled resources outside the realtime target. Common
  quantum experiments prepare reviewed LO values around a target segment;
  specialized spectroscopy recipes schedule LO changes explicitly and record
  `carrier = LO + signed IF`.
- IQ offset closure is one named lab policy shared by host preparation and target
  compilation. It may include idle guard channels because physical coupling is
  declared explicitly rather than inferred from qubit or instrument identity.
- The target selects raw capture with target DSP or compatible onboard DSP while
  preserving one versioned integrated-IQ convention. Target and device placement
  are checked against identical known traces.
- Every compiled artifact embeds the immutable device snapshot used for
  lowering, exact event-to-channel placement, and a deduplicated physical
  footprint. Preview joins that physical layer to the authored, logical, and
  scheduled program layers without expanding the complete experiment.
- Placement also records why each event uses its selected route: configured
  routes, shared endpoints and LOs, demodulator slots, and the common timing
  domain are stable constraint nodes linked from each event.
- Target admission reports list entries, waveform bytes, event and acquisition
  counts, complete result bytes, and per-shot chunk bytes together. The runtime
  retains bounded shot chunks as one logical partitioned value; Arrow storage
  and GUI decoding preserve those partitions. The GUI requests bounded
  program-layer pages filtered by entity, resource, kind, or text.
- The list-mode runtime uses explicit load, prepare, arm, shared-trigger, and
  fetch batches. Their order is auditable; target docstrings define trigger
  session guarantees, setup invalidation, and acquisition placement.
- The AWG/scope experiment uses entityless routes because the cable is temporary
  and no qubit mapping is needed. A completely unregistered diagnostic device
  uses `temporary_instrument(...)` in a direct session instead.
- Instrument snapshots, requested state, intents, and receipts remain run
  evidence. Experiments record only scientifically meaningful values; output
  enable remains an ordinary state that an experiment may vary.

The exact conventions live beside their owners in `physical_policies.py`,
`workflows/xy_drive.py`, `workflows/awg_output_monitor.py`, and
`targets/list_mode/`. The README provides the scenario map rather than a second
target specification.

## Checks

```sh
uv run pytest examples/reference_lab/tests
uv run ruff check examples/reference_lab
uv run basedpyright examples/reference_lab
```

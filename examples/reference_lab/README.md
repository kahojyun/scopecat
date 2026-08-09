# Scopecat Reference Lab

This is the single runnable gallery for Scopecat. Virtual RF and DC sources,
temperature monitoring, a VNA, three shared LOs, two bare AWGs, one bare
digitizer, and a temporarily connected oscilloscope all belong to one
four-qubit laboratory project. Every recipe uses the same daemon, immutable
configuration history, fourteen-device inventory, and six reviewable parameter
tables: `qubits`, `iq_chains`, `lo_groups`, `readout_resonators`,
`channel_calibrations`, and `bias_profiles`.

The quantum compiler and list-mode runtime are not instruments in that inventory.
They lower logical drive/readout/acquisition signals to real I/Q DAC buffers and
ADC/demodulator programs, then submit typed device batches through the same
worker-owned bare instruments used by ordinary operations. Direct diagnostic
workflows reach the same physical AWG channels without going through the
quantum pulse facade, and therefore conflict on the same physical reservation.
The hardware runtime fetches raw ADC voltage traces from the worker and performs
target-owned signed-IF demodulation; deterministic response models are explicit
virtual-plant test inputs, not a second production result path.

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
notebook discovers that same daemon automatically.

## Gallery path

Run these scripts in order, or execute their `# %%` cells in an editor:

1. `notebooks/00_lab_tour.py` inspects the shared inventory and parameter rows.
2. `notebooks/10_direct_control.py` reserves the flux source, temperature
   monitor, and VNA together, exercises their live typed clients, and releases
   them without creating an experiment run.
3. `notebooks/20_flux_spectroscopy.py` previews and runs a DC-bias scan, records
   complex S21 traces and temperature, fits the resonator, saves table and
   figure evidence, and creates a candidate update to the
   `readout_resonators` row for `q0`.
4. `notebooks/21_scan_shapes.py` runs an ordered point cloud with duplicate
   points and a repeated two-dimensional snake-traversed grid.
5. `notebooks/22_channel_map.py` shows four physical drive I/Q pairs, one shared
   readout I/Q pair, four demodulation slots on one ADC input, and four flux
   routes spread across two two-channel devices.
6. `notebooks/23_q0_ramsey.py` introduces one Ramsey delay scan on q0.
7. `notebooks/24_flux_ramsey.py` composes q0 flux bias and Ramsey delay into one
   two-dimensional experiment.
8. `notebooks/25_entity_routed_ramsey.py` reuses the Ramsey workflow while
   point-locally switching between the q0 and q1 channel sets.
9. `notebooks/26_parallel_multiplexed_ramsey.py` runs independent q0/q1 drive
   channels concurrently, sums their shared readout waveform, and collects two
   demodulation channels.
10. `notebooks/27_channel_timing_candidate.py` proposes a reviewed q1 timing
    update and checks it with a pinned candidate config.
11. `notebooks/28_channel_conflict_diagnostic.py` shows the precise diagnostic
    for overlapping work on the q0 drive route.
12. `notebooks/29_channel_unavailable.py` keeps q0 IQ data available when the
    q1 demodulation channel reports a structured missing result.
13. `notebooks/30_drag_calibration.py` runs the two-dimensional DRAG experiment,
   analyzes it, checks the candidate without changing the default, accepts the
   reviewed `qubits` row update, uses it in a production run, and undoes the
   activation while retaining the audit trail.
14. `notebooks/31_adaptive_tuneup.py` runs a bounded tune-up, rediscovers its
   durable lineage, and resumes it to a measurement-dependent stop condition.
15. `notebooks/32_quantum_program_inspection.py` displays typed ports and the
   authored sequence/repeat/parallel structure without touching hardware.
16. `notebooks/33_multichannel_dc_bias.py` joins a named logical bias profile
    to per-qubit gain/polarity/offset calibration, applies the four resulting
    voltages through two physical DC sources, parks them, and disables every
    routed output.
17. `notebooks/34_xy_lo_sweep.py` composes one shared external LO with two bare
    AWG I/Q channel pairs, renders signed-IF waveforms, coalesces the AWG-wide
    sample/reference clocks, and records carrier frequency without manual
    post-run conversion.
18. `notebooks/35_awg_output_monitor.py` uses entityless bench resources to arm
    a temporarily cabled oscilloscope, play one physical AWG output, fetch its
    voltage trace, and keep the wiring intent in the run name and description.
19. `notebooks/40_measurement_workbench.py` demonstrates selection, filtering,
    grouping, Xarray grid restoration, Arrow export, and paged reads.
20. `notebooks/50_ragged_scope_capture.py` varies the oscilloscope record length
    while monitoring the same AWG output, then slices the resulting real ragged
    waveform data.

```sh
uv run python examples/reference_lab/notebooks/00_lab_tour.py
uv run python examples/reference_lab/notebooks/10_direct_control.py
uv run python examples/reference_lab/notebooks/20_flux_spectroscopy.py
uv run python examples/reference_lab/notebooks/21_scan_shapes.py
uv run python examples/reference_lab/notebooks/22_channel_map.py
uv run python examples/reference_lab/notebooks/23_q0_ramsey.py
uv run python examples/reference_lab/notebooks/24_flux_ramsey.py
uv run python examples/reference_lab/notebooks/25_entity_routed_ramsey.py
uv run python examples/reference_lab/notebooks/26_parallel_multiplexed_ramsey.py
uv run python examples/reference_lab/notebooks/27_channel_timing_candidate.py
uv run python examples/reference_lab/notebooks/28_channel_conflict_diagnostic.py
uv run python examples/reference_lab/notebooks/29_channel_unavailable.py
uv run python examples/reference_lab/notebooks/30_drag_calibration.py
uv run python examples/reference_lab/notebooks/31_adaptive_tuneup.py
uv run python examples/reference_lab/notebooks/32_quantum_program_inspection.py
uv run python examples/reference_lab/notebooks/33_multichannel_dc_bias.py
uv run python examples/reference_lab/notebooks/34_xy_lo_sweep.py
uv run python examples/reference_lab/notebooks/35_awg_output_monitor.py
uv run python examples/reference_lab/notebooks/40_measurement_workbench.py
uv run python examples/reference_lab/notebooks/50_ragged_scope_capture.py
```

The virtual instrument world is deterministic: enabled flux bias moves the VNA
notch and changes mixing-chamber telemetry. The experiment declarations use
logical resources and interface contracts rather than concrete driver classes,
so the same workflows can be routed to compatible real devices.

## Source map

| Path | Responsibility |
|---|---|
| `config/system-infrastructure.json` | One fourteen-device inventory, static target capabilities, one timing-domain trigger controller, component-scoped LO distribution routes, physical drive/readout I/Q routes, one ADC with four demod slots, configurable bare-device channel counts, two two-channel DC sources, and an entityless AWG/scope bench route. |
| `src/reference_lab/parameters.py` | Six reviewed calibration/profile schemas, including carrier, shared-LO, and affine IQ-mixer values; physical channel IDs and LO membership are not duplicated here. |
| `src/reference_lab/provider.py` | Deterministic bare-device provider, including shared AWGs, digitizer, the coupled AWG/scope world, and coherent two-channel bias ramps/readback. |
| `src/reference_lab/targets/list_mode/` | Compiler-owned AWG and digitizer programs, target preparation, signed-IF lowering, and the worker command adapter; the virtual-plant adapter feeds the same triggered worker/device path. |
| `src/reference_lab/workflows/` | Copyable experiment, analysis, and production workflows. |
| `notebooks/` | User-facing gallery recipes. |
| `tests/` | Real daemon, worker, storage, analysis, and configuration checks for the gallery. |

Configuration changes publish immutable revisions. Instrument connection and
startup state remain system configuration; reviewed scientific calibration
values live in the parameter tables; temporary scan axes remain invocation
inputs.

The flux routes describe active DC source channels only. A passive bias tee is
part of the lab wiring assumption, not an instrument interface or config
record. Fast-flux pulses remain quantum signals on the routed pulse target;
they are not exposed as a DC-instrument capability.

The reference DACs additionally expose optional `scopecat.dc_bias/v1`: each
named profile transition becomes one scoped driver patch per physical DAC, and
the gallery records actual voltage plus settled status for every qubit. This is
slow bias control, not a fast-flux waveform interface. The bare AWG exposes
direct entry playback plus explicit program load, entry arm, and start
operations. The target performs `prepare -> load -> arm -> one timing-domain
trigger -> fetch`; these are auditable ordering boundaries, not a claim of
cross-device atomicity.
Each trigger carries a run-scoped epoch id and the exact expected AWG/digitizer
participants. The timing adapter rejects an incomplete arm set and replays a
known epoch result without emitting another edge when the advertised operation
provides session idempotence. A plain `fire` operation provides no such
guarantee. Neither promise survives a timing-device or driver-process restart;
an unknown trigger receipt across that boundary is never retried blindly and
makes the run indeterminate under the normal worker receipt semantics.
The target artifact has list rows and an explicit per-entry trigger-phase-reset
policy, so a real driver can map the same program to hardware list memory
without changing experiment authoring. `ramp_duration`
covers the present park/operate/park UX without inventing a fast-flux trigger
abstraction.

Each physical DAC keeps one exclusivity key. Channel-level concurrent ownership
would conflict with shared device connection, trigger, and list-memory state, so
the current lab claims the whole device while still batching its routed channels.

The XY fixture keeps frequency planning in the lab integration rather than in
Scopecat core. Q0/Q1 share `drive-lo-a`, Q2/Q3 share `drive-lo-b`, and the
multiplexed readout has its own LO. The `xy_drive` facade accepts the selected
drive LO and a signed IF directly;
fixed-IF LO scans therefore remain concise, while the returned
`carrier_frequency = LO + IF` value can be recorded alongside measurements.
The facade renders the signed IF into separate real I/Q waveforms, coalesces
shared LO and AWG clock demands, and leaves each mounted DAC output independently
addressable.

The quantum target derives static LO membership and physical RF-output
components from routing. Its opaque target configuration keeps timing policy
and maps each physical I/Q channel pair to a calibration key, without repeating
entity membership. Reviewed carrier frequencies, LO setpoints, and one affine
matrix/offset calibration per physical IQ mixer come from the accepted
parameter snapshot. Shared readout tones therefore do not duplicate one mixer
calibration per qubit. Each carrier resolves against exactly one LO group, and
the compiler renders the resulting signed IF with an entry-trigger-reset phase
reference. A compiled batch projects only the AWGs, digitizers, LO groups, and
timing controller it actually uses; the configured target instrument list is
an authority boundary, not a request to reserve every possible member. ADC
input, semantic demodulation and integration, physical result representation,
and logical result address remain separate fields. The semantic intent
always requests integrated IQ. The daemon-resolved instrument catalog says
which physical acquisitions the digitizer advertises, while the lab target
configuration selects `target`, `device`, or `prefer_device` policy. Together
they deterministically lower the intent to raw ADC capture plus target-side DSP
or to the digitizer's onboard DSP acquisition. The target builder also verifies
that every route, LO, and timing reference stays inside its configured
instrument authority.
Both placements name the same versioned IQ convention: rectangular averaging
at sample-center times, `exp(-iωt)` demodulation, unity normalization at zero IF,
and factor-two single-sideband amplitude normalization otherwise. Integrated IQ
retains the raw trace unit. Known-trace conformance tests compare the complete
logical results of target and onboard placement.
That keeps a shared
ADC with four concurrent demodulators honest without promoting a universal
frequency-plan or channel-group API into Scopecat core.

The fixed-IF LO sweep is intentionally one specialized lab workflow rather than
a first-class `FrequencyPlan`. Most experiments consume reviewed carriers and LO
groups; the few spectroscopy recipes that step an LO can own that local schedule
and record both requested LO and derived carrier values. Signed IF remains
native throughout, including negative sidebands.

The AWG/scope monitor deliberately has no entity selection. Its routes identify
the same `drive-awg` CH1 used by the q0 I path plus a reusable scope input, not a
persistent cable or qubit assignment. The notebook records the temporary
connection and operator intent in the run name and description. This keeps the
ordinary workflow concise. Here the scope is known inventory and only the cable
is temporary, so a small named experiment can retain its trace. A genuinely
unregistered diagnostic device instead uses `temporary_instrument(...)` in a
direct session; that path needs driver and connection data but no entity mapping
or config publication, and intentionally does not turn an ad hoc action into a
durable experiment run.

Run-start snapshots, requested output state, command intent, and receipts remain
run evidence rather than automatic dataset variables. The monitor notebooks
record only the trace and coordinates that matter scientifically. Output enable
is deliberately ordinary requested state, not a global validation rule, because
on/off comparison can itself be the experiment. The run manifest carries a
neutral count/list summary of baseline changes, final changes, and missing final
readbacks; complete snapshots remain an opt-in evidence record.

Ragged waveform data comes from point-varying oscilloscope record length. The
former synthetic event digitizer is intentionally absent: unavailable and
failing acquisition cases remain framework tests rather than being presented as
another laboratory device abstraction.

## Checks

```sh
uv run pytest examples/reference_lab/tests
uv run ruff check examples/reference_lab
uv run basedpyright examples/reference_lab
```

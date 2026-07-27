// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api";
import type { InstrumentSessionLease, InstrumentState, InstrumentView } from "../../api-contract";
import { InstrumentsWorkspace } from "./InstrumentsWorkspace";
import {
  applyInstrumentState,
  closeInstrumentSession,
  collectInstrumentCapability,
  getActiveConfig,
  getInstruments,
  heartbeatInstrumentSession,
  openInstrumentSession,
  publishInstrumentConnection,
  readInstrumentState,
  resolveInstrumentAttention,
} from "./instrument-api";

vi.mock("./instrument-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./instrument-api")>()),
  applyInstrumentState: vi.fn(),
  closeInstrumentSession: vi.fn(),
  collectInstrumentCapability: vi.fn(),
  getActiveConfig: vi.fn(),
  getInstruments: vi.fn(),
  heartbeatInstrumentSession: vi.fn(),
  openInstrumentSession: vi.fn(),
  publishInstrumentConnection: vi.fn(),
  readInstrumentState: vi.fn(),
  resolveInstrumentAttention: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getInstruments).mockResolvedValue({
    config_entry_id: "lab-default",
    config_content_hash: "sha256:active",
    problems: [],
    items: [instrument()],
  });
  vi.mocked(getActiveConfig).mockResolvedValue(activeConfig());
  vi.mocked(openInstrumentSession).mockResolvedValue(sessionLease());
  vi.mocked(heartbeatInstrumentSession).mockImplementation(async (lease) => ({
    ...lease,
    expires_at: "2026-07-27T09:10:00Z",
  }));
  vi.mocked(readInstrumentState).mockResolvedValue(instrumentState());
  vi.mocked(applyInstrumentState).mockResolvedValue({
    status: "applied",
    problems: [],
    state: instrumentState(6_000_000_000),
  });
  vi.mocked(closeInstrumentSession).mockResolvedValue();
  vi.mocked(collectInstrumentCapability).mockResolvedValue({
    status: "collected",
    problems: [],
    readback: { values: {} },
  });
  vi.mocked(publishInstrumentConnection).mockResolvedValue();
  vi.mocked(resolveInstrumentAttention).mockResolvedValue();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("instrument workspace", () => {
  it("shows unscoped provider problems at workspace level", async () => {
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [
        {
          code: "provider_unavailable",
          message: "The optional vendor provider could not be loaded.",
          phase: "provider_preflight",
          related_locations: [],
        },
      ],
      items: [instrument()],
    });

    renderWorkspace();

    expect(await screen.findByText("Instrument provider issues")).toBeVisible();
    expect(screen.getByText("The optional vendor provider could not be loaded.")).toBeVisible();
  });

  it("lists connection and ownership without connecting on selection", async () => {
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [],
      items: [
        instrument(),
        instrument({
          spec: {
            id: "vna-1",
            kind: "vector_network_analyzer",
            driver_id: "keysight.pna",
            connection: {
              kind: "tcpip_socket",
              host: "192.0.2.12",
              port: 5025,
              timeout_seconds: 5,
            },
          },
          description: {
            instrument_id: "vna-1",
            implementation_id: "keysight.pna",
            implementation_version: "0.1",
            label: "Readout VNA",
            capabilities: [],
          },
          availability: "active",
          owner_kind: "run",
          owner_id: "run-42",
          owner_actor: null,
          expires_at: "2026-07-27T09:10:00Z",
        }),
      ],
    });

    renderWorkspace();

    expect(await screen.findByText("Drive source")).toBeVisible();
    expect(screen.getByText("Virtual · local simulator")).toBeVisible();
    expect(screen.getByText("Readout VNA")).toBeVisible();
    expect(screen.getByText("TCP/IP · 192.0.2.12:5025")).toBeVisible();
    expect(screen.getByText(/Run/).closest(".instrument-list-owner")).toHaveTextContent("run-42");
    expect(openInstrumentSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTitle("Inspect instrument vna-1"));
    expect(await screen.findByText("Read-only while owned")).toBeVisible();
    expect(screen.getByRole("button", { name: "Edit connection" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });

  it("does not duplicate a driver version prefix", async () => {
    const prefixed = instrument();
    prefixed.description = {
      ...prefixed.description!,
      implementation_version: "v1",
    };
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [],
      items: [prefixed],
    });

    renderWorkspace();

    expect(await screen.findByText("v1")).toBeVisible();
    expect(screen.queryByText("vv1")).not.toBeInTheDocument();
  });

  it("connects explicitly, reads initial state, heartbeats, and closes on unmount", async () => {
    vi.mocked(openInstrumentSession).mockResolvedValue(
      sessionLease({ heartbeat_interval_seconds: 0.01 }),
    );
    const rendered = renderWorkspace();

    await screen.findByText("Drive source");
    expect(openInstrumentSession).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Instrument session actor"), {
      target: { value: "Ada" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(openInstrumentSession).toHaveBeenCalledWith(
        "drive-source",
        "Ada",
        expect.stringMatching(/^ui-open-/),
      ),
    );
    await waitFor(() =>
      expect(readInstrumentState).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: "session-1" }),
        "drive-source",
      ),
    );
    expect(await screen.findByDisplayValue("5000000000")).toBeVisible();
    await waitFor(() => expect(heartbeatInstrumentSession).toHaveBeenCalled());

    rendered.unmount();

    await waitFor(() =>
      expect(closeInstrumentSession).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: "session-1" }),
        true,
      ),
    );
  });

  it("explains that an expired lease is quarantined instead of auto-released", async () => {
    vi.mocked(openInstrumentSession).mockResolvedValue(
      sessionLease({ heartbeat_interval_seconds: 0.01 }),
    );
    vi.mocked(heartbeatInstrumentSession).mockRejectedValue(new Error("Heartbeat failed."));
    renderWorkspace();

    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(
      await screen.findByText(/the session enters attention_required\/quarantine/i),
    ).toHaveTextContent("it is not released automatically");
    expect(screen.getByText(/An operator must resolve it before/)).toBeVisible();
  });

  it("stages typed fields locally and sends one apply command", async () => {
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const frequency = await screen.findByRole("spinbutton", {
      name: /CW frequency/,
    });
    const readOnly = screen.getByRole("spinbutton", {
      name: /Measured temperature/,
    });
    expect(readOnly).toBeDisabled();

    fireEvent.change(frequency, { target: { value: "6000000000" } });

    expect(applyInstrumentState).not.toHaveBeenCalled();
    expect(screen.getByText("1 staged field")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));

    await waitFor(() =>
      expect(applyInstrumentState).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: "session-1" }),
        "drive-source",
        [
          {
            capabilityId: "rf_output",
            fieldPath: "frequency",
            value: { value: 6_000_000_000, unit: "Hz" },
          },
        ],
        expect.stringMatching(/^ui-apply-/),
      ),
    );
    expect(await screen.findByText("Apply receipt: Applied")).toBeVisible();
  });

  it("reuses operation ids while retrying apply, collect, and close", async () => {
    vi.mocked(applyInstrumentState).mockRejectedValueOnce(new Error("Apply network failed."));
    vi.mocked(collectInstrumentCapability).mockRejectedValueOnce(
      new Error("Collect network failed."),
    );
    vi.mocked(closeInstrumentSession).mockRejectedValueOnce(
      new ApiError("The local daemon did not respond."),
    );
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const frequency = await screen.findByRole("spinbutton", { name: /CW frequency/ });
    fireEvent.change(frequency, { target: { value: "6000000000" } });

    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));
    expect(await screen.findByText("Apply network failed.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));
    await waitFor(() => expect(applyInstrumentState).toHaveBeenCalledTimes(2));
    expect(vi.mocked(applyInstrumentState).mock.calls[0]?.[3]).toBe(
      vi.mocked(applyInstrumentState).mock.calls[1]?.[3],
    );

    fireEvent.click(screen.getByRole("button", { name: "Collect" }));
    expect(await screen.findByText("Collect network failed.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Collect" }));
    await waitFor(() => expect(collectInstrumentCapability).toHaveBeenCalledTimes(2));
    expect(vi.mocked(collectInstrumentCapability).mock.calls[0]?.[4]).toBe(
      vi.mocked(collectInstrumentCapability).mock.calls[1]?.[4],
    );

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(closeInstrumentSession).toHaveBeenCalledTimes(2), {
      timeout: 2_000,
    });
    expect(vi.mocked(closeInstrumentSession).mock.calls[0]?.[2]).toBe(
      vi.mocked(closeInstrumentSession).mock.calls[1]?.[2],
    );
  });

  it("starts a new collect operation after an applied state change", async () => {
    vi.mocked(collectInstrumentCapability).mockRejectedValueOnce(
      new Error("Collect request lost."),
    );
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const frequency = await screen.findByRole("spinbutton", { name: /CW frequency/ });

    fireEvent.click(screen.getByRole("button", { name: "Collect" }));
    expect(await screen.findByText("Collect request lost.")).toBeVisible();
    const staleCollectId = vi.mocked(collectInstrumentCapability).mock.calls[0]?.[4];

    fireEvent.change(frequency, { target: { value: "6000000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));
    expect(await screen.findByText("Apply receipt: Applied")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Collect" }));

    await waitFor(() => expect(collectInstrumentCapability).toHaveBeenCalledTimes(2));
    expect(vi.mocked(collectInstrumentCapability).mock.calls[1]?.[4]).not.toBe(staleCollectId);
  });

  it("disables collection when a mixed product still has an unresolved dynamic axis", async () => {
    const mixedAxisInstrument = instrument();
    mixedAxisInstrument.description = {
      ...mixedAxisInstrument.description!,
      capabilities: [
        {
          id: "network_sweep",
          label: "Network sweep",
          fields: [],
          products: [
            {
              key: "trace",
              label: "S-parameter trace",
              dtype: "complex128",
              axes: [
                { id: "frequency", label: "Frequency", kind: "frequency", unit: "Hz" },
                { id: "receiver", kind: "receiver", size: 2 },
              ],
            },
          ],
        },
      ],
    };
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [],
      items: [mixedAxisInstrument],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      sessionLease({ descriptions: [mixedAxisInstrument.description] }),
    );

    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(
      await screen.findByText(
        /Collect is unavailable until S-parameter trace has a positive point count for Frequency/,
      ),
    ).toBeVisible();
    const collect = screen.getByRole("button", { name: "Collect" });
    expect(collect).toBeDisabled();
    fireEvent.click(collect);
    expect(collectInstrumentCapability).not.toHaveBeenCalled();
  });

  it("keeps the lease and close id available after network retries fail", async () => {
    vi.mocked(closeInstrumentSession)
      .mockRejectedValueOnce(new ApiError("Close request lost."))
      .mockRejectedValueOnce(new ApiError("Close request lost again."));
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("Interactive session connected");

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    expect(
      await screen.findByText(/the session enters attention_required\/quarantine/i),
    ).toBeVisible();
    expect(screen.getByText("Interactive session connected")).toBeVisible();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
    expect(closeInstrumentSession).toHaveBeenCalledTimes(2);
    const retainedOperationId = vi.mocked(closeInstrumentSession).mock.calls[0]?.[2];
    expect(vi.mocked(closeInstrumentSession).mock.calls[1]?.[2]).toBe(retainedOperationId);

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(closeInstrumentSession).toHaveBeenCalledTimes(3));
    expect(vi.mocked(closeInstrumentSession).mock.calls[2]?.[2]).toBe(retainedOperationId);
    expect(await screen.findByRole("button", { name: "Connect" })).toBeVisible();
  });

  it("stays on the leased instrument when closing before selection fails", async () => {
    const monitor = instrument({
      spec: {
        id: "monitor",
        kind: "temperature_controller",
        driver_id: "virtual.temperature",
        connection: { kind: "virtual" },
      },
      description: {
        instrument_id: "monitor",
        implementation_id: "virtual.temperature",
        implementation_version: "v1",
        label: "Fridge monitor",
        capabilities: [],
      },
    });
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [],
      items: [instrument(), monitor],
    });
    vi.mocked(closeInstrumentSession).mockRejectedValueOnce(new Error("Switch close failed."));
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("Interactive session connected");

    fireEvent.click(screen.getByTitle("Inspect instrument monitor"));

    expect(await screen.findByText(/Switch close failed/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Drive source", level: 2 })).toBeVisible();
    const operationId = vi.mocked(closeInstrumentSession).mock.calls[0]?.[2];

    fireEvent.click(screen.getByTitle("Inspect instrument monitor"));

    expect(await screen.findByRole("heading", { name: "Fridge monitor", level: 2 })).toBeVisible();
    expect(vi.mocked(closeInstrumentSession).mock.calls[1]?.[2]).toBe(operationId);
  });

  it("clears hidden credentials and options when the driver changes", async () => {
    const active = activeConfig();
    active.config.system.instrument_registry.instruments[0]!.connection = {
      kind: "virtual",
      credential_ref: "secret:old-driver",
      options: { seed: 42 },
    };
    vi.mocked(getActiveConfig).mockResolvedValue(active);
    renderWorkspace();

    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Edit connection" }));
    const driverId = await screen.findByRole("textbox", { name: "Driver id" });
    fireEvent.change(driverId, { target: { value: "virtual.rf_source.v2" } });

    expect(
      screen.getByText(/previous credential reference and driver options were cleared/i),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Publish default" }));

    await waitFor(() =>
      expect(publishInstrumentConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          instrumentId: "drive-source",
          driverId: "virtual.rf_source.v2",
          connection: {
            kind: "virtual",
            credential_ref: null,
            options: {},
          },
        }),
      ),
    );
    expect(openInstrumentSession).not.toHaveBeenCalled();
  });

  it("shows quarantined ownership and the operator resolution action", async () => {
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [],
      items: [
        instrument({
          availability: "quarantined",
          owner_kind: "instrument_session",
          owner_id: "session-stale",
          owner_actor: "Grace",
          expires_at: null,
        }),
      ],
    });
    renderWorkspace();

    expect(await screen.findByText("Operator resolution required")).toBeVisible();
    expect(screen.getByText("Grace")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Resolve quarantine" }));
    await waitFor(() => expect(resolveInstrumentAttention).toHaveBeenCalledWith("session-stale"));
  });
});

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <InstrumentsWorkspace daemonUnavailable={false} />
    </QueryClientProvider>,
  );
}

function instrument(overrides: Partial<InstrumentView> = {}): InstrumentView {
  return {
    spec: {
      id: "drive-source",
      kind: "signal_generator",
      driver_id: "virtual.rf_source",
      connection: { kind: "virtual" },
    },
    description: {
      instrument_id: "drive-source",
      implementation_id: "virtual.rf_source",
      implementation_version: "0.1",
      label: "Drive source",
      description: "Virtual microwave source",
      capabilities: [
        {
          id: "rf_output",
          label: "RF output",
          fields: [
            {
              id: "frequency",
              label: "CW frequency",
              access: "read_write",
              value_type: { type: "quantity", finite: true, unit: "Hz" },
            },
            {
              id: "output_enabled",
              label: "RF output",
              access: "read_write",
              value_type: { type: "bool" },
            },
            {
              id: "temperature",
              label: "Measured temperature",
              access: "read_only",
              value_type: { type: "quantity", finite: true, unit: "K" },
            },
          ],
          products: [
            {
              key: "trace",
              label: "Trace",
              dtype: "float64",
              unit: "ratio",
              axes: [{ id: "sample", kind: "sample", size: 3 }],
            },
          ],
        },
      ],
    },
    availability: "available",
    owner_kind: null,
    owner_id: null,
    owner_actor: null,
    expires_at: null,
    problems: [],
    ...overrides,
  };
}

function sessionLease(overrides: Partial<InstrumentSessionLease> = {}): InstrumentSessionLease {
  return {
    session_id: "session-1",
    lease_id: "lease-1",
    actor: "local-operator",
    config_entry_id: "lab-default",
    config_content_hash: "sha256:active",
    instrument_ids: ["drive-source"],
    descriptions: [instrument().description!],
    issued_at: "2026-07-27T09:00:00Z",
    expires_at: "2026-07-27T09:05:00Z",
    heartbeat_interval_seconds: 60,
    ...overrides,
  };
}

function instrumentState(frequency = 5_000_000_000): InstrumentState {
  return {
    instrument_id: "drive-source",
    fields: [
      {
        capability_id: "rf_output",
        field_path: "frequency",
        value: { value: frequency, unit: "Hz" },
      },
      {
        capability_id: "rf_output",
        field_path: "output_enabled",
        value: false,
      },
      {
        capability_id: "rf_output",
        field_path: "temperature",
        value: { value: 0.02, unit: "K" },
      },
    ],
  };
}

function activeConfig(): Awaited<ReturnType<typeof getActiveConfig>> {
  return {
    activation: {
      generation: 3,
      action: "activation",
      entry_id: "lab-default",
      entry_content_hash: "sha256:active",
      actor: "Ada",
      note: "",
      recorded_at: "2026-07-27T08:00:00Z",
    },
    entry: {
      id: "lab-default",
      content_hash: "sha256:active",
      config_ref: "entries/lab-default.json",
      source: { kind: "direct_config_profile" },
      actor: "Ada",
      note: "",
      recorded_at: "2026-07-27T08:00:00Z",
    },
    config: {
      id: "lab",
      system: {
        id: "system",
        primary_entity_id: "q0",
        topology: { entities: [] },
        instrument_registry: { instruments: [instrument().spec] },
        routing: { bindings: [] },
        domain_target: null,
        parameter_catalog: { id: "parameters", definitions: [] },
      },
      parameter_snapshot: { id: "parameters", values: [] },
    },
  };
}

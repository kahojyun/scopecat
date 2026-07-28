// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api";
import type { InstrumentSession, InstrumentState, InstrumentView } from "../../api-contract";
import { InstrumentsWorkspace } from "./InstrumentsWorkspace";
import {
  abortInstrumentSession,
  applyInstrumentState,
  closeInstrumentSession,
  collectInstrumentAcquisition,
  getActiveConfig,
  getInstruments,
  openInstrumentSession,
  publishInstrumentConnection,
  readInstrumentState,
  resolveInstrumentAttention,
} from "./instrument-api";

vi.mock("./instrument-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./instrument-api")>()),
  abortInstrumentSession: vi.fn(),
  applyInstrumentState: vi.fn(),
  closeInstrumentSession: vi.fn(),
  collectInstrumentAcquisition: vi.fn(),
  getActiveConfig: vi.fn(),
  getInstruments: vi.fn(),
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
  vi.mocked(openInstrumentSession).mockResolvedValue(session());
  vi.mocked(readInstrumentState).mockResolvedValue(instrumentState());
  vi.mocked(applyInstrumentState).mockResolvedValue({
    status: "applied",
    problems: [],
    state: instrumentState(6_000_000_000),
  });
  vi.mocked(closeInstrumentSession).mockResolvedValue();
  vi.mocked(abortInstrumentSession).mockResolvedValue();
  vi.mocked(collectInstrumentAcquisition).mockResolvedValue({
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
            interfaces: [],
          },
          availability: "active",
          owner_kind: "run",
          owner_id: "run-42",
          owner_actor: null,
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

  it("keeps driver ABI details out of the ordinary interface view", async () => {
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

    const heading = (await screen.findByText("Interfaces")).closest(".interface-heading");
    expect(heading).not.toBeNull();
    expect(within(heading as HTMLElement).queryByText("virtual.rf_source")).not.toBeInTheDocument();
    expect(within(heading as HTMLElement).queryByText("v1")).not.toBeInTheDocument();
  });

  it("connects explicitly, reads initial state, and closes on unmount", async () => {
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
    expect(screen.queryByText("session-1")).not.toBeInTheDocument();

    rendered.unmount();

    await waitFor(() => expect(closeInstrumentSession).toHaveBeenCalledWith("session-1", true));
  });

  it("allows an operator to disconnect a daemon-owned interactive session", async () => {
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [],
      items: [
        instrument({
          availability: "active",
          owner_kind: "instrument_session",
          owner_id: "session-stale",
          owner_actor: "Grace",
        }),
      ],
    });
    renderWorkspace();

    expect(await screen.findByText("Read-only while owned")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect session" }));

    await waitFor(() => expect(abortInstrumentSession).toHaveBeenCalledWith("session-stale"));
  });

  it("stages typed properties locally and sends one apply command", async () => {
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
    expect(screen.getByText("1 staged property")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));

    await waitFor(() =>
      expect(applyInstrumentState).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: "session-1" }),
        "drive-source",
        [
          {
            interfaceId: "scopecat.rf_output/v1",
            componentPath: [],
            propertyId: "frequency",
            value: { value: 6_000_000_000, unit: "Hz" },
          },
        ],
        expect.stringMatching(/^ui-apply-/),
      ),
    );
    expect(await screen.findByText("Apply receipt: Applied")).toBeVisible();
  });

  it("reuses operation ids while retrying mutations", async () => {
    vi.mocked(applyInstrumentState).mockRejectedValueOnce(new Error("Apply network failed."));
    vi.mocked(collectInstrumentAcquisition).mockRejectedValueOnce(
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
    await waitFor(() => expect(collectInstrumentAcquisition).toHaveBeenCalledTimes(2));
    expect(vi.mocked(collectInstrumentAcquisition).mock.calls[0]?.[4]).toBe(
      vi.mocked(collectInstrumentAcquisition).mock.calls[1]?.[4],
    );

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(closeInstrumentSession).toHaveBeenCalledTimes(2), {
      timeout: 2_000,
    });
    expect(vi.mocked(closeInstrumentSession).mock.calls).toEqual([["session-1"], ["session-1"]]);
  });

  it("starts a new collect operation after an applied state change", async () => {
    vi.mocked(collectInstrumentAcquisition).mockRejectedValueOnce(
      new Error("Collect request lost."),
    );
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const frequency = await screen.findByRole("spinbutton", { name: /CW frequency/ });

    fireEvent.click(screen.getByRole("button", { name: "Collect" }));
    expect(await screen.findByText("Collect request lost.")).toBeVisible();
    const staleCollectId = vi.mocked(collectInstrumentAcquisition).mock.calls[0]?.[4];

    fireEvent.change(frequency, { target: { value: "6000000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));
    expect(await screen.findByText("Apply receipt: Applied")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Collect" }));

    await waitFor(() => expect(collectInstrumentAcquisition).toHaveBeenCalledTimes(2));
    expect(vi.mocked(collectInstrumentAcquisition).mock.calls[1]?.[4]).not.toBe(staleCollectId);
  });

  it("disables collection when an acquisition result has an unresolved dynamic axis", async () => {
    const mixedAxisInstrument = instrument();
    mixedAxisInstrument.description = {
      ...mixedAxisInstrument.description!,
      interfaces: [
        {
          id: "scopecat.network_sweep/v1",
          label: "Network sweep",
          properties: [],
          operations: [],
          components: [],
          acquisitions: [
            {
              id: "sweep",
              results: [
                {
                  id: "trace",
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
      session({ descriptions: [mixedAxisInstrument.description] }),
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
    expect(collectInstrumentAcquisition).not.toHaveBeenCalled();
  });

  it("keeps the session available after close retries fail", async () => {
    vi.mocked(closeInstrumentSession)
      .mockRejectedValueOnce(new ApiError("Close request lost."))
      .mockRejectedValueOnce(new ApiError("Close request lost again."));
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("Interactive session connected");

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    expect(await screen.findByText("Close request lost again.")).toBeVisible();
    expect(screen.getByText("Interactive session connected")).toBeVisible();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
    expect(closeInstrumentSession).toHaveBeenCalledTimes(2);
    expect(vi.mocked(closeInstrumentSession).mock.calls[0]).toEqual(["session-1"]);
    expect(vi.mocked(closeInstrumentSession).mock.calls[1]).toEqual(["session-1"]);

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(closeInstrumentSession).toHaveBeenCalledTimes(3));
    expect(vi.mocked(closeInstrumentSession).mock.calls[2]).toEqual(["session-1"]);
    expect(await screen.findByRole("button", { name: "Connect" })).toBeVisible();
  });

  it("stays on the connected instrument when closing before selection fails", async () => {
    const monitor = instrument({
      spec: {
        id: "monitor",
        driver_id: "virtual.temperature",
        connection: { kind: "virtual" },
      },
      description: {
        instrument_id: "monitor",
        implementation_id: "virtual.temperature",
        implementation_version: "v1",
        label: "Fridge monitor",
        interfaces: [],
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
    expect(vi.mocked(closeInstrumentSession).mock.calls[0]).toEqual(["session-1"]);

    fireEvent.click(screen.getByTitle("Inspect instrument monitor"));

    expect(await screen.findByRole("heading", { name: "Fridge monitor", level: 2 })).toBeVisible();
    expect(vi.mocked(closeInstrumentSession).mock.calls[1]).toEqual(["session-1"]);
  });

  it("edits only endpoint fields while keeping driver and connection kind fixed", async () => {
    const active = activeConfig();
    active.config.system.instrument_registry.instruments[0]!.driver_id = "keysight.pna";
    active.config.system.instrument_registry.instruments[0]!.connection = {
      kind: "tcpip_socket",
      host: "192.0.2.20",
      port: 5025,
      timeout_seconds: 5,
      options: { termination: "lf" },
    };
    const tcpInstrument = instrument();
    tcpInstrument.spec = active.config.system.instrument_registry.instruments[0]!;
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      config_content_hash: "sha256:active",
      problems: [],
      items: [tcpInstrument],
    });
    vi.mocked(getActiveConfig).mockResolvedValue(active);
    renderWorkspace();

    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Edit connection" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("keysight.pna")).toBeVisible();
    expect(within(dialog).getByText("TCP/IP socket")).toBeVisible();
    expect(within(dialog).queryByRole("textbox", { name: "Driver id" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Host"), {
      target: { value: "192.0.2.24" },
    });
    fireEvent.change(within(dialog).getByLabelText("Timeout (seconds)"), {
      target: { value: "8" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Publish default" }));

    await waitFor(() =>
      expect(publishInstrumentConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          instrumentId: "drive-source",
          connection: {
            kind: "tcpip_socket",
            host: "192.0.2.24",
            port: 5025,
            timeout_seconds: 8,
            options: { termination: "lf" },
          },
        }),
      ),
    );
    expect(openInstrumentSession).not.toHaveBeenCalled();
  });

  it("disables connection editing for a virtual instrument", async () => {
    renderWorkspace();

    await screen.findByText("Drive source");
    const edit = screen.getByRole("button", { name: "Edit connection" });
    expect(edit).toBeDisabled();
    expect(edit).toHaveAttribute("title", "Virtual connections have no editable endpoint");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
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
      driver_id: "virtual.rf_source",
      connection: { kind: "virtual" },
    },
    description: {
      instrument_id: "drive-source",
      implementation_id: "virtual.rf_source",
      implementation_version: "0.1",
      label: "Drive source",
      description: "Virtual microwave source",
      interfaces: [
        {
          id: "scopecat.rf_output/v1",
          label: "RF output",
          properties: [
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
          operations: [],
          components: [],
          acquisitions: [
            {
              id: "sample",
              label: "Sample",
              results: [
                {
                  id: "trace",
                  label: "Trace",
                  dtype: "float64",
                  unit: "ratio",
                  axes: [{ id: "sample", kind: "sample", size: 3 }],
                },
              ],
            },
          ],
        },
      ],
    },
    availability: "available",
    owner_kind: null,
    owner_id: null,
    owner_actor: null,
    problems: [],
    ...overrides,
  };
}

function session(overrides: Partial<InstrumentSession> = {}): InstrumentSession {
  return {
    session_id: "session-1",
    actor: "local-operator",
    config_entry_id: "lab-default",
    config_content_hash: "sha256:active",
    instrument_ids: ["drive-source"],
    descriptions: [instrument().description!],
    opened_at: "2026-07-27T09:00:00Z",
    ...overrides,
  };
}

function instrumentState(frequency = 5_000_000_000): InstrumentState {
  return {
    instrument_id: "drive-source",
    properties: [
      {
        interface_id: "scopecat.rf_output/v1",
        component_path: [],
        property_id: "frequency",
        value: { value: frequency, unit: "Hz" },
      },
      {
        interface_id: "scopecat.rf_output/v1",
        component_path: [],
        property_id: "output_enabled",
        value: false,
      },
      {
        interface_id: "scopecat.rf_output/v1",
        component_path: [],
        property_id: "temperature",
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

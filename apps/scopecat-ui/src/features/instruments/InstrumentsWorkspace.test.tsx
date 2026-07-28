// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api";
import type {
  InstrumentInterface,
  InstrumentSession,
  InstrumentState,
  InstrumentView,
} from "../../api-contract";
import { InstrumentsWorkspace } from "./InstrumentsWorkspace";
import {
  abortInstrumentSession,
  applyInstrumentConfiguredDefaults,
  applyInstrumentState,
  closeInstrumentSession,
  collectInstrumentAcquisition,
  getActiveConfig,
  getInstruments,
  invokeInstrumentOperation,
  openInstrumentSession,
  publishInstrumentConnection,
  readInstrumentState,
  resolveInstrumentAttention,
} from "./instrument-api";

vi.mock("./instrument-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./instrument-api")>()),
  abortInstrumentSession: vi.fn(),
  applyInstrumentConfiguredDefaults: vi.fn(),
  applyInstrumentState: vi.fn(),
  closeInstrumentSession: vi.fn(),
  collectInstrumentAcquisition: vi.fn(),
  getActiveConfig: vi.fn(),
  getInstruments: vi.fn(),
  invokeInstrumentOperation: vi.fn(),
  openInstrumentSession: vi.fn(),
  publishInstrumentConnection: vi.fn(),
  readInstrumentState: vi.fn(),
  resolveInstrumentAttention: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getInstruments).mockResolvedValue({
    config_entry_id: "lab-default",
    problems: [],
    items: [instrument()],
  });
  vi.mocked(getActiveConfig).mockResolvedValue(activeConfig());
  vi.mocked(openInstrumentSession).mockResolvedValue(session());
  vi.mocked(readInstrumentState).mockResolvedValue(instrumentState());
  vi.mocked(applyInstrumentConfiguredDefaults).mockResolvedValue(
    configuredDefaultsReceipt("applied", instrumentState(6_000_000_000)),
  );
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
  vi.mocked(invokeInstrumentOperation).mockResolvedValue({
    status: "invoked",
    problems: [],
    state: instrumentState(7_000_000_000),
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
      problems: [],
      items: [
        instrument(),
        instrument({
          instrument_id: "vna-1",
          driver_id: "keysight.pna",
          connection: {
            kind: "tcpip_socket",
            host: "192.0.2.12",
            port: 5025,
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
      problems: [],
      items: [prefixed],
    });

    renderWorkspace();

    const heading = (await screen.findByText("Interfaces")).closest(".interface-heading");
    expect(heading).not.toBeNull();
    expect(within(heading as HTMLElement).queryByText("virtual.rf_source")).not.toBeInTheDocument();
    expect(within(heading as HTMLElement).queryByText("v1")).not.toBeInTheDocument();
  });

  it("uses session-open state without another read, refreshes explicitly, and closes", async () => {
    vi.mocked(readInstrumentState).mockResolvedValueOnce(instrumentState(6_000_000_000));
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
    expect(readInstrumentState).not.toHaveBeenCalled();
    expect(await screen.findByDisplayValue("5000000000")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Refresh state" }));
    await waitFor(() =>
      expect(readInstrumentState).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: "session-1" }),
        "drive-source",
      ),
    );
    expect(await screen.findByDisplayValue("6000000000")).toBeVisible();
    expect(screen.queryByText("session-1")).not.toBeInTheDocument();

    rendered.unmount();

    await waitFor(() => expect(closeInstrumentSession).toHaveBeenCalledWith("session-1", true));
  });

  it("shows and applies only session-authoritative configured defaults", async () => {
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({ configured_default_instrument_ids: ["drive-source"] }),
    );
    renderWorkspace();

    await screen.findByText("Drive source");
    expect(
      screen.queryByRole("button", { name: "Apply configured defaults" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const applyDefaults = await screen.findByRole("button", {
      name: "Apply configured defaults",
    });
    fireEvent.click(applyDefaults);

    await waitFor(() =>
      expect(applyInstrumentConfiguredDefaults).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: "session-1" }),
        "drive-source",
        expect.stringMatching(/^ui-configured-defaults-/),
      ),
    );
    expect(await screen.findByText("Configured defaults applied.")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: /CW frequency/ })).toHaveValue(6_000_000_000);
  });

  it("clears stale operation results after applying configured defaults", async () => {
    const withOperations = instrumentWithOperations();
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [withOperations],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({
        configured_default_instrument_ids: ["drive-source"],
        descriptions: [withOperations.description!],
      }),
    );
    renderWorkspace();

    await screen.findByText("Reset fault");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Invoke Reset fault" }));
    expect(await screen.findByText("Invoke receipt: Invoked")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Apply configured defaults" }));
    expect(await screen.findByText("Configured defaults applied.")).toBeVisible();
    expect(screen.queryByText("Invoke receipt: Invoked")).not.toBeInTheDocument();
  });

  it("hides configured defaults when the pinned session has none", async () => {
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("Interactive session connected");

    expect(
      screen.queryByRole("button", { name: "Apply configured defaults" }),
    ).not.toBeInTheDocument();
  });

  it("disables configured defaults for staged values and pending interactions", async () => {
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({ configured_default_instrument_ids: ["drive-source"] }),
    );
    let finishCollect: (() => void) | undefined;
    vi.mocked(collectInstrumentAcquisition).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishCollect = () =>
            resolve({
              status: "collected",
              problems: [],
              readback: { values: {} },
            });
        }),
    );
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const frequency = await screen.findByRole("spinbutton", { name: /CW frequency/ });
    const applyDefaults = screen.getByRole("button", {
      name: "Apply configured defaults",
    });

    fireEvent.change(frequency, { target: { value: "6000000000" } });
    expect(applyDefaults).toBeDisabled();
    expect(applyDefaults).toHaveAttribute("title", "Apply or reset staged properties first");

    fireEvent.click(screen.getByRole("button", { name: "Collect" }));
    await waitFor(() => expect(collectInstrumentAcquisition).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Apply staged" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refresh state" })).toBeDisabled();
    expect(applyDefaults).toBeDisabled();
    expect(applyDefaults).toHaveAttribute("title", "Apply or reset staged properties first");
    finishCollect?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply staged" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(applyDefaults).toBeEnabled();
  });

  it("blocks other device interactions while configured defaults are pending", async () => {
    const withOperations = instrumentWithOperations();
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [withOperations],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({
        configured_default_instrument_ids: ["drive-source"],
        descriptions: [withOperations.description!],
      }),
    );
    let finishDefaults:
      | ((receipt: Awaited<ReturnType<typeof applyInstrumentConfiguredDefaults>>) => void)
      | undefined;
    vi.mocked(applyInstrumentConfiguredDefaults).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishDefaults = resolve;
        }),
    );
    renderWorkspace();
    await screen.findByText("Reset fault");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const applyDefaults = await screen.findByRole("button", {
      name: "Apply configured defaults",
    });
    await waitFor(() => expect(applyDefaults).toBeEnabled());

    fireEvent.click(applyDefaults);
    await waitFor(() => expect(applyInstrumentConfiguredDefaults).toHaveBeenCalledOnce());

    expect(screen.getByRole("button", { name: "Refresh state" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Collect" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Invoke Reset fault" })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: /CW frequency/ })).toBeDisabled();
    expect(applyDefaults).toHaveAttribute(
      "title",
      "Wait for the current instrument interaction to finish",
    );

    finishDefaults?.(configuredDefaultsReceipt("unchanged", instrumentState()));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Refresh state" })).toBeEnabled(),
    );
  });

  it("shows configured-default rejection problems without losing the session", async () => {
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({ configured_default_instrument_ids: ["drive-source"] }),
    );
    vi.mocked(applyInstrumentConfiguredDefaults).mockResolvedValueOnce({
      session_id: "session-1",
      operation_id: "defaults-rejected",
      instrument_id: "drive-source",
      config_entry_id: "lab-default",
      status: "rejected",
      problems: [
        {
          code: "driver_rejected",
          message: "Driver refused the configured state.",
          phase: "execution",
          related_locations: [],
        },
      ],
      state: null,
    });
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply configured defaults" }));

    expect(
      await screen.findByText("Configured defaults rejected: Driver refused the configured state."),
    ).toBeVisible();
    expect(screen.getByText("Interactive session connected")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });

  it("reuses the configured-default operation id while retrying a network failure", async () => {
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({ configured_default_instrument_ids: ["drive-source"] }),
    );
    vi.mocked(applyInstrumentConfiguredDefaults)
      .mockRejectedValueOnce(new ApiError("Defaults request lost."))
      .mockResolvedValueOnce(configuredDefaultsReceipt("unchanged", instrumentState()));
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const applyDefaults = await screen.findByRole("button", {
      name: "Apply configured defaults",
    });

    fireEvent.click(applyDefaults);

    await waitFor(() => expect(applyInstrumentConfiguredDefaults).toHaveBeenCalledTimes(2));
    expect(vi.mocked(applyInstrumentConfiguredDefaults).mock.calls[0]?.[2]).toBe(
      vi.mocked(applyInstrumentConfiguredDefaults).mock.calls[1]?.[2],
    );
    expect(await screen.findByText("State already matched the configured defaults.")).toBeVisible();
  });

  it("refreshes ownership after a configured-default conflict", async () => {
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({ configured_default_instrument_ids: ["drive-source"] }),
    );
    vi.mocked(applyInstrumentConfiguredDefaults).mockRejectedValueOnce(
      new ApiError("The session is no longer active.", 409),
    );
    renderWorkspace();
    await screen.findByText("Drive source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply configured defaults" }));

    expect(
      await screen.findByText("The interactive session ended while applying configured defaults."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect" })).toBeVisible();
  });

  it("allows an operator to disconnect a daemon-owned interactive session", async () => {
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
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
    expect(screen.queryByText("session-stale")).not.toBeInTheDocument();
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

  it("renders a discriminator first with common and active-case properties", async () => {
    const variantInstrument = instrumentWithDiscriminatedState();
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [variantInstrument],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({
        descriptions: [variantInstrument.description!],
        observed_state: [discriminatedInstrumentState("voltage")],
      }),
    );
    renderWorkspace();

    await screen.findByText("DC source");
    expect(screen.getByRole("combobox", { name: /Source mode/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /DC output/ })).toBeDisabled();
    expect(screen.queryByRole("spinbutton", { name: /Voltage range/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: /Current range/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByRole("spinbutton", { name: /Voltage range/ })).toHaveValue(5);
    expect(screen.queryByRole("spinbutton", { name: /Current range/ })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /Source mode/ })).toHaveValue("voltage");

    const card = screen
      .getByRole("heading", { name: "DC source", level: 4 })
      .closest(".interface-card");
    expect(card).not.toBeNull();
    expect(
      Array.from(card!.querySelectorAll(".property-label strong")).map(
        (element) => element.textContent,
      ),
    ).toEqual(["Source mode", "DC output", "Voltage range"]);
  });

  it("drops inactive-case drafts while preserving common and other endpoint drafts", async () => {
    const variantInstrument = instrumentWithDiscriminatedState();
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [variantInstrument],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({
        descriptions: [variantInstrument.description!],
        observed_state: [discriminatedInstrumentState("voltage")],
      }),
    );
    vi.mocked(applyInstrumentState).mockResolvedValueOnce(
      discriminatedApplyReceipt("current", 6_000_000_000),
    );
    renderWorkspace();

    await screen.findByText("DC source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.change(await screen.findByRole("spinbutton", { name: /Voltage range/ }), {
      target: { value: "8" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /DC output/ }));
    fireEvent.change(screen.getByRole("spinbutton", { name: /CW frequency/ }), {
      target: { value: "6000000000" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: /RF voltage limit/ }), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /Source mode/ }), {
      target: { value: "current" },
    });

    expect(screen.queryByRole("spinbutton", { name: /Voltage range/ })).not.toBeInTheDocument();
    const currentRange = screen.getByRole("spinbutton", { name: /Current range/ });
    expect(currentRange).toHaveValue(null);
    expect(screen.getByText("4 staged properties")).toBeVisible();
    expect(applyInstrumentState).not.toHaveBeenCalled();

    fireEvent.change(currentRange, { target: { value: "0.1" } });
    expect(screen.getByText("5 staged properties")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));

    await waitFor(() => expect(applyInstrumentState).toHaveBeenCalledOnce());
    const assignments = vi.mocked(applyInstrumentState).mock.calls[0]![2];
    expect(assignments).toHaveLength(5);
    expect(assignments).toEqual(
      expect.arrayContaining([
        {
          interfaceId: "scopecat.dc_source/v2",
          componentPath: [],
          propertyId: "source_mode",
          value: "current",
        },
        {
          interfaceId: "scopecat.dc_source/v2",
          componentPath: [],
          propertyId: "output_enabled",
          value: true,
        },
        {
          interfaceId: "scopecat.dc_source/v2",
          componentPath: [],
          propertyId: "current_range",
          value: { value: 0.1, unit: "A" },
        },
        {
          interfaceId: "scopecat.rf_output/v1",
          componentPath: [],
          propertyId: "frequency",
          value: { value: 6_000_000_000, unit: "Hz" },
        },
        {
          interfaceId: "scopecat.rf_output/v1",
          componentPath: [],
          propertyId: "voltage_range",
          value: { value: 2, unit: "V" },
        },
      ]),
    );
    expect(assignments).not.toContainEqual(
      expect.objectContaining({
        interfaceId: "scopecat.dc_source/v2",
        propertyId: "voltage_range",
      }),
    );
    expect(await screen.findByText("Apply receipt: Applied")).toBeVisible();
    expect(screen.getByRole("combobox", { name: /Source mode/ })).toHaveValue("current");
    expect(screen.getByRole("spinbutton", { name: /Current range/ })).toHaveValue(0.1);
    expect(screen.queryByRole("spinbutton", { name: /Voltage range/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/staged propert/)).not.toBeInTheDocument();
  });

  it("does not revive case drafts when the discriminator draft is reset", async () => {
    const variantInstrument = instrumentWithDiscriminatedState();
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [variantInstrument],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({
        descriptions: [variantInstrument.description!],
        observed_state: [discriminatedInstrumentState("voltage")],
      }),
    );
    renderWorkspace();

    await screen.findByText("DC source");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.change(await screen.findByRole("spinbutton", { name: /Voltage range/ }), {
      target: { value: "8" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /Source mode/ }), {
      target: { value: "current" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Current range/ }), {
      target: { value: "0.1" },
    });

    const discriminator = screen.getByRole("combobox", { name: /Source mode/ });
    const discriminatorEditor = discriminator.closest(".interface-property");
    expect(discriminatorEditor).not.toBeNull();
    fireEvent.click(
      within(discriminatorEditor as HTMLElement).getByRole("button", {
        name: "Reset staged value",
      }),
    );

    expect(screen.getByRole("spinbutton", { name: /Voltage range/ })).toHaveValue(5);
    expect(screen.queryByRole("spinbutton", { name: /Current range/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/staged propert/)).not.toBeInTheDocument();
    expect(applyInstrumentState).not.toHaveBeenCalled();
  });

  it("fills typed operation arguments locally and invokes once outside staged apply", async () => {
    const withOperations = instrumentWithOperations();
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [withOperations],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({ descriptions: [withOperations.description!] }),
    );
    renderWorkspace();

    await screen.findByText("Configure trigger");
    expect(screen.getByRole("button", { name: "Invoke Configure trigger" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Invoke Upload waveform" })).toBeDisabled();
    expect(
      screen.getByText(
        "Payload arguments require an encoded command payload and are not supported in the GUI.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("payload_id")).not.toBeInTheDocument();
    expect(screen.queryByText("waveform/v1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.change(await screen.findByRole("combobox", { name: /Enable correction/ }), {
      target: { value: "true" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Average count/ }), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Threshold/ }), {
      target: { value: "0.75" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /Profile name/ }), {
      target: { value: "fast" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Settling time/ }), {
      target: { value: "0.25" },
    });

    expect(screen.queryByText(/staged propert/)).not.toBeInTheDocument();
    expect(applyInstrumentState).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Invoke Configure trigger" }));

    await waitFor(() => expect(invokeInstrumentOperation).toHaveBeenCalledOnce());
    expect(invokeInstrumentOperation).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: "session-1" }),
      "drive-source",
      expect.objectContaining({
        interfaceId: "scopecat.rf_output/v1",
        componentPath: [],
        operation: expect.objectContaining({ id: "configure_trigger" }),
      }),
      [
        { id: "enabled", value: true },
        { id: "averages", value: 3 },
        { id: "threshold", value: 0.75 },
        { id: "profile", value: "fast" },
        { id: "settling", value: { value: 0.25, unit: "s" } },
      ],
      expect.stringMatching(/^ui-invoke-/),
    );
    expect(await screen.findByText("Invoke receipt: Invoked")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: /CW frequency/ })).toHaveValue(7_000_000_000);
    const commandId = vi.mocked(invokeInstrumentOperation).mock.calls[0]?.[4];
    expect(commandId).toBeDefined();
    expect(screen.queryByText(commandId!)).not.toBeInTheDocument();
    expect(screen.queryByText("session-1")).not.toBeInTheDocument();
    expect(applyInstrumentState).not.toHaveBeenCalled();
  });

  it("uses the existing quarantine semantics for an unknown invoke receipt", async () => {
    const withOperations = instrumentWithOperations();
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [withOperations],
    });
    vi.mocked(openInstrumentSession).mockResolvedValue(
      session({ descriptions: [withOperations.description!] }),
    );
    vi.mocked(invokeInstrumentOperation).mockResolvedValueOnce({
      status: "unknown",
      problems: [
        {
          code: "instrument_invoke_unknown",
          message: "The hardware may have accepted the operation.",
          phase: "execution",
          related_locations: [],
        },
      ],
      state: null,
    });
    renderWorkspace();

    await screen.findByText("Reset fault");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Invoke Reset fault" }));

    expect(
      await screen.findByText(
        "The operation result is unknown. The daemon quarantined this session for operator review.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("session-1")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Connect" })).toBeVisible();
  });

  it("reuses command ids while retrying mutations", async () => {
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
    const staleCollectCommandId = vi.mocked(collectInstrumentAcquisition).mock.calls[0]?.[4];

    fireEvent.change(frequency, { target: { value: "6000000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply staged" }));
    expect(await screen.findByText("Apply receipt: Applied")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Collect" }));

    await waitFor(() => expect(collectInstrumentAcquisition).toHaveBeenCalledTimes(2));
    expect(vi.mocked(collectInstrumentAcquisition).mock.calls[1]?.[4]).not.toBe(
      staleCollectCommandId,
    );
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
              kind: "fixed",
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
      instrument_id: "monitor",
      driver_id: "virtual.temperature",
      connection: { kind: "virtual" },
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

  it("loads the active config only after connection editing is requested", async () => {
    const active = activeConfig();
    active.config.system.instrument_registry.instruments[0]!.driver_id = "keysight.pna";
    active.config.system.instrument_registry.instruments[0]!.connection = {
      kind: "tcpip_socket",
      host: "192.0.2.20",
      port: 5025,
      timeout_seconds: 5,
    };
    const tcpInstrument = instrument({
      driver_id: "keysight.pna",
      connection: {
        kind: "tcpip_socket",
        host: "192.0.2.20",
        port: 5025,
      },
    });
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
      problems: [],
      items: [tcpInstrument],
    });
    let resolveConfig: ((value: Awaited<ReturnType<typeof getActiveConfig>>) => void) | undefined;
    vi.mocked(getActiveConfig).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveConfig = resolve;
        }),
    );
    renderWorkspace();

    await screen.findByText("Drive source");
    expect(getActiveConfig).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Edit connection" }));

    await waitFor(() => expect(getActiveConfig).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Loading configuration" })).toBeDisabled();
    if (!resolveConfig) throw new Error("Expected the active config request to be pending.");
    resolveConfig(active);
    expect(await screen.findByRole("dialog")).toBeVisible();
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
    tcpInstrument.driver_id = "keysight.pna";
    tcpInstrument.connection = {
      kind: "tcpip_socket",
      host: "192.0.2.20",
      port: 5025,
    };
    vi.mocked(getInstruments).mockResolvedValue({
      config_entry_id: "lab-default",
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
    expect(screen.queryByText("session-stale")).not.toBeInTheDocument();
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
    instrument_id: "drive-source",
    driver_id: "virtual.rf_source",
    connection: { kind: "virtual" },
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
              kind: "fixed",
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

function instrumentWithDiscriminatedState(): InstrumentView {
  const view = instrument();
  const description = view.description!;
  const originalRfOutput = description.interfaces![0]!;
  const rfOutput: InstrumentInterface = {
    ...originalRfOutput,
    properties: [
      ...(originalRfOutput.properties ?? []),
      {
        id: "voltage_range",
        label: "RF voltage limit",
        access: "read_write",
        value_type: { type: "quantity", finite: true, unit: "V" },
      },
    ],
  };
  const dcSource: InstrumentInterface = {
    id: "scopecat.dc_source/v2",
    label: "DC source",
    properties: [
      {
        id: "source_mode",
        label: "Source mode",
        access: "read_write",
        value_type: { type: "string", choices: ["voltage", "current"] },
      },
      {
        id: "output_enabled",
        label: "DC output",
        access: "read_write",
        value_type: { type: "bool" },
      },
      {
        id: "voltage_range",
        label: "Voltage range",
        access: "read_write",
        value_type: { type: "quantity", finite: true, unit: "V" },
      },
      {
        id: "current_range",
        label: "Current range",
        access: "read_write",
        value_type: { type: "quantity", finite: true, unit: "A" },
      },
    ],
    state: {
      discriminator_property_id: "source_mode",
      common_property_ids: ["output_enabled"],
      cases: [
        { value: "voltage", property_ids: ["voltage_range"] },
        { value: "current", property_ids: ["current_range"] },
      ],
    },
    operations: [],
    components: [],
    acquisitions: [],
  };
  view.description = {
    ...description,
    interfaces: [dcSource, rfOutput],
  };
  return view;
}

function instrumentWithOperations(): InstrumentView {
  const view = instrument();
  const description = view.description!;
  const instrumentInterface = description.interfaces![0]!;
  view.description = {
    ...description,
    interfaces: [
      {
        ...instrumentInterface,
        operations: [
          {
            id: "configure_trigger",
            label: "Configure trigger",
            description: "Configure and arm the trigger in one hardware operation.",
            arguments: [
              {
                id: "enabled",
                label: "Enable correction",
                value_type: { type: "bool" },
              },
              {
                id: "averages",
                label: "Average count",
                value_type: { type: "int", minimum: 1, maximum: 16 },
              },
              {
                id: "threshold",
                label: "Threshold",
                value_type: { type: "float", finite: true, minimum: 0, maximum: 1 },
              },
              {
                id: "profile",
                label: "Profile name",
                value_type: { type: "string" },
              },
              {
                id: "settling",
                label: "Settling time",
                value_type: { type: "quantity", finite: true, unit: "s", minimum: 0 },
              },
            ],
          },
          {
            id: "reset_fault",
            label: "Reset fault",
            arguments: [],
          },
          {
            id: "upload_waveform",
            label: "Upload waveform",
            arguments: [
              {
                id: "waveform",
                label: "Waveform file",
                value_type: { type: "payload", schema_id: "waveform/v1" },
              },
            ],
          },
        ],
      },
    ],
  };
  return view;
}

function session(overrides: Partial<InstrumentSession> = {}): InstrumentSession {
  return {
    session_id: "session-1",
    actor: "local-operator",
    config_entry_id: "lab-default",
    config_content_hash: "sha256:active",
    instrument_ids: ["drive-source"],
    configured_default_instrument_ids: [],
    descriptions: [instrument().description!],
    observed_state: [instrumentState()],
    opened_at: "2026-07-27T09:00:00Z",
    ...overrides,
  };
}

function configuredDefaultsReceipt(
  status: "applied" | "unchanged",
  state: InstrumentState,
): Awaited<ReturnType<typeof applyInstrumentConfiguredDefaults>> {
  return {
    session_id: "session-1",
    operation_id: "defaults-1",
    instrument_id: "drive-source",
    config_entry_id: "lab-default",
    status,
    problems: [],
    state,
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

function discriminatedInstrumentState(
  mode: "current" | "voltage",
  frequency = 5_000_000_000,
): InstrumentState {
  return {
    instrument_id: "drive-source",
    properties: [
      {
        interface_id: "scopecat.dc_source/v2",
        component_path: [],
        property_id: "source_mode",
        value: mode,
      },
      {
        interface_id: "scopecat.dc_source/v2",
        component_path: [],
        property_id: "output_enabled",
        value: mode === "current",
      },
      {
        interface_id: "scopecat.dc_source/v2",
        component_path: [],
        property_id: mode === "voltage" ? "voltage_range" : "current_range",
        value: { value: mode === "voltage" ? 5 : 0.1, unit: mode === "voltage" ? "V" : "A" },
      },
      ...(instrumentState(frequency).properties ?? []),
    ],
  };
}

function discriminatedApplyReceipt(
  mode: "current" | "voltage",
  frequency: number,
): Awaited<ReturnType<typeof applyInstrumentState>> {
  return {
    status: "applied",
    problems: [],
    state: discriminatedInstrumentState(mode, frequency),
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
        instrument_registry: { instruments: [configuredInstrument()] },
        routing: { bindings: [] },
        domain_target: null,
        parameter_catalog: { id: "parameters", definitions: [] },
      },
      parameter_snapshot: { id: "parameters", values: [] },
    },
  };
}

function configuredInstrument() {
  return {
    id: "drive-source",
    exclusivity_key: "drive-source",
    driver_id: "virtual.rf_source",
    connection: { kind: "virtual" as const },
    default_state: [],
    run_start: "preserve" as const,
  };
}

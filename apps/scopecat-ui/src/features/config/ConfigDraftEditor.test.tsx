// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfigDraftEditor, type ConfigDraftSeed } from "./ConfigDraftEditor";
import type {
  ConfigDraftDefaultReceipt,
  ConfigDraftPreview,
  ConfigDraftRegistrationReceipt,
  ConfigProfileSnapshot,
} from "../../api-contract";

const apiMocks = vi.hoisted(() => ({
  previewConfigDraft: vi.fn(),
  registerConfigDraft: vi.fn(),
  setConfigDraftDefault: vi.fn(),
}));

vi.mock("./config-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./config-api")>()),
  previewConfigDraft: apiMocks.previewConfigDraft,
  registerConfigDraft: apiMocks.registerConfigDraft,
  setConfigDraftDefault: apiMocks.setConfigDraftDefault,
}));

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;

afterEach(cleanup);

beforeEach(() => {
  apiMocks.previewConfigDraft.mockReset();
  apiMocks.registerConfigDraft.mockReset();
  apiMocks.setConfigDraftDefault.mockReset();
});

describe("ConfigDraftEditor", () => {
  it("sets a scalar edit as the default without requiring an explicit preview", async () => {
    const seed = draftSeed();
    const candidate = snapshot(5.2, 6.5);
    const preview = validPreview(seed, candidate);
    const receipt = defaultReceipt();
    apiMocks.previewConfigDraft.mockResolvedValue(preview);
    apiMocks.setConfigDraftDefault.mockResolvedValue(receipt);
    const registered = vi.fn();

    renderEditor(seed, registered);

    expect(screen.getByRole("button", { name: "Set as default" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("drive.frequency value"), {
      target: { value: "5.2" },
    });
    fireEvent.change(screen.getByLabelText("Audit note"), {
      target: { value: "fresh calibration" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set as default" }));

    await waitFor(() => expect(apiMocks.previewConfigDraft).toHaveBeenCalled());
    expect(apiMocks.previewConfigDraft.mock.calls[0]?.[0]).toEqual({
      base_entry_id: "config-a",
      base_content_hash: HASH_A,
      base_generation: 3,
      candidate_id: "profile-edit",
      updates: [
        {
          kind: "replace_parameter",
          value: {
            id: "drive.frequency",
            shape: "scalar",
            value: { value: 5.2, unit: "GHz" },
          },
        },
      ],
    });
    await waitFor(() => expect(apiMocks.setConfigDraftDefault).toHaveBeenCalled());
    expect(apiMocks.setConfigDraftDefault.mock.calls[0]?.[0]).toEqual({
      registration: {
        draft: expect.objectContaining({
          base_entry_id: "config-a",
          updates: expect.any(Array),
        }),
        expected_result_content_hash: HASH_B,
        entry_id: "profile-edit-bbbbbbbbbbbb",
        registered_by: "Ada",
        note: "fresh calibration",
      },
      operator: "Ada",
      activation_note: "fresh calibration",
    });
    expect(screen.getByText("Candidate is valid")).toBeInTheDocument();
    const comparison = screen.getByLabelText("Default to selected value");
    expect(within(comparison).getByText("5 GHz")).toBeInTheDocument();
    expect(within(comparison).getByText("5.2 GHz")).toBeInTheDocument();
    await waitFor(() => expect(registered).toHaveBeenCalledWith(receipt));
  });

  it("keeps register-only with a custom id in Advanced", async () => {
    const seed = draftSeed();
    const receipt = registrationReceipt();
    apiMocks.previewConfigDraft.mockResolvedValue(validPreview(seed, snapshot(5.2, 6.5)));
    apiMocks.registerConfigDraft.mockResolvedValue(receipt);

    renderEditor(seed);
    fireEvent.change(screen.getByLabelText("drive.frequency value"), {
      target: { value: "5.2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview changes" }));
    await screen.findByText("Candidate is valid");
    fireEvent.click(screen.getByText("Advanced"));
    fireEvent.change(screen.getByLabelText("Saved version id"), {
      target: { value: "calibration-candidate" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register only" }));

    await waitFor(() => expect(apiMocks.registerConfigDraft).toHaveBeenCalled());
    expect(apiMocks.registerConfigDraft.mock.calls[0]?.[0]).toEqual({
      draft: expect.objectContaining({ candidate_id: "profile-edit" }),
      expected_result_content_hash: HASH_B,
      entry_id: "calibration-candidate",
      registered_by: "Ada",
      note: "",
    });
    expect(apiMocks.setConfigDraftDefault).not.toHaveBeenCalled();
  });

  it("turns keyed table cell changes into row updates", async () => {
    const seed = draftSeed();
    apiMocks.previewConfigDraft.mockResolvedValue(validPreview(seed, snapshot(5, 6.6)));

    renderEditor(seed);
    fireEvent.click(screen.getByRole("button", { name: /^calibrationtable$/i }));

    expect(screen.getByLabelText("calibration row 1 entity")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("calibration row 1 frequency"), {
      target: { value: "6.6" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview changes" }));

    await waitFor(() => expect(apiMocks.previewConfigDraft).toHaveBeenCalled());
    expect(apiMocks.previewConfigDraft.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        updates: [
          {
            kind: "update_parameter_rows",
            parameter_id: "calibration",
            key: {
              entity: {
                id: "q0",
                kind: "logical_qubit",
                metadata: {},
              },
            },
            values: { frequency: 6.6 },
          },
        ],
      }),
    );
  });

  it("keeps the primary key editable on newly inserted rows", () => {
    const seed = draftSeed();

    renderEditor(seed);
    fireEvent.click(screen.getByRole("button", { name: /^calibrationtable$/i }));
    fireEvent.click(screen.getByRole("button", { name: "Add row" }));

    expect(screen.getByLabelText("calibration row 1 entity")).toBeDisabled();
    expect(screen.getByLabelText("calibration row 2 entity")).toBeEnabled();
  });

  it("invalidates a preview immediately when a numeric field is blank", async () => {
    const seed = draftSeed();
    apiMocks.previewConfigDraft.mockResolvedValue(validPreview(seed, snapshot(5.2, 6.5)));

    renderEditor(seed);
    const valueInput = screen.getByLabelText("drive.frequency value");
    fireEvent.change(valueInput, { target: { value: "5.2" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview changes" }));
    await screen.findByText("Candidate is valid");
    expect(screen.getByRole("button", { name: "Set as default" })).toBeEnabled();

    fireEvent.change(valueInput, { target: { value: "" } });

    expect(valueInput).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText("Candidate is valid")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set as default" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /^drive\.frequencyscalar/i }));
    expect(screen.getByRole("button", { name: "Preview changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set as default" })).toBeDisabled();
    expect(apiMocks.previewConfigDraft).toHaveBeenCalledTimes(1);
  });

  it("disables preview and saving when the default base becomes stale", () => {
    const seed = draftSeed();

    renderEditor(seed, undefined, {
      generation: 4,
      active_entry_id: "config-b",
      active_entry_content_hash: HASH_B,
    });

    expect(screen.getByText(/default configuration changed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set as default" })).toBeDisabled();
  });
});

function renderEditor(seed: ConfigDraftSeed, onRegistered = vi.fn(), currentActive = seed.active) {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigDraftEditor
        seed={seed}
        currentActive={currentActive}
        operator="Ada"
        onCancel={vi.fn()}
        onRegistered={onRegistered}
      />
    </QueryClientProvider>,
  );
}

function draftSeed(): ConfigDraftSeed {
  return {
    entry: {
      id: "config-a",
      content_hash: HASH_A,
      config_ref: "entries/config-a.json",
      registered_by: "Ada",
      registered_at: "2026-07-24T08:00:00Z",
      source: { kind: "direct_config_profile" },
      note: "",
    },
    active: {
      generation: 3,
      active_entry_id: "config-a",
      active_entry_content_hash: HASH_A,
    },
    config: snapshot(5, 6.5),
  };
}

function validPreview(
  seed: ConfigDraftSeed,
  config: ReturnType<typeof snapshot>,
): ConfigDraftPreview {
  const before = seed.config.parameter_snapshot.values?.[0];
  const after = config.parameter_snapshot.values?.[0];
  if (!before || !after) throw new Error("missing scalar fixture");
  return {
    valid: true,
    base_entry: seed.entry,
    base_generation: seed.active.generation,
    base_content_hash: seed.active.active_entry_content_hash,
    config,
    result_content_hash: HASH_B,
    deltas: [
      {
        parameter_id: before.id,
        before,
        after,
      },
    ],
    problems: [],
  };
}

function registrationReceipt(): ConfigDraftRegistrationReceipt {
  return {
    entry: {
      id: "config-a-edit",
      content_hash: HASH_B,
      config_ref: "entries/config-a-edit.json",
      registered_by: "Ada",
      registered_at: "2026-07-24T08:10:00Z",
      source: {
        kind: "manual_parameter_updates",
        base_entry_id: "config-a",
        base_config_content_hash: HASH_A,
        base_registry_generation: 3,
      },
      note: "",
    },
    result_content_hash: HASH_B,
    deltas: [],
  };
}

function defaultReceipt(): ConfigDraftDefaultReceipt {
  const registered = registrationReceipt();
  const entryId = "profile-edit-bbbbbbbbbbbb";
  return {
    ...registered,
    entry: { ...registered.entry, id: entryId },
    active_state: {
      generation: 4,
      active_entry_id: entryId,
      active_entry_content_hash: HASH_B,
      updated_at: "2026-07-24T08:10:00Z",
    },
    activation: {
      id: "activation-4",
      generation: 4,
      action: "activation",
      entry_id: entryId,
      entry_content_hash: HASH_B,
      previous_entry_id: "config-a",
      operator: "Ada",
      note: "fresh calibration",
      recorded_at: "2026-07-24T08:10:00Z",
    },
  };
}

function snapshot(driveFrequency: number, readoutFrequency: number): ConfigProfileSnapshot {
  return {
    id: "profile",
    system: {
      id: "system",
      primary_entity_id: "q0",
      topology: {
        entities: [
          { id: "q0", kind: "logical_qubit", metadata: {} },
          { id: "q1", kind: "logical_qubit", metadata: {} },
        ],
      },
      instrument_registry: { instruments: [] },
      routing: { bindings: [] },
      domain_target: null,
      parameter_catalog: {
        id: "calibration",
        definitions: [
          {
            id: "drive.frequency",
            value_type: {
              shape: "scalar",
              atom: { type: "quantity", unit: "GHz" },
            },
            description: "Drive frequency",
          },
          {
            id: "calibration",
            value_type: {
              shape: "table",
              columns: [
                {
                  id: "entity",
                  value_type: {
                    type: "entity",
                    entity_kind: "logical_qubit",
                  },
                },
                {
                  id: "frequency",
                  value_type: { type: "float", minimum: 4, maximum: 8 },
                },
              ],
              primary_key: ["entity"],
            },
            description: "Qubit calibration",
          },
        ],
      },
    },
    parameter_snapshot: {
      id: "parameters",
      values: [
        {
          id: "drive.frequency",
          shape: "scalar",
          value: { value: driveFrequency, unit: "GHz" },
        },
        {
          id: "calibration",
          shape: "table",
          rows: [
            {
              entity: {
                id: "q0",
                kind: "logical_qubit",
                metadata: {},
              },
              frequency: readoutFrequency,
            },
          ],
        },
      ],
    },
  };
}

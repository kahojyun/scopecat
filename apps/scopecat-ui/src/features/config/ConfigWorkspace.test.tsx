// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getRunAnalyses } from "../../api";
import {
  activateConfigEntry,
  getConfigRegistry,
  getConfigRegistryEntry,
  rollbackConfig,
} from "./config-api";
import { ConfigWorkspace } from "./ConfigWorkspace";
import type { ConfigRegistryEntry } from "./config-types";
import { getRunParameterProposals } from "../runs/proposal-api";

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  getRunAnalyses: vi.fn(),
}));

vi.mock("./config-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./config-api")>()),
  activateConfigEntry: vi.fn(),
  getConfigRegistry: vi.fn(),
  getConfigRegistryEntry: vi.fn(),
  rollbackConfig: vi.fn(),
}));

vi.mock("../runs/proposal-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../runs/proposal-api")>()),
  getRunParameterProposals: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getRunParameterProposals).mockResolvedValue({
    runId: "run-calibration",
    items: [],
  });
  vi.mocked(getRunAnalyses).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("ConfigWorkspace", () => {
  it("presents saved versions as defaults and undo without generation ceremony", async () => {
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active: {
        generation: 2,
        entryId: "baseline",
        contentHash: "sha256:baseline",
      },
      entries: [
        configEntry("baseline", "sha256:baseline"),
        configEntry("calibrated", "sha256:calibrated"),
      ],
      history: [
        activation(2, "baseline", "sha256:baseline", "calibrated"),
        activation(1, "calibrated", "sha256:calibrated"),
      ],
    });
    vi.mocked(getConfigRegistryEntry).mockImplementation(async (entryId) => {
      const contentHash = `sha256:${entryId}`;
      return {
        entry: configEntry(entryId, contentHash),
        config: emptyConfig(entryId),
        summary: {
          id: entryId,
          primaryEntityId: "q0",
          parameterCount: 0,
          instrumentCount: 0,
          connectionCount: 0,
        },
      };
    });
    vi.mocked(activateConfigEntry).mockResolvedValue();
    vi.mocked(rollbackConfig).mockResolvedValue();

    renderWorkspace();

    expect(
      await screen.findByRole("heading", { name: "Default configuration" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Saved versions").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled();
    expect(screen.queryByText("Runtime-derived default")).not.toBeInTheDocument();
    expect(await screen.findByText("Direct configuration profile")).toBeInTheDocument();
    expect(screen.getByText("Saved from one complete config snapshot.")).toBeInTheDocument();
    expect(screen.queryByText(/application-provided/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /calibrated.*direct profile/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Set as default" }));
    const activateDialog = await screen.findByRole("alertdialog");
    expect(activateDialog).toHaveTextContent("Set calibrated as the default configuration?");
    fireEvent.click(within(activateDialog).getByRole("button", { name: "Set as default" }));

    await waitFor(() =>
      expect(activateConfigEntry).toHaveBeenCalledWith("calibrated", {
        operator: "local-operator",
        note: "",
        expectedGeneration: 2,
      }),
    );

    const undo = screen.getByRole("button", { name: "Undo" });
    await waitFor(() => expect(undo).toBeEnabled());
    fireEvent.click(undo);
    const rollbackDialog = await screen.findByRole("alertdialog");
    expect(rollbackDialog).toHaveTextContent("Restore calibrated as the default configuration?");
    fireEvent.click(within(rollbackDialog).getByRole("button", { name: "Restore default" }));
    await waitFor(() => expect(rollbackConfig).toHaveBeenCalled());
  });

  it.each(["manual_parameter_updates", "candidate_config"] as const)(
    "marks a %s default as runtime-derived without claiming source drift",
    async (sourceKind) => {
      const entry = runtimeDerivedEntry(sourceKind);
      vi.mocked(getConfigRegistry).mockResolvedValue({
        active: {
          generation: 3,
          entryId: entry.id,
          contentHash: entry.contentHash,
        },
        entries: [entry],
        history: [activation(3, entry.id, entry.contentHash)],
      });
      vi.mocked(getConfigRegistryEntry).mockResolvedValue({
        entry,
        config: emptyConfig(entry.id),
        summary: {
          id: entry.id,
          primaryEntityId: "q0",
          parameterCount: 0,
          instrumentCount: 0,
          connectionCount: 0,
        },
      });

      renderWorkspace();

      const notice = await screen.findByRole("note");
      expect(within(notice).getByText("Runtime-derived default")).toBeInTheDocument();
      expect(notice).toHaveTextContent(
        "cannot tell whether the project's Git/Python configuration source is synchronized",
      );
      expect(notice).toHaveTextContent("scopecat config diff .");
      expect(notice).not.toHaveTextContent(/drift/i);
    },
  );

  it("opens the immutable base entry for a manual parameter update", async () => {
    const entry = runtimeDerivedEntry("manual_parameter_updates");
    const baseline = configEntry("baseline", "sha256:baseline");
    const entries = [entry, baseline];
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active: {
        generation: 3,
        entryId: entry.id,
        contentHash: entry.contentHash,
      },
      entries,
      history: [activation(3, entry.id, entry.contentHash)],
    });
    vi.mocked(getConfigRegistryEntry).mockImplementation(async (entryId) => {
      const selected = entries.find((item) => item.id === entryId)!;
      return entryDetail(selected);
    });

    renderWorkspace();

    expect(await screen.findByText("Manual parameter update")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open base version baseline" }));

    expect(await screen.findByRole("heading", { name: "baseline" })).toBeInTheDocument();
    expect(screen.getByText("Direct configuration profile")).toBeInTheDocument();
  });

  it("joins candidate proposals, analyses, and the latest decision", async () => {
    const entry = runtimeDerivedEntry("candidate_config", ["gain-result", "fit-result"]);
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active: {
        generation: 3,
        entryId: entry.id,
        contentHash: entry.contentHash,
      },
      entries: [entry],
      history: [activation(3, entry.id, entry.contentHash)],
    });
    vi.mocked(getConfigRegistryEntry).mockResolvedValue(entryDetail(entry));
    vi.mocked(getRunParameterProposals).mockResolvedValue({
      runId: "run-calibration",
      items: [
        {
          id: "fit-result",
          sourceRunId: "run-calibration",
          analysisRecordId: "analysis-fit",
          baseConfigId: "baseline",
          baseContentHash: "sha256:baseline",
          reason: "Peak moved",
          confidence: 0.98,
          deltas: [],
          decisions: [
            {
              eventId: "decision-old",
              decision: "approved",
              actor: "Ada",
              authorityKind: "human",
              note: "Older note",
              decidedAt: "2026-07-24T07:00:00Z",
            },
            {
              eventId: "decision-latest",
              decision: "approved",
              actor: "nightly-calibration",
              authorityKind: "automatic_policy",
              policyId: "fit-confidence",
              policyVersion: "2",
              note: "High-confidence fit",
              decidedAt: "2026-07-24T08:00:00Z",
            },
          ],
        },
        {
          id: "endpoint-only-result",
          sourceRunId: "run-calibration",
          analysisRecordId: "analysis-endpoint-only",
          baseConfigId: "baseline",
          baseContentHash: "sha256:baseline",
          reason: "Not part of this candidate",
          confidence: 0.9,
          deltas: [],
          decisions: [],
        },
        {
          id: "gain-result",
          sourceRunId: "run-calibration",
          analysisRecordId: "analysis-gain",
          baseConfigId: "baseline",
          baseContentHash: "sha256:baseline",
          reason: "Gain moved",
          confidence: 0.97,
          deltas: [],
          decisions: [
            {
              eventId: "gain-decision-old",
              decision: "rejected",
              actor: "Ada",
              authorityKind: "human",
              note: "Stale gain review",
              decidedAt: "2026-07-24T06:00:00Z",
            },
            {
              eventId: "gain-decision-latest",
              decision: "approved",
              actor: "Grace",
              authorityKind: "human",
              note: "Gain checked",
              decidedAt: "2026-07-24T09:00:00Z",
            },
          ],
        },
      ],
    });
    vi.mocked(getRunAnalyses).mockResolvedValue([
      {
        id: "analysis-gain",
        title: "Gain fit",
        key: "gain-fit",
        outputs: [],
      },
      {
        id: "analysis-fit",
        title: "Frequency fit",
        key: "fit",
        outputs: [],
      },
    ]);
    const openRun = vi.fn();

    renderWorkspace(openRun);

    expect(await screen.findByText("Analysis candidate")).toBeInTheDocument();
    expect(screen.getByText("run-calibration")).toBeInTheDocument();
    const evidence = await screen.findAllByRole("article", {
      name: /^Proposal /,
    });
    expect(evidence).toHaveLength(2);
    expect(evidence.map((item) => item.getAttribute("aria-label"))).toEqual([
      "Proposal gain-result",
      "Proposal fit-result",
    ]);
    const gainEvidence = screen.getByRole("article", {
      name: "Proposal gain-result",
    });
    expect(
      screen.queryByRole("article", {
        name: "Proposal endpoint-only-result",
      }),
    ).not.toBeInTheDocument();
    expect(within(gainEvidence).getByText("analysis-gain")).toBeInTheDocument();
    expect(within(gainEvidence).getByText("Gain fit")).toBeInTheDocument();
    expect(within(gainEvidence).getByText("Approved · Human · Grace")).toBeInTheDocument();
    expect(within(gainEvidence).getByText("Gain checked")).toBeInTheDocument();
    expect(screen.queryByText("Stale gain review")).not.toBeInTheDocument();
    expect(await screen.findByText("analysis-fit")).toBeInTheDocument();
    expect(screen.getByText("Frequency fit")).toBeInTheDocument();
    expect(
      screen.getByText("Approved · Automatic policy fit-confidence@2 · nightly-calibration"),
    ).toBeInTheDocument();
    expect(screen.getByText("High-confidence fit")).toBeInTheDocument();
    expect(screen.queryByText("Older note")).not.toBeInTheDocument();
    expect(document.querySelector('time[datetime="2026-07-24T08:00:00Z"]')).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open producing run" }));
    expect(openRun).toHaveBeenCalledWith("run-calibration");
  });

  it("keeps decision note and time unresolved while proposals load", async () => {
    const entry = runtimeDerivedEntry("candidate_config");
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active: {
        generation: 3,
        entryId: entry.id,
        contentHash: entry.contentHash,
      },
      entries: [entry],
      history: [activation(3, entry.id, entry.contentHash)],
    });
    vi.mocked(getConfigRegistryEntry).mockResolvedValue(entryDetail(entry));
    vi.mocked(getRunParameterProposals).mockImplementation(
      () => new Promise<Awaited<ReturnType<typeof getRunParameterProposals>>>(() => undefined),
    );

    renderWorkspace();

    const evidence = await screen.findByRole("article", {
      name: "Proposal fit-result",
    });
    expect(within(evidence).getByText("Loading proposal")).toBeInTheDocument();
    expect(within(evidence).getByText("Loading decision")).toBeInTheDocument();
    expect(within(evidence).queryByText("Note")).not.toBeInTheDocument();
    expect(within(evidence).queryByText("Decided")).not.toBeInTheDocument();
  });

  it("does not report missing decision note or time when proposals fail", async () => {
    const entry = runtimeDerivedEntry("candidate_config");
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active: {
        generation: 3,
        entryId: entry.id,
        contentHash: entry.contentHash,
      },
      entries: [entry],
      history: [activation(3, entry.id, entry.contentHash)],
    });
    vi.mocked(getConfigRegistryEntry).mockResolvedValue(entryDetail(entry));
    vi.mocked(getRunParameterProposals).mockRejectedValue(new Error("proposal store offline"));

    renderWorkspace();

    expect(
      await screen.findByText("Proposal evidence unavailable: proposal store offline"),
    ).toBeInTheDocument();
    const evidence = screen.getByRole("article", {
      name: "Proposal fit-result",
    });
    expect(within(evidence).getByText("Proposal details unavailable")).toBeInTheDocument();
    expect(within(evidence).getByText("Decision unavailable")).toBeInTheDocument();
    expect(within(evidence).queryByText("Note")).not.toBeInTheDocument();
    expect(within(evidence).queryByText("Decided")).not.toBeInTheDocument();
  });
});

function renderWorkspace(onOpenRun?: (runId: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigWorkspace daemonUnavailable={false} onOpenRun={onOpenRun} />
    </QueryClientProvider>,
  );
}

function configEntry(id: string, contentHash: string) {
  return {
    id,
    contentHash,
    configRef: `entries/${id}.json`,
    registeredBy: "Ada",
    registeredAt: "2026-07-24T08:00:00Z",
    source: {
      kind: "direct_config_profile" as const,
      proposalIds: [],
    },
  };
}

function runtimeDerivedEntry(
  kind: "manual_parameter_updates" | "candidate_config",
  proposalIds = ["fit-result"],
) {
  const entry = configEntry("runtime-default", "sha256:runtime-default");
  return {
    ...entry,
    source:
      kind === "manual_parameter_updates"
        ? {
            kind,
            proposalIds: [],
            baseEntryId: "baseline",
            baseContentHash: "sha256:baseline",
            baseGeneration: 2,
          }
        : {
            kind,
            proposalIds,
            runId: "run-calibration",
            baseContentHash: "sha256:baseline",
          },
  };
}

function activation(
  generation: number,
  entryId: string,
  entryContentHash: string,
  previousEntryId?: string,
) {
  return {
    id: `activation-${generation}`,
    generation,
    action: "activation" as const,
    entryId,
    entryContentHash,
    previousEntryId,
    operator: "Ada",
    recordedAt: "2026-07-24T08:00:00Z",
  };
}

function entryDetail(entry: ConfigRegistryEntry) {
  return {
    entry,
    config: emptyConfig(entry.id),
    summary: {
      id: entry.id,
      primaryEntityId: "q0",
      parameterCount: 0,
      instrumentCount: 0,
      connectionCount: 0,
    },
  };
}

function emptyConfig(id: string) {
  return {
    id,
    system: {
      id: "system",
      primaryEntityId: "q0",
      topology: {
        entities: [],
        devices: [],
        links: [],
        lines: [],
        channels: [],
        groups: [],
      },
      instruments: [],
      routing: [],
      parameterCatalog: {
        id: "parameters",
        definitions: [],
        metadata: {},
      },
    },
    environment: {
      id: "environment",
      connections: [],
    },
    parameterSnapshot: {
      id: "parameters",
      values: [],
      metadata: {},
    },
    raw: {},
  };
}

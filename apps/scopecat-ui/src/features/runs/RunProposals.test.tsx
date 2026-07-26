// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getConfigRegistry } from "../config/config-api";
import {
  activateProposalCandidate,
  getRunParameterProposals,
  reviewParameterProposal,
} from "./proposal-api";
import type { ParameterProposal, RunParameterProposals } from "./proposal-types";
import { RunProposals } from "./RunProposals";

vi.mock("../config/config-api", () => ({
  getConfigRegistry: vi.fn(),
}));

vi.mock("./proposal-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./proposal-api")>();
  return {
    ...original,
    activateProposalCandidate: vi.fn(),
    getRunParameterProposals: vi.fn(),
    reviewParameterProposal: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("RunProposals", () => {
  it("keeps approve-only as an advanced action", async () => {
    vi.mocked(getRunParameterProposals).mockResolvedValue(proposalList(pendingProposal()));
    vi.mocked(reviewParameterProposal).mockResolvedValue();
    renderProposals();

    expect(await screen.findByText("q0.drive.frequency")).toBeInTheDocument();
    expect(screen.getByText("5 GHz")).toBeInTheDocument();
    expect(screen.getByText("5.1 GHz")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Evidence or rationale"), {
      target: { value: "Peak is clean" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Approve only/ }));
    const approvalDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(approvalDialog).getByRole("button", { name: "Approve proposal" }));

    await waitFor(() =>
      expect(reviewParameterProposal).toHaveBeenCalledWith("run-1", "drive-frequency", {
        reviewer: "local-operator",
        note: "Peak is clean",
        decision: "approved",
      }),
    );
  });

  it("can accept each approved proposal as the default without exposing generations", async () => {
    const older = approvedProposal({
      id: "older-proposal",
      proposedAt: "2026-07-22T10:00:00Z",
    });
    const latest = approvedProposal({
      id: "latest-proposal",
      proposedAt: "2026-07-23T10:00:00Z",
    });
    vi.mocked(getRunParameterProposals).mockResolvedValue(proposalList(older, latest));
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active_state: {
        generation: 3,
        active_entry_id: "baseline",
        active_entry_content_hash: "sha256:base",
      },
      entries: [],
    });
    vi.mocked(activateProposalCandidate).mockResolvedValue();
    renderProposals();

    const setDefault = await screen.findAllByRole("button", {
      name: "Accept as default",
    });
    expect(screen.getAllByText("Approved", { selector: ".proposal-state" })).toHaveLength(2);
    expect(setDefault).toHaveLength(2);
    await waitFor(() => expect(setDefault[1]).toBeEnabled());
    fireEvent.click(setDefault[1]!);
    const defaultDialog = await screen.findByRole("alertdialog");
    expect(defaultDialog).toHaveTextContent(
      "Accept proposal latest-proposal and set its configuration as the default.",
    );
    fireEvent.click(within(defaultDialog).getByRole("button", { name: "Accept as default" }));

    await waitFor(() =>
      expect(activateProposalCandidate).toHaveBeenCalledWith({
        runId: "run-1",
        proposalIds: ["latest-proposal"],
        registeredBy: "local-operator",
        operator: "local-operator",
        expectedGeneration: 3,
        note: "",
      }),
    );
  });

  it("accepts a pending proposal in one action and reports publish failure", async () => {
    vi.mocked(getRunParameterProposals).mockResolvedValue(proposalList(pendingProposal()));
    vi.mocked(reviewParameterProposal).mockResolvedValue();
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active_state: {
        generation: 3,
        active_entry_id: "baseline",
        active_entry_content_hash: "sha256:base",
      },
      entries: [],
    });
    vi.mocked(activateProposalCandidate).mockRejectedValue(new Error("generation conflict"));
    renderProposals();

    const accept = await screen.findByRole("button", {
      name: "Accept as default",
    });
    await waitFor(() => expect(accept).toBeEnabled());
    fireEvent.click(accept);
    const defaultDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(defaultDialog).getByRole("button", { name: "Accept as default" }));

    expect(
      await screen.findByText(
        "The proposal is accepted, but the default was not changed: generation conflict",
      ),
    ).toBeInTheDocument();
    expect(reviewParameterProposal).toHaveBeenCalledWith("run-1", "drive-frequency", {
      reviewer: "local-operator",
      note: "",
      decision: "approved",
    });
  });
});

function renderProposals() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RunProposals runId="run-1" />
    </QueryClientProvider>,
  );
}

function proposalList(...items: ParameterProposal[]): RunParameterProposals {
  return { runId: "run-1", items };
}

function pendingProposal(overrides: Partial<ParameterProposal> = {}): ParameterProposal {
  return {
    id: "drive-frequency",
    sourceRunId: "run-1",
    analysisRecordId: "analysis-fit",
    baseConfigId: "baseline",
    baseContentHash: "sha256:base",
    reason: "Peak moved",
    confidence: 0.94,
    proposedAt: "2026-07-23T10:00:00Z",
    deltas: [
      {
        parameterId: "q0.drive.frequency",
        before: { value: 5, unit: "GHz" },
        after: { value: 5.1, unit: "GHz" },
      },
    ],
    decisions: [],
    ...overrides,
  };
}

function approvedProposal(overrides: Partial<ParameterProposal> = {}): ParameterProposal {
  const proposal = pendingProposal(overrides);
  return {
    ...proposal,
    decisions: [
      {
        eventId: `decision-${proposal.id}`,
        decision: "approved",
        actor: "Ada",
        authorityKind: "human",
        note: "Verified",
        decidedAt: proposal.proposedAt,
      },
    ],
  };
}

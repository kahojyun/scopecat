// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getConfigRegistry } from "./config-api";
import {
  activateProposalCandidate,
  getRunParameterProposals,
  reviewParameterProposal,
} from "./proposal-api";
import type {
  ParameterProposal,
  RunParameterProposals,
} from "./proposal-types";
import { RunProposals } from "./RunProposals";

vi.mock("./config-api", () => ({
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
  it("renders proposal deltas and appends an approval decision", async () => {
    vi.mocked(getRunParameterProposals).mockResolvedValue(
      proposalList(pendingProposal()),
    );
    vi.mocked(reviewParameterProposal).mockResolvedValue();
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderProposals();

    expect(await screen.findByText("q0.drive.frequency")).toBeInTheDocument();
    expect(screen.getByText("5 GHz")).toBeInTheDocument();
    expect(screen.getByText("5.1 GHz")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Evidence or rationale"), {
      target: { value: "Peak is clean" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(reviewParameterProposal).toHaveBeenCalledWith(
        "run-1",
        "drive-frequency",
        {
          reviewer: "local-operator",
          note: "Peak is clean",
          decision: "approved",
        },
      ),
    );
  });

  it("can activate each proposal whose latest decision is approved", async () => {
    const older = approvedProposal({
      id: "older-proposal",
      proposedAt: "2026-07-22T10:00:00Z",
    });
    const latest = approvedProposal({
      id: "latest-proposal",
      proposedAt: "2026-07-23T10:00:00Z",
    });
    vi.mocked(getRunParameterProposals).mockResolvedValue(
      proposalList(older, latest),
    );
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active: {
        generation: 3,
        entryId: "baseline",
        contentHash: "sha256:base",
      },
      entries: [],
      history: [],
    });
    vi.mocked(activateProposalCandidate).mockResolvedValue();
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderProposals();

    const activate = await screen.findAllByRole("button", {
      name: "Activate config",
    });
    expect(
      screen.getAllByText("Approved", { selector: ".proposal-state" }),
    ).toHaveLength(2);
    expect(activate).toHaveLength(2);
    await waitFor(() => expect(activate[1]).toBeEnabled());
    fireEvent.click(activate[1]!);

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

  it("shows an activation failure after a successful review", async () => {
    vi.mocked(getRunParameterProposals)
      .mockResolvedValueOnce(proposalList(pendingProposal()))
      .mockResolvedValue(proposalList(approvedProposal()));
    vi.mocked(reviewParameterProposal).mockResolvedValue();
    vi.mocked(getConfigRegistry).mockResolvedValue({
      active: {
        generation: 3,
        entryId: "baseline",
        contentHash: "sha256:base",
      },
      entries: [],
      history: [],
    });
    vi.mocked(activateProposalCandidate).mockRejectedValue(
      new Error("generation conflict"),
    );
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderProposals();

    fireEvent.click(
      await screen.findByRole("button", { name: "Approve" }),
    );
    const activate = await screen.findByRole("button", {
      name: "Activate config",
    });
    await waitFor(() => expect(activate).toBeEnabled());
    fireEvent.click(activate);

    expect(
      await screen.findByText("generation conflict"),
    ).toBeInTheDocument();
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

function pendingProposal(
  overrides: Partial<ParameterProposal> = {},
): ParameterProposal {
  return {
    id: "drive-frequency",
    sourceRunId: "run-1",
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

function approvedProposal(
  overrides: Partial<ParameterProposal> = {},
): ParameterProposal {
  const proposal = pendingProposal(overrides);
  return {
    ...proposal,
    decisions: [
      {
        eventId: `decision-${proposal.id}`,
        decision: "approved",
        actor: "Ada",
        note: "Verified",
        decidedAt: proposal.proposedAt,
      },
    ],
  };
}

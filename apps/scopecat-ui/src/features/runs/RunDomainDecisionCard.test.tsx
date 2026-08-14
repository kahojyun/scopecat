// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunDomainDecisionPage } from "../../api-contract";
import type { ProjectRun } from "../../types";
import { enqueueRunDomain, getRunDomainQueue, resolveRunDomain } from "./run-api";
import { RunDomainDecisionCard } from "./RunDomainDecisionCard";

vi.mock("./run-api", () => ({
  enqueueRunDomain: vi.fn(),
  getRunDomainQueue: vi.fn(),
  resolveRunDomain: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.mocked(getRunDomainQueue).mockResolvedValue({ run_id: "run-1", items: [] });
  vi.mocked(resolveRunDomain).mockResolvedValue({
    coordinate_mode: "snap",
    region_scope: "current",
    region_ids: [],
    requested_fragment: fragment(5.16, "sha256:requested"),
    fragment: fragment(5.2, "sha256:resolved"),
    region_count: 1,
    total_point_count: 1,
  });
});

describe("RunDomainDecisionCard", () => {
  it("shows durable accepted decisions and their execution progress", () => {
    const run = projectRun(false);
    run.pointPlan.decisionCount = 2;
    renderCard(
      <RunDomainDecisionCard
        page={decisionPage()}
        error={null}
        pending={false}
        completedPointCount={4}
        run={run}
      />,
    );

    expect(screen.getByText("Complete")).toBeVisible();
    expect(screen.getByText("Accepted")).toBeVisible();
    expect(screen.getByText("Run point #5")).toBeVisible();
    expect(screen.getByText("Optimizer")).toBeVisible();
    expect(screen.queryByText(/compiled domain inspection/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Decision #1/ }));
    expect(screen.getByText("Run point #4")).toBeVisible();
  });

  it("previews snapping and enqueues the domain without resolving it twice", async () => {
    vi.mocked(enqueueRunDomain).mockResolvedValue({
      queue_index: 0,
      occurred_at: "2026-08-13T10:00:00Z",
      request: {
        request_id: "operator-domain.1",
        coordinate_mode: "snap",
        region_scope: "current",
        region_ids: [],
        region_count: 1,
        requested_fragment: fragment(5.16, "sha256:requested"),
        fragment: fragment(5.2, "sha256:resolved"),
        request_fingerprint: "sha256:request",
      },
      status: "pending",
      accepted_point_count: 0,
    });
    renderCard(
      <RunDomainDecisionCard
        page={{ run_id: "run-1", items: [], next_cursor: null }}
        error={null}
        pending={false}
        completedPointCount={1}
        run={projectRun(true)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Snap scan" }));
    fireEvent.change(screen.getByLabelText("drive_frequency values"), {
      target: { value: "5.16" },
    });
    const preview = await screen.findByText((_, element) => {
      if (element?.tagName !== "P") return false;
      return element.textContent?.includes("values will be snapped explicitly") ?? false;
    });
    expect(preview).toHaveTextContent("1 points across 1 region");
    expect(preview).toHaveTextContent("drive_frequency [5.2 GHz]");
    const resolutionCount = vi.mocked(resolveRunDomain).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Add scan" }));

    await waitFor(() =>
      expect(enqueueRunDomain).toHaveBeenCalledWith(
        "run-1",
        expect.objectContaining({
          coordinate_mode: "snap",
          region_scope: "current",
          fragment: expect.objectContaining({
            layout: "grid",
            axes: [
              {
                axis_id: "drive_frequency",
                source: {
                  kind: "values",
                  values: [{ value: 5.16, unit: "GHz" }],
                },
              },
            ],
          }),
        }),
      ),
    );
    expect(resolveRunDomain).toHaveBeenCalledTimes(resolutionCount);
    expect(screen.queryByRole("button", { name: "Inspect" })).not.toBeInTheDocument();
  });

  it("does not offer explicit region selection for a sampled region catalog", () => {
    const run = projectRun(true);
    run.plan.adaptiveRegionCount = 300;
    run.plan.adaptiveRegionsTruncated = true;

    renderCard(
      <RunDomainDecisionCard
        page={{ run_id: "run-1", items: [], next_cursor: null }}
        error={null}
        pending={false}
        completedPointCount={1}
        run={run}
      />,
    );

    expect(screen.queryByRole("option", { name: "Selected regions" })).not.toBeInTheDocument();
    expect(screen.getByText(/explicit selection is unavailable/i)).toHaveTextContent(
      "all 300 regions",
    );
  });
});

function renderCard(card: ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } })
      }
    >
      {card}
    </QueryClientProvider>,
  );
}

function projectRun(active: boolean): ProjectRun {
  return {
    runId: "run-1",
    experimentId: "adaptive-scan",
    tags: [],
    status: active ? "running" : "succeeded",
    stateLabel: active ? "Running" : "Succeeded",
    pointPlan: {
      initialPointCount: 1,
      acceptedPointCount: 1,
      pointLimit: 4,
      decisionCount: 0,
      optimizerAttemptCount: 0,
      operatorRequestCount: 0,
      closed: !active,
      stopReason: active ? undefined : "optimizer converged",
    },
    plan: {
      initialPointCount: 1,
      pointLimit: 4,
      coordinateIds: ["drive_frequency"],
      adaptiveCoordinateIds: ["drive_frequency"],
      adaptiveScope: "per_region",
      adaptiveRegionCount: 1,
      adaptiveRegions: [{ id: "region-0", coordinates: {}, initial_point_count: 1 }],
      adaptiveRegionsTruncated: false,
      coordinateSpecs: [
        {
          id: "drive_frequency",
          kind: "quantity",
          dimension: "frequency",
          unit: "GHz",
          minimum: null,
          maximum: null,
          finite: true,
          choices: null,
          entity_kind: null,
          sampled_values: [5, 5.1, 5.2].map((value) => ({ value, unit: "GHz" })),
          sampled_values_truncated: false,
        },
      ],
      sampledPoints: [5, 5.1, 5.2].map((value) => ({
        drive_frequency: { value, unit: "GHz" },
      })),
      sampledPointsTruncated: false,
      recordIds: ["signal"],
    },
    resources: [],
    contents: [],
  };
}

function decisionPage(): RunDomainDecisionPage {
  return {
    run_id: "run-1",
    items: [decision(0, 3, 5.2), decision(1, 4, 5.3)],
    next_cursor: null,
  };
}

function decision(proposalIndex: number, pointIndex: number, frequency: number) {
  return {
    operation_id: `decision-${proposalIndex}`,
    proposal_index: proposalIndex,
    occurred_at: "2026-08-13T10:00:00Z",
    proposal: {
      fragment: fragment(frequency, `sha256:fragment-${proposalIndex}`),
      region_ids: ["region-0"],
      source: "optimizer" as const,
      based_on_region_revisions: {},
      proposal_fingerprint: `sha256:proposal-${proposalIndex}`,
    },
    outcome: "accepted" as const,
    accepted_point_start: pointIndex,
    accepted_point_count: 1,
  };
}

function fragment(value: number, fingerprint: string) {
  return {
    layout: "grid" as const,
    axes: [
      {
        axis_id: "drive_frequency",
        source: { kind: "values" as const, values: [{ value, unit: "GHz" }] },
      },
    ],
    point_count: 1,
    fragment_fingerprint: fingerprint,
  };
}

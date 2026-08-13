// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunInspectionFeed } from "../../api-contract";
import type { ProjectRun } from "../../types";
import { enqueueRunDomain, getRunDomainQueue, resolveRunDomain } from "./run-api";
import { RunInspectionCard } from "./RunInspectionCard";

vi.mock("../../ui/EChart", () => ({
  EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}));
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

describe("RunInspectionCard", () => {
  it("shows compiled and completed optimizer points with side-by-side comparison", () => {
    renderCard(
      <RunInspectionCard
        feed={inspectionFeed()}
        error={null}
        pending={false}
        completedPointCount={4}
        run={projectRun(false)}
      />,
    );

    expect(screen.getByText("Complete")).toBeVisible();
    expect(screen.getByText("Compiled")).toBeVisible();
    expect(screen.getByText("Run point #5")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Compare with"), { target: { value: "0" } });

    expect(screen.getByText("Selected")).toBeVisible();
    expect(screen.getByText("Comparison")).toBeVisible();
    expect(screen.getAllByRole("img", { name: "Compiled physical waveforms" })).toHaveLength(2);
  });

  it("keeps snapping explicit and queues the displayed physical coordinates", async () => {
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
      <RunInspectionCard
        feed={{ run_id: "run-1", items: [], total_proposal_count: 0, items_truncated: false }}
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
    expect(preview).toHaveTextContent("drive_frequency [5.2]");
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

function inspectionFeed(): RunInspectionFeed {
  return {
    run_id: "run-1",
    items: [event(0, 3, 5.2), event(1, 4, 5.3)],
    total_proposal_count: 2,
    items_truncated: false,
  };
}

function event(proposalIndex: number, pointIndex: number, frequency: number) {
  return {
    proposal_index: proposalIndex,
    occurred_at: "2026-08-13T10:00:00Z",
    fragment: fragment(frequency, `sha256:fragment-${proposalIndex}`),
    region_ids: ["region-0"],
    source: "optimizer" as const,
    outcome: "accepted" as const,
    accepted_point_start: pointIndex,
    accepted_point_count: 1,
    inspections: [
      {
        operation_id: `capture:batch-${pointIndex}`,
        point_index: pointIndex,
        target_id: "reference-lab.list-mode",
        artifact_id: `artifact-${pointIndex}`,
        artifact_fingerprint: `sha256:artifact-${pointIndex}`,
        content: {
          schema_id: "scopecat.compiled_artifact_inspection.v1" as const,
          kind: "reference_lab.list_mode.v1",
          facts: [],
          point_count: 1,
          points_truncated: false,
          bounds: {
            max_points: 1,
            max_waveforms_per_point: 12,
            max_samples_per_waveform: 256,
          },
          warnings: [],
          points: [
            {
              realization_fingerprint: `sha256:realization-${pointIndex}`,
              target_entry_id: `point-${pointIndex}`,
              facts: [],
              waveform_count: 1,
              waveforms_truncated: false,
              warnings: [],
              waveforms: [
                {
                  channel_id: "awg-1/outputs/i",
                  instrument_id: "awg-1",
                  peak_abs: 0.5,
                  rms: 0.25,
                  source_sample_count: 4,
                  samples_sha256: "samples",
                  sample_indices: [0, 1, 2, 3],
                  samples: [0, 0.5, -0.5, 0],
                  downsampling: "none" as const,
                },
              ],
            },
          ],
        },
      },
    ],
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

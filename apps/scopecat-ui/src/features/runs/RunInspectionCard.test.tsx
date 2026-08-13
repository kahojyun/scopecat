// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunInspectionFeed } from "../../api-contract";
import type { MeasurementPreview, ProjectRun } from "../../types";
import { enqueueRunPoint, getRunPointQueue } from "./run-api";
import { RunInspectionCard } from "./RunInspectionCard";

vi.mock("../../ui/EChart", () => ({
  EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}));
vi.mock("./run-api", () => ({
  enqueueRunPoint: vi.fn(),
  getRunPointQueue: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.mocked(getRunPointQueue).mockResolvedValue({ run_id: "run-1", items: [] });
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
    vi.mocked(enqueueRunPoint).mockResolvedValue({
      queue_index: 0,
      occurred_at: "2026-08-13T10:00:00Z",
      request: {
        request_id: "operator-point.1",
        coordinates: { drive_frequency: { value: 5.2, unit: "GHz" } },
        coordinate_fingerprint: "sha256:queued",
      },
      status: "pending",
    });
    renderCard(
      <RunInspectionCard
        feed={{ run_id: "run-1", items: [], total_proposal_count: 0, items_truncated: false }}
        error={null}
        pending={false}
        completedPointCount={1}
        run={projectRun(true)}
        measurements={measurementPreview()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "snap" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: /drive_frequency/i }), {
      target: { value: "5.16" },
    });
    expect(screen.getByText(/Will queue snapped point/).closest("p")).toHaveTextContent("5.2 GHz");
    fireEvent.click(screen.getByRole("button", { name: "Queue point" }));

    await waitFor(() =>
      expect(enqueueRunPoint).toHaveBeenCalledWith(
        "run-1",
        expect.objectContaining({
          coordinates: { drive_frequency: { value: 5.2, unit: "GHz" } },
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
      recordIds: ["signal"],
    },
    resources: [],
    contents: [],
  };
}

function measurementPreview(): MeasurementPreview {
  return {
    items: [],
    schema: {
      dataset_id: "raw-measurements",
      format_version: "scopecat.measurement_dataset_schema.v10",
      record_schema: "scopecat.measurement_record.v4",
      point_domain: {
        kind: "product_grid",
        axes: [
          {
            id: "drive_frequency",
            size: 3,
            source: {
              kind: "values",
              values: [5, 5.1, 5.2].map((value) => ({
                kind: "scalar" as const,
                dtype: "float64" as const,
                unit: "GHz",
                value,
              })),
            },
          },
        ],
      },
      dimensions: [{ id: "point", kind: "point", size: 3 }],
      variables: [],
    },
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
    candidate: {
      coordinates: { drive_frequency: { value: frequency, unit: "GHz" } },
      proposal_fingerprint: `sha256:proposal-${proposalIndex}`,
      source: "optimizer" as const,
    },
    outcome: "accepted" as const,
    accepted_point: {
      point_index: pointIndex,
      coordinates: { drive_frequency: { value: frequency, unit: "GHz" } },
      proposal_fingerprint: `sha256:proposal-${proposalIndex}`,
      source: "optimizer" as const,
    },
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

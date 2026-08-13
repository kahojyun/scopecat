// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReviewSession } from "../../api-contract";
import { ReviewWorkspace } from "./ReviewWorkspace";
import { compileReviewPoint, getReview, getReviews } from "./review-api";

vi.mock("./review-api", () => ({
  compileReviewPoint: vi.fn(),
  getReview: vi.fn(),
  getReviews: vi.fn(),
}));

vi.mock("../../ui/EChart", () => ({
  EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}));

beforeEach(() => {
  const value = reviewSession();
  vi.mocked(getReviews).mockResolvedValue({ items: [value] });
  vi.mocked(getReview).mockResolvedValue(value);
  vi.mocked(compileReviewPoint).mockResolvedValue();
  window.history.replaceState(null, "", "/#reviews/review-1");
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ReviewWorkspace", () => {
  it("shows typed waveform inspection and physical realization identity", async () => {
    renderWorkspace();

    expect(await screen.findByText("Compile point")).toBeVisible();
    expect(screen.getByText("Planned point #1")).toBeVisible();
    expect(screen.getByRole("img", { name: "Compiled physical waveforms" })).toBeVisible();
    expect(screen.getByText("awg-1/outputs/i")).toBeVisible();
    expect(screen.getByText("sha256:realization")).toBeVisible();
  });

  it("submits off-grid coordinates without snapping to the planned point", async () => {
    renderWorkspace();
    await screen.findByText("Compile point");

    fireEvent.click(screen.getByRole("button", { name: "Off-grid" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: /beta/i }), {
      target: { value: "0.137" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "amplification" }), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Compile waveform" }));

    await waitFor(() =>
      expect(compileReviewPoint).toHaveBeenCalledWith("review-1", {
        coordinate_mode: "free",
        coordinates: {
          amplification: 2,
          beta: { unit: "ns", value: 0.137 },
        },
      }),
    );
  });

  it("keeps strict coordinate matching as a separate selectable mode", async () => {
    renderWorkspace();
    await screen.findByText("Compile point");

    fireEvent.click(screen.getByRole("button", { name: "exact" }));
    fireEvent.click(screen.getByRole("button", { name: "Compile waveform" }));

    await waitFor(() =>
      expect(compileReviewPoint).toHaveBeenCalledWith(
        "review-1",
        expect.objectContaining({ coordinate_mode: "exact" }),
      ),
    );
  });
});

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReviewWorkspace daemonUnavailable={false} />
    </QueryClientProvider>,
  );
}

function reviewSession(): ReviewSession {
  return {
    active: true,
    coordinates: [
      {
        id: "beta",
        kind: "quantity",
        unit: "ns",
        minimum: -1,
        maximum: 1,
        planned_values: [{ value: 0, unit: "ns" }],
        planned_values_truncated: false,
      },
      {
        id: "amplification",
        kind: "int",
        minimum: 1,
        maximum: 3,
        planned_values: [1, 2, 3],
        planned_values_truncated: false,
      },
    ],
    created_at: "2026-08-13T09:00:00Z",
    experiment_id: "drag-beta",
    experiment_kind: "experiment",
    latest_result: {
      completed_at: "2026-08-13T09:00:01Z",
      request_id: "initial",
      inspections: [
        {
          operation_id: "capture",
          point_index: 0,
          target_id: "reference-lab.list-mode",
          artifact_id: "artifact-1",
          artifact_fingerprint: "sha256:artifact",
          content: {
            schema_id: "scopecat.compiled_artifact_inspection.v1",
            kind: "reference_lab.list_mode.v1",
            facts: [{ id: "sample_rate_hz", value: 1_000_000_000, unit: "Hz" }],
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
                realization_fingerprint: "sha256:realization",
                target_entry_id: "point-0",
                facts: [{ id: "sample_count", value: 4 }],
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
                    downsampling: "none",
                  },
                ],
              },
            ],
          },
        },
      ],
      point: {
        point_index: 0,
        coordinates: { beta: { value: 0, unit: "ns" }, amplification: 1 },
        proposal_fingerprint: "sha256:proposal",
        source: "author",
      },
    },
    pending_request_count: 0,
    planned_points: [
      {
        point_index: 0,
        coordinates: { beta: { value: 0, unit: "ns" }, amplification: 1 },
        source: "author",
      },
    ],
    planned_points_truncated: false,
    session_id: "review-1",
    title: "DRAG beta review",
    updated_at: "2026-08-13T09:00:01Z",
  };
}

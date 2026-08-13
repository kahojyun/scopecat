// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunInspectionFeed } from "../../api-contract";
import { RunInspectionCard } from "./RunInspectionCard";

vi.mock("../../ui/EChart", () => ({
  EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}));

afterEach(cleanup);

describe("RunInspectionCard", () => {
  it("shows compiled and completed optimizer points with side-by-side comparison", () => {
    render(
      <RunInspectionCard
        feed={inspectionFeed()}
        error={null}
        pending={false}
        completedPointCount={4}
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
});

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

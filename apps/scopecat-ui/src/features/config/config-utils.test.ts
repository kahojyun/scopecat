import { describe, expect, it } from "vitest";
import type { ConfigRegistryEntry } from "../../api-contract";
import { configSourceLabel, filterConfigEntries } from "./config-utils";

const HASH = `sha256:${"a".repeat(64)}`;

describe("calibration cohort registry presentation", () => {
  const entry: ConfigRegistryEntry = {
    id: "drag-merged",
    config_ref: "entries/drag-merged.json",
    content_hash: HASH,
    actor: "resident-worker",
    note: "nightly calibration",
    recorded_at: "2026-08-19T01:00:00Z",
    source: {
      kind: "calibration_cohort_merge",
      cohort_id: "drag-nightly",
      spec_hash: HASH,
      composition_policy_ref: {
        id: "reference_lab.drag-composition",
        version: "1",
        fingerprint: HASH,
      },
      merge_policy: "common_base_cells_v1",
      base_entry_id: "baseline",
      base_config_content_hash: HASH,
      base_registry_generation: 4,
      candidate_id: "drag-candidate",
      contributions: [
        {
          member_id: "q0",
          procedure_run_id: "procedure-q0",
          baseline_step: { step_key: "baseline", attempt: 1 },
          baseline_run_id: "baseline-run-q0",
          fit_step: { step_key: "fit", attempt: 1 },
          fit_analysis_record_id: "fit-analysis-q0",
          candidate_step: { step_key: "candidate", attempt: 1 },
          candidate_run_id: "candidate-run-q0",
          proposal_id: "proposal-q0",
          verification_step: { step_key: "verification", attempt: 1 },
          decision: {
            analysis_record_id: "verification-analysis-q0",
            output_id: "decision",
            schema_id: "reference_lab.drag-decision.v1",
            schema_hash: HASH,
          },
          result_input_fingerprint: HASH,
        },
      ],
    },
  };

  it("has its own source label", () => {
    expect(configSourceLabel(entry)).toBe("Calibration cohort merge");
  });

  it.each([
    "drag-nightly",
    "reference_lab.drag-composition",
    "q0",
    "procedure-q0",
    "proposal-q0",
    "fit-analysis-q0",
  ])("is searchable by exact provenance term %s", (term) => {
    expect(filterConfigEntries([entry], term)).toEqual([entry]);
  });
});

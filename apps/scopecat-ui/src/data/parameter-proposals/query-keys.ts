export const parameterProposalKeys = {
  all: ["parameter-proposals"] as const,
  run: (runId: string) => ["parameter-proposals", runId] as const,
  firstPage: (runId: string) => ["parameter-proposals", runId, "first-page"] as const,
  infinite: (runId: string) => ["parameter-proposals", runId, "infinite"] as const,
};

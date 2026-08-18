import type { AnalysisRecordOutput } from "../../api-contract";
import type { AnalysisOutput } from "../../types";

export function analysisOutput(output: AnalysisRecordOutput): AnalysisOutput {
  const producedBy =
    output.kind === "fact" || output.kind === "dataset" || output.kind === "artifact"
      ? (output.produced_by ?? undefined)
      : undefined;
  const derivedFrom = output.kind === "dataset" ? (output.derived_from ?? undefined) : undefined;
  const shared = {
    id: output.id,
    title: output.title,
    producedBy,
    derivedFrom,
    metadata: output.metadata ?? {},
  };
  if (output.kind === "table") {
    return { ...shared, kind: "table", content: output.content };
  }
  if (output.kind === "figure") {
    return { ...shared, kind: "figure", content: output.content };
  }
  if (output.kind === "fact") {
    return { ...shared, kind: "fact", content: output.content };
  }
  if (output.kind === "dataset") {
    return { ...shared, kind: "dataset", content: output.content };
  }
  if (output.kind === "artifact") {
    return { ...shared, kind: "artifact", content: output.content };
  }
  return {
    ...shared,
    kind: "parameter_change_proposal",
    content: output.content,
  };
}

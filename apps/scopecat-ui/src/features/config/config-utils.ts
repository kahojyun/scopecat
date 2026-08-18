import type { ConfigRegistryEntry } from "../../api-contract";

export function filterConfigEntries(
  entries: ConfigRegistryEntry[],
  search: string,
): ConfigRegistryEntry[] {
  const query = search.trim().toLocaleLowerCase();
  if (!query) return entries;
  return entries.filter((entry) => {
    const sourceTerms = configSourceSearchTerms(entry.source);
    return [entry.id, entry.actor, entry.note, entry.source.kind, ...sourceTerms]
      .filter((value): value is string => value !== undefined)
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });
}

export function configSourceLabel(entry: ConfigRegistryEntry): string {
  switch (entry.source.kind) {
    case "direct_config_profile":
      return "Direct profile";
    case "manual_parameter_updates":
      return "Typed parameter edit";
    case "candidate_config":
      return "Candidate config";
    case "calibration_cohort_merge":
      return "Calibration cohort merge";
    default:
      return assertNever(entry.source);
  }
}

function configSourceSearchTerms(
  source: ConfigRegistryEntry["source"],
): Array<string | null | undefined> {
  switch (source.kind) {
    case "direct_config_profile":
    case "manual_parameter_updates":
      return [];
    case "candidate_config":
      return [source.run_id, source.proposal_id];
    case "calibration_cohort_merge":
      return [
        source.cohort_id,
        source.spec_hash,
        source.candidate_id,
        source.base_entry_id,
        source.base_config_content_hash,
        source.composition_policy_ref.id,
        source.composition_policy_ref.version,
        source.composition_policy_ref.fingerprint,
        source.automatic_publication_policy_id,
        source.automatic_publication_policy_version,
        source.automatic_publication_policy_fingerprint,
        ...source.contributions.flatMap((contribution) => [
          contribution.member_id,
          contribution.procedure_run_id,
          contribution.baseline_run_id,
          contribution.baseline_step.step_key,
          contribution.candidate_run_id,
          contribution.candidate_step.step_key,
          contribution.proposal_id,
          contribution.fit_analysis_record_id,
          contribution.fit_step.step_key,
          contribution.verification_step.step_key,
          contribution.decision.analysis_record_id,
          contribution.decision.output_id,
          contribution.result_input_fingerprint,
        ]),
      ];
    default:
      return assertNever(source);
  }
}

function assertNever(value: never): never {
  throw new Error(`Unsupported config source: ${JSON.stringify(value)}`);
}

export function safeConfigEntryId(value: string): string {
  const normalized = value
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return /^[A-Za-z0-9]/.test(normalized) ? normalized : `config-${normalized}`;
}

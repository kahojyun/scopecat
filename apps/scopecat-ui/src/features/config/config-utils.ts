import type { ConfigRegistryEntry } from "../../api-contract";

export function filterConfigEntries(
  entries: ConfigRegistryEntry[],
  search: string,
): ConfigRegistryEntry[] {
  const query = search.trim().toLocaleLowerCase();
  if (!query) return entries;
  return entries.filter((entry) => {
    const candidateTerms =
      entry.source.kind === "candidate_config"
        ? [entry.source.run_id, entry.source.proposal_id]
        : [];
    return [entry.id, entry.actor, entry.note, entry.source.kind, ...candidateTerms]
      .filter((value): value is string => value !== undefined)
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });
}

export function configSourceLabel(entry: ConfigRegistryEntry): string {
  if (entry.source.kind === "candidate_config") return "Candidate config";
  if (entry.source.kind === "manual_parameter_updates") return "Typed parameter edit";
  return "Direct profile";
}

export function safeConfigEntryId(value: string): string {
  const normalized = value
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return /^[A-Za-z0-9]/.test(normalized) ? normalized : `config-${normalized}`;
}

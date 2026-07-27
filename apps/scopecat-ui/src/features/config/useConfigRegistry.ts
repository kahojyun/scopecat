import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../../api";
import { getConfigRegistry, getConfigRegistryEntry } from "./config-api";
import { filterConfigEntries } from "./config-utils";

export function useConfigRegistry(daemonUnavailable: boolean) {
  const [selectedId, setSelectedId] = useState<string>();
  const [registrySearch, setRegistrySearch] = useState("");
  const registryQuery = useQuery({
    queryKey: ["config", "registry"],
    queryFn: ({ signal }) => getConfigRegistry(signal),
    enabled: !daemonUnavailable,
    refetchInterval: 5_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
  });
  const overview = registryQuery.data;

  useEffect(() => {
    if (!overview) return;
    const selectionExists = overview.entries.some((entry) => entry.id === selectedId);
    if (selectionExists) return;
    const preferred =
      overview.entries.find((entry) => entry.id === overview.activation?.entry_id) ??
      overview.entries[0];
    setSelectedId(preferred?.id);
  }, [overview, selectedId]);

  const filteredEntries = useMemo(
    () => filterConfigEntries(overview?.entries ?? [], registrySearch),
    [overview?.entries, registrySearch],
  );
  const selectedEntry = overview?.entries.find((entry) => entry.id === selectedId);
  const activeEntry = overview?.entries.find((entry) => entry.id === overview.activation?.entry_id);
  const entryDetailQuery = useQuery({
    queryKey: ["config", "entry", selectedEntry?.id, selectedEntry?.content_hash],
    queryFn: ({ signal }) => getConfigRegistryEntry(selectedEntry!.id, signal),
    enabled: selectedEntry !== undefined,
    staleTime: Infinity,
  });
  const activeDetailQuery = useQuery({
    queryKey: ["config", "entry", activeEntry?.id, activeEntry?.content_hash],
    queryFn: ({ signal }) => getConfigRegistryEntry(activeEntry!.id, signal),
    enabled: activeEntry !== undefined,
    staleTime: Infinity,
  });

  return {
    registryQuery,
    overview,
    selectedId,
    selectEntry: setSelectedId,
    registrySearch,
    setRegistrySearch,
    filteredEntries,
    selectedEntry,
    entryDetailQuery,
    activeDetailQuery,
  };
}

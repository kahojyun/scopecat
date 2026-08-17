import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError } from "../../api-client";
import type {
  ConfigActivationPage,
  ConfigRegistryOverview,
  ConfigRegistryPage,
} from "../../api-contract";
import {
  getConfigRegistry,
  getConfigRegistryEntry,
  getOlderConfigActivationHistory,
  getOlderConfigRegistryEntries,
} from "./config-api";
import { filterConfigEntries } from "./config-utils";

interface OlderEntryHistory {
  headCursor: number;
  pages: ConfigRegistryPage[];
}

interface OlderActivationHistory {
  headCursor: number;
  pages: ConfigActivationPage[];
}

export function useConfigRegistry(daemonUnavailable: boolean) {
  const [selection, setSelection] = useState<{ id?: string; userSelected: boolean }>({
    userSelected: false,
  });
  const [registrySearch, setRegistrySearch] = useState("");
  const registryQuery = useQuery({
    queryKey: ["config", "registry"],
    queryFn: ({ signal }) => getConfigRegistry(signal),
    enabled: !daemonUnavailable,
    refetchInterval: 5_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
  });
  const [olderEntries, setOlderEntries] = useState<OlderEntryHistory>();
  const [olderActivations, setOlderActivations] = useState<OlderActivationHistory>();
  const entryHeadCursor = registryQuery.data?.entries_next_cursor;
  const activationHeadCursor = registryQuery.data?.activation_history_next_cursor;
  const olderEntriesMutation = useMutation({
    mutationFn: ({ before }: { before: number; headCursor: number }) =>
      getOlderConfigRegistryEntries(before),
    onSuccess: (page, request) => {
      if (entryHeadCursor !== request.headCursor) return;
      setOlderEntries((current) =>
        current?.headCursor === request.headCursor
          ? { ...current, pages: [...current.pages, page] }
          : { headCursor: request.headCursor, pages: [page] },
      );
    },
  });
  const olderActivationsMutation = useMutation({
    mutationFn: ({ before }: { before: number; headCursor: number }) =>
      getOlderConfigActivationHistory(before),
    onSuccess: (page, request) => {
      if (activationHeadCursor !== request.headCursor) return;
      setOlderActivations((current) =>
        current?.headCursor === request.headCursor
          ? { ...current, pages: [...current.pages, page] }
          : { headCursor: request.headCursor, pages: [page] },
      );
    },
  });
  const overview = useMemo<ConfigRegistryOverview | undefined>(() => {
    const head = registryQuery.data;
    if (!head) return undefined;
    const entryPages =
      olderEntries && olderEntries.headCursor === entryHeadCursor ? olderEntries.pages : [];
    const activationPages =
      olderActivations && olderActivations.headCursor === activationHeadCursor
        ? olderActivations.pages
        : [];
    const entries = new Map(head.entries.map((entry) => [entry.id, entry]));
    const activations = new Map(
      head.activation_history.map((record) => [record.generation, record]),
    );
    for (const page of entryPages) {
      for (const entry of page.entries) entries.set(entry.id, entry);
    }
    for (const page of activationPages) {
      for (const record of page.items) activations.set(record.generation, record);
    }
    return {
      ...head,
      entries: [...entries.values()],
      activation_history: [...activations.values()],
      entries_next_cursor:
        entryPages.length > 0
          ? (entryPages.at(-1)?.next_cursor ?? undefined)
          : head.entries_next_cursor,
      activation_history_next_cursor:
        activationPages.length > 0
          ? (activationPages.at(-1)?.next_cursor ?? undefined)
          : head.activation_history_next_cursor,
    };
  }, [
    activationHeadCursor,
    entryHeadCursor,
    olderActivations,
    olderEntries,
    registryQuery.data,
  ]);
  const selectedId = selection.id;
  const activeEntryId = overview?.activation?.entry_id;
  const activeDetailQuery = useQuery({
    queryKey: ["config", "entry", activeEntryId],
    queryFn: ({ signal }) => getConfigRegistryEntry(activeEntryId!, signal),
    enabled: activeEntryId !== undefined,
    staleTime: Infinity,
  });
  const displayedEntries = useMemo(() => {
    const entries = overview?.entries ?? [];
    const activeEntry = activeDetailQuery.data?.entry;
    return activeEntry && !entries.some((entry) => entry.id === activeEntry.id)
      ? [activeEntry, ...entries]
      : entries;
  }, [activeDetailQuery.data?.entry, overview?.entries]);

  useEffect(() => {
    setOlderEntries((current) =>
      current && current.headCursor !== entryHeadCursor ? undefined : current,
    );
  }, [entryHeadCursor]);

  useEffect(() => {
    setOlderActivations((current) =>
      current && current.headCursor !== activationHeadCursor ? undefined : current,
    );
  }, [activationHeadCursor]);

  useEffect(() => {
    if (!overview) return;
    const selectionExists = displayedEntries.some((entry) => entry.id === selectedId);
    if (selection.userSelected && selectionExists) return;
    const preferredId = activeEntryId ?? displayedEntries[0]?.id;
    if (preferredId === selectedId && !selection.userSelected) return;
    setSelection({ id: preferredId, userSelected: false });
  }, [activeEntryId, displayedEntries, overview, selectedId, selection.userSelected]);

  const selectEntry = useCallback((entryId: string) => {
    setSelection({ id: entryId, userSelected: true });
  }, []);

  const filteredEntries = useMemo(
    () => filterConfigEntries(displayedEntries, registrySearch),
    [displayedEntries, registrySearch],
  );
  const selectedEntry = displayedEntries.find((entry) => entry.id === selectedId);
  const entryDetailQuery = useQuery({
    queryKey: ["config", "entry", selectedEntry?.id],
    queryFn: ({ signal }) => getConfigRegistryEntry(selectedEntry!.id, signal),
    enabled: selectedEntry !== undefined,
    staleTime: Infinity,
  });

  return {
    registryQuery,
    overview,
    selectedId,
    selectEntry,
    registrySearch,
    setRegistrySearch,
    filteredEntries,
    selectedEntry,
    entryDetailQuery,
    activeDetailQuery,
    olderEntriesMutation,
    olderActivationsMutation,
    loadOlderEntries: () => {
      if (entryHeadCursor === undefined || overview?.entries_next_cursor === undefined) return;
      olderEntriesMutation.mutate({
        headCursor: entryHeadCursor,
        before: overview.entries_next_cursor,
      });
    },
    loadOlderActivations: () => {
      if (
        activationHeadCursor === undefined ||
        overview?.activation_history_next_cursor === undefined
      )
        return;
      olderActivationsMutation.mutate({
        headCursor: activationHeadCursor,
        before: overview.activation_history_next_cursor,
      });
    },
  };
}

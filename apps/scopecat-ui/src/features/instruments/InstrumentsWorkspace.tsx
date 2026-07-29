import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Cable,
  CircleOff,
  LoaderCircle,
  Plus,
  RefreshCw,
  ServerCrash,
} from "lucide-react";
import type { InstrumentSession, InstrumentSessionLease, InstrumentView } from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { InstrumentConfigDialog } from "./InstrumentConfigDialog";
import { AvailabilityBadge, InstrumentInspector } from "./InstrumentInspector";
import {
  abortInstrumentSession,
  closeInstrumentSession,
  connectionSummary,
  createInstrumentCommandId,
  getActiveConfig,
  getDriverCatalog,
  getInstruments,
  openInstrumentSession,
  renewInstrumentSession,
  retryTransientInstrumentMutation,
} from "./instrument-api";

const EMPTY_INSTRUMENTS: InstrumentView[] = [];
const LOCAL_OPERATOR = "local-operator";
type ConfigTarget = { kind: "add" } | { kind: "edit"; instrumentId: string };

export function InstrumentsWorkspace({ daemonUnavailable }: { daemonUnavailable: boolean }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string>();
  const [session, setSession] = useState<InstrumentSession>();
  const [sessionError, setSessionError] = useState<string>();
  const [configTarget, setConfigTarget] = useState<ConfigTarget>();
  const sessionRef = useRef<InstrumentSession | undefined>(undefined);
  const closingRef = useRef(false);
  const pendingSelectionRef = useRef<string | undefined>(undefined);
  const openAttemptRef = useRef<{ key: string; operationId: string } | undefined>(undefined);

  const instrumentsQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: ({ signal }) => getInstruments(signal),
    enabled: !daemonUnavailable,
  });
  const activeConfigQuery = useQuery({
    queryKey: ["config", "active"],
    queryFn: ({ signal }) => getActiveConfig(signal),
    enabled: !daemonUnavailable && configTarget !== undefined,
  });
  const driverCatalogQuery = useQuery({
    queryKey: ["instrument-drivers"],
    queryFn: ({ signal }) => getDriverCatalog(signal),
    enabled: !daemonUnavailable,
  });

  const instruments = instrumentsQuery.data?.items ?? EMPTY_INSTRUMENTS;
  const selected = instruments.find((instrument) => instrument.instrument_id === selectedId);

  useEffect(() => {
    if (instruments.length === 0) {
      setSelectedId(undefined);
      return;
    }
    if (!selectedId || !instruments.some((instrument) => instrument.instrument_id === selectedId)) {
      setSelectedId(instruments[0]?.instrument_id);
    }
  }, [instruments, selectedId]);

  useEffect(() => {
    if (!configTarget || !activeConfigQuery.isError) return;
    setSessionError(errorMessage(activeConfigQuery.error));
    setConfigTarget(undefined);
  }, [activeConfigQuery.error, activeConfigQuery.isError, configTarget]);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    const releaseOnExit = () => {
      const current = sessionRef.current;
      if (!current || closingRef.current) return;
      sessionRef.current = undefined;
      closingRef.current = true;
      void closeInstrumentSession(current.session_id, true).catch(() => {
        // Lease expiry releases the session if this fast close cannot reach the daemon.
      });
    };
    window.addEventListener("beforeunload", releaseOnExit);
    return () => {
      window.removeEventListener("beforeunload", releaseOnExit);
      releaseOnExit();
    };
  }, []);

  const connectMutation = useMutation({
    mutationFn: ({
      instrumentId,
      operator,
      operationId,
    }: {
      instrumentId: string;
      operator: string;
      operationId: string;
    }) => openInstrumentSession(instrumentId, operator, operationId),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: async (opened) => {
      openAttemptRef.current = undefined;
      closingRef.current = false;
      sessionRef.current = opened;
      setSession(opened);
      setSessionError(undefined);
      await queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: (cause) => setSessionError(errorMessage(cause)),
  });
  const endMutation = useMutation({
    mutationFn: ({ sessionId, abort }: { sessionId: string; abort: boolean }) =>
      abort ? abortInstrumentSession(sessionId) : closeInstrumentSession(sessionId),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (_, { sessionId }) => {
      if (sessionRef.current?.session_id === sessionId) {
        sessionRef.current = undefined;
        setSession(undefined);
      }
      const pendingSelection = pendingSelectionRef.current;
      pendingSelectionRef.current = undefined;
      if (pendingSelection) setSelectedId(pendingSelection);
      setSessionError(undefined);
    },
    onError: (cause) => {
      pendingSelectionRef.current = undefined;
      setSessionError(errorMessage(cause));
    },
    onSettled: async () => {
      closingRef.current = false;
      await queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });

  const selectInstrument = (instrumentId: string) => {
    openAttemptRef.current = undefined;
    connectMutation.reset();
    const current = sessionRef.current;
    if (current && !current.instrument_ids.includes(instrumentId)) {
      pendingSelectionRef.current = instrumentId;
      if (!closingRef.current) endSession(current.session_id);
      return;
    }
    setSelectedId(instrumentId);
    setSessionError(undefined);
  };
  const closeCurrent = () => {
    const current = sessionRef.current;
    if (!current || closingRef.current) return;
    pendingSelectionRef.current = undefined;
    endSession(current.session_id);
  };
  const loseCurrent = (message: string) => {
    sessionRef.current = undefined;
    setSession(undefined);
    setSessionError(message);
    void queryClient.invalidateQueries({ queryKey: ["instruments"] });
  };
  const connectCurrent = (instrumentId: string) => {
    const key = instrumentId;
    if (openAttemptRef.current?.key !== key) {
      openAttemptRef.current = {
        key,
        operationId: createInstrumentCommandId("open"),
      };
    }
    connectMutation.mutate({
      instrumentId,
      operator: LOCAL_OPERATOR,
      operationId: openAttemptRef.current.operationId,
    });
  };
  const endSession = (sessionId: string, abort = false) => {
    closingRef.current = true;
    setSessionError(undefined);
    endMutation.mutate({ sessionId, abort });
  };

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    let timeout: number | undefined;

    const scheduleRenewal = (lease: InstrumentSessionLease) => {
      const renewedAt = Date.parse(lease.renewed_at);
      const leaseDuration = Date.parse(lease.expires_at) - renewedAt;
      const delay = Math.max(0, renewedAt + leaseDuration / 3 - Date.now());
      timeout = window.setTimeout(() => {
        void renewInstrumentSession(lease.session_id).then(
          (renewed) => {
            const current = sessionRef.current;
            if (cancelled || current?.session_id !== renewed.session_id) return;
            const next = { ...current, ...renewed };
            sessionRef.current = next;
            setSession(next);
            scheduleRenewal(renewed);
          },
          () => {
            if (cancelled || sessionRef.current?.session_id !== lease.session_id) return;
            loseCurrent(
              "The instrument session lease was lost. The daemon will release the instrument when the lease expires.",
            );
          },
        );
      }, delay);
    };

    scheduleRenewal(session);
    return () => {
      cancelled = true;
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
    // Renewal reschedules itself from each authoritative lease receipt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.session_id]);

  useEffect(() => {
    if (!session) return;
    const sessionInstrument = instruments.find((instrument) =>
      session.instrument_ids.includes(instrument.instrument_id),
    );
    if (!sessionInstrument) return;
    const ownerChanged =
      sessionInstrument.availability === "active" &&
      (sessionInstrument.owner_kind !== "instrument_session" ||
        sessionInstrument.owner_id !== session.session_id);
    if (sessionInstrument.availability === "quarantined" || ownerChanged) {
      loseCurrent(
        sessionInstrument.availability === "quarantined"
          ? "The daemon quarantined this instrument after an uncertain operation."
          : "The instrument is now owned by another run or session.",
      );
    }
    // Reconcile the local session whenever a fresh canonical instrument view arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrumentsQuery.dataUpdatedAt, session?.session_id]);

  return (
    <section className="instruments-workspace" aria-labelledby="instruments-heading">
      <header className="instruments-toolbar">
        <div>
          <span className="eyebrow">Direct hardware interaction</span>
          <h2 id="instruments-heading">Instruments</h2>
          <p>Inspect device controls, then explicitly connect one device for direct interaction.</p>
        </div>
      </header>

      {(instrumentsQuery.data?.problems ?? []).length > 0 && (
        <div className="instrument-provider-problems" role="status">
          <AlertTriangle size={17} aria-hidden="true" />
          <div>
            <strong>Instrument provider issues</strong>
            {(instrumentsQuery.data?.problems ?? []).map((problem, index) => (
              <p key={`${problem.code}-${index}`}>{problem.message}</p>
            ))}
          </div>
        </div>
      )}

      <div className="instruments-layout">
        <aside className="instrument-browser" aria-label="Configured instruments">
          <div className="instrument-browser-heading">
            <div>
              <h3>Devices</h3>
              <small>{instruments.length} configured</small>
            </div>
            <div className="instrument-browser-actions">
              <button
                type="button"
                className="icon-button"
                aria-label="Add instrument"
                title={driverCatalogQuery.isError ? "Driver catalog unavailable" : "Add instrument"}
                disabled={driverCatalogQuery.isPending || driverCatalogQuery.isError}
                onClick={() => {
                  setSessionError(undefined);
                  setConfigTarget({ kind: "add" });
                }}
              >
                <Plus size={15} />
              </button>
              <button
                type="button"
                className="icon-button"
                aria-label="Refresh instruments"
                title="Refresh instruments"
                onClick={() => void queryClient.invalidateQueries({ queryKey: ["instruments"] })}
              >
                <RefreshCw size={15} className={instrumentsQuery.isFetching ? "spin" : undefined} />
              </button>
            </div>
          </div>

          {daemonUnavailable ? (
            <InstrumentListMessage
              icon={<ServerCrash />}
              title="Instrument index unavailable"
              detail="Reconnect to the local daemon to inspect configured devices."
            />
          ) : instrumentsQuery.isPending ? (
            <InstrumentListMessage
              icon={<LoaderCircle className="spin" />}
              title="Loading instruments"
              detail="Reading the active configuration and current instrument owners."
            />
          ) : instrumentsQuery.isError ? (
            <InstrumentListMessage
              icon={<AlertTriangle />}
              title="Could not load instruments"
              detail={errorMessage(instrumentsQuery.error)}
              error
            />
          ) : instruments.length === 0 ? (
            <InstrumentListMessage
              icon={<CircleOff />}
              title="No instruments configured"
              detail="Add a registered device to the active laboratory configuration."
            />
          ) : (
            <div className="instrument-list">
              {instruments.map((instrument) => (
                <InstrumentListItem
                  key={instrument.instrument_id}
                  instrument={instrument}
                  selected={instrument.instrument_id === selected?.instrument_id}
                  connected={session?.instrument_ids.includes(instrument.instrument_id)}
                  onSelect={() => selectInstrument(instrument.instrument_id)}
                />
              ))}
            </div>
          )}
        </aside>

        {selected ? (
          <InstrumentInspector
            key={selected.instrument_id}
            instrument={selected}
            session={session}
            sessionError={sessionError}
            connectPending={
              connectMutation.isPending &&
              connectMutation.variables?.instrumentId === selected.instrument_id
            }
            closePending={endMutation.isPending}
            configurationPending={
              configTarget?.kind === "edit" &&
              configTarget.instrumentId === selected.instrument_id &&
              (activeConfigQuery.isFetching || driverCatalogQuery.isFetching)
            }
            configurationUnavailable={driverCatalogQuery.isError}
            onConnect={() => connectCurrent(selected.instrument_id)}
            onClose={closeCurrent}
            onSessionLost={loseCurrent}
            onDisconnectOwner={() => {
              if (
                selected.owner_kind === "instrument_session" &&
                selected.owner_id &&
                !closingRef.current
              ) {
                endSession(selected.owner_id, true);
              }
            }}
            onConfigure={() => {
              setSessionError(undefined);
              setConfigTarget({ kind: "edit", instrumentId: selected.instrument_id });
            }}
          />
        ) : (
          <div className="instrument-inspector no-selection">
            <InstrumentListMessage
              icon={<Cable />}
              title="Nothing selected"
              detail="Choose a configured instrument to inspect its controls."
            />
          </div>
        )}
      </div>

      {configTarget &&
        activeConfigQuery.data &&
        driverCatalogQuery.data &&
        !activeConfigQuery.isFetching &&
        !activeConfigQuery.isError &&
        !driverCatalogQuery.isFetching &&
        !driverCatalogQuery.isError && (
          <InstrumentConfigDialog
            key={`${configTarget.kind}-${
              configTarget.kind === "edit" ? configTarget.instrumentId : "new"
            }-${activeConfigQuery.data.activation.generation}`}
            active={activeConfigQuery.data}
            catalog={driverCatalogQuery.data}
            instrumentId={configTarget.kind === "edit" ? configTarget.instrumentId : undefined}
            description={
              configTarget.kind === "edit"
                ? (instruments.find(
                    (instrument) => instrument.instrument_id === configTarget.instrumentId,
                  )?.description ?? undefined)
                : undefined
            }
            onCancel={() => setConfigTarget(undefined)}
            onPublished={async (instrumentId) => {
              setConfigTarget(undefined);
              setSelectedId(instrumentId);
              await Promise.all([
                queryClient.invalidateQueries({ queryKey: ["config"] }),
                queryClient.invalidateQueries({ queryKey: ["instruments"] }),
              ]);
            }}
          />
        )}
    </section>
  );
}

function InstrumentListItem({
  instrument,
  selected,
  connected,
  onSelect,
}: {
  instrument: InstrumentView;
  selected: boolean;
  connected?: boolean;
  onSelect: () => void;
}) {
  const label = instrument.description?.label ?? instrument.instrument_id;
  return (
    <button
      type="button"
      className={`instrument-list-item ${selected ? "selected" : ""}`}
      aria-current={selected ? "true" : undefined}
      title={`Inspect instrument ${instrument.instrument_id}`}
      onClick={onSelect}
    >
      <span className="instrument-list-title">
        <strong>{label}</strong>
        <AvailabilityBadge availability={instrument.availability} connected={connected} />
      </span>
      <code>{instrument.instrument_id}</code>
      <dl>
        <div>
          <dt>Connection</dt>
          <dd>{connectionSummary(instrument.connection)}</dd>
        </div>
      </dl>
      {instrument.owner_id && (
        <span className="instrument-list-owner">
          {instrument.owner_kind === "run" ? "Run in progress" : "Interactive session active"}
        </span>
      )}
    </button>
  );
}

function InstrumentListMessage({
  icon,
  title,
  detail,
  error = false,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
  error?: boolean;
}) {
  return (
    <div className={`instrument-list-message ${error ? "error" : ""}`}>
      <span aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

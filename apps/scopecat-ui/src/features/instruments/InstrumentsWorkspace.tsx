import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Cable,
  CircleOff,
  LoaderCircle,
  RefreshCw,
  ServerCrash,
} from "lucide-react";
import type { InstrumentSessionLease, InstrumentView } from "../../api-contract";
import { errorMessage, formatDateTime, formatRelative } from "../../lib/presentation";
import { InstrumentConnectionDialog } from "./InstrumentConnectionDialog";
import { AvailabilityBadge, InstrumentInspector } from "./InstrumentInspector";
import {
  closeInstrumentSession,
  connectionSummary,
  createInstrumentOperationId,
  getActiveConfig,
  getInstruments,
  heartbeatInstrumentSession,
  openInstrumentSession,
  retryTransientInstrumentMutation,
} from "./instrument-api";

const EMPTY_INSTRUMENTS: InstrumentView[] = [];

export function InstrumentsWorkspace({ daemonUnavailable }: { daemonUnavailable: boolean }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string>();
  const [actor, setActor] = useState("local-operator");
  const [lease, setLease] = useState<InstrumentSessionLease>();
  const [sessionError, setSessionError] = useState<string>();
  const [configInstrumentId, setConfigInstrumentId] = useState<string>();
  const [closingSessionId, setClosingSessionId] = useState<string>();
  const leaseRef = useRef<InstrumentSessionLease | undefined>(undefined);
  const closingRef = useRef(false);
  const pendingSelectionRef = useRef<string | undefined>(undefined);
  const openAttemptRef = useRef<{ key: string; operationId: string } | undefined>(undefined);
  const closeOperationIdsRef = useRef<Record<string, string>>({});

  const instrumentsQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: ({ signal }) => getInstruments(signal),
    enabled: !daemonUnavailable,
  });
  const activeConfigQuery = useQuery({
    queryKey: ["config", "active"],
    queryFn: ({ signal }) => getActiveConfig(signal),
    enabled: !daemonUnavailable,
  });

  const instruments = instrumentsQuery.data?.items ?? EMPTY_INSTRUMENTS;
  const selected = instruments.find((instrument) => instrument.spec.id === selectedId);

  useEffect(() => {
    if (instruments.length === 0) {
      setSelectedId(undefined);
      return;
    }
    if (!selectedId || !instruments.some((instrument) => instrument.spec.id === selectedId)) {
      setSelectedId(instruments[0]?.spec.id);
    }
  }, [instruments, selectedId]);

  useEffect(() => {
    if (!configInstrumentId || !activeConfigQuery.isError) return;
    setSessionError(errorMessage(activeConfigQuery.error));
    setConfigInstrumentId(undefined);
  }, [activeConfigQuery.error, activeConfigQuery.isError, configInstrumentId]);

  useEffect(() => {
    leaseRef.current = lease;
  }, [lease]);

  useEffect(() => {
    const releaseOnExit = () => {
      const current = leaseRef.current;
      if (!current || closingRef.current) return;
      leaseRef.current = undefined;
      closingRef.current = true;
      void closeInstrumentSession(current, true).catch(() => {
        // Expiry quarantines the session for operator resolution when close cannot finish.
      });
    };
    window.addEventListener("beforeunload", releaseOnExit);
    return () => {
      window.removeEventListener("beforeunload", releaseOnExit);
      releaseOnExit();
    };
  }, []);

  useEffect(() => {
    if (!lease || closingSessionId === lease.session_id) return;
    let cancelled = false;
    const delay = Math.max(50, lease.heartbeat_interval_seconds * 1_000);
    const timer = window.setTimeout(() => {
      void heartbeatInstrumentSession(lease)
        .then((renewed) => {
          if (
            !cancelled &&
            leaseRef.current?.session_id === renewed.session_id &&
            !closingRef.current
          ) {
            setLease(renewed);
            setSessionError(undefined);
          }
        })
        .catch((cause) => {
          if (cancelled || leaseRef.current?.session_id !== lease.session_id) return;
          leaseRef.current = undefined;
          setLease(undefined);
          setSessionError(
            `${errorMessage(cause)} ${leaseExpiryAttentionMessage(lease.expires_at)}`,
          );
          void queryClient.invalidateQueries({ queryKey: ["instruments"] });
        });
    }, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [closingSessionId, lease, queryClient]);

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
      leaseRef.current = opened;
      setLease(opened);
      setSessionError(undefined);
      await queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: (cause) => setSessionError(errorMessage(cause)),
  });
  const closeMutation = useMutation({
    mutationFn: ({
      closingLease,
      operationId,
    }: {
      closingLease: InstrumentSessionLease;
      operationId: string;
    }) => closeInstrumentSession(closingLease, false, operationId),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (_, { closingLease }) => {
      delete closeOperationIdsRef.current[closingLease.session_id];
      if (leaseRef.current?.session_id === closingLease.session_id) {
        leaseRef.current = undefined;
        setLease(undefined);
      }
      const pendingSelection = pendingSelectionRef.current;
      pendingSelectionRef.current = undefined;
      if (pendingSelection) setSelectedId(pendingSelection);
      setSessionError(undefined);
    },
    onError: (cause, { closingLease }) => {
      pendingSelectionRef.current = undefined;
      setSessionError(
        `${errorMessage(cause)} ${leaseExpiryAttentionMessage(closingLease.expires_at)}`,
      );
    },
    onSettled: async () => {
      closingRef.current = false;
      setClosingSessionId(undefined);
      await queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });

  const selectInstrument = (instrumentId: string) => {
    openAttemptRef.current = undefined;
    connectMutation.reset();
    const current = leaseRef.current;
    if (current && !current.instrument_ids.includes(instrumentId)) {
      pendingSelectionRef.current = instrumentId;
      if (!closingRef.current) closeWithStableOperationId(current);
      return;
    }
    setSelectedId(instrumentId);
    setSessionError(undefined);
  };
  const closeCurrent = () => {
    const current = leaseRef.current;
    if (!current || closingRef.current) return;
    pendingSelectionRef.current = undefined;
    closeWithStableOperationId(current);
  };
  const loseCurrent = (message: string, expiresAt?: string) => {
    leaseRef.current = undefined;
    setLease(undefined);
    setSessionError(expiresAt ? `${message} ${leaseExpiryAttentionMessage(expiresAt)}` : message);
    void queryClient.invalidateQueries({ queryKey: ["instruments"] });
  };
  const connectCurrent = (instrumentId: string) => {
    const operator = actor.trim();
    const key = `${instrumentId}\u0000${operator}`;
    if (openAttemptRef.current?.key !== key) {
      openAttemptRef.current = {
        key,
        operationId: createInstrumentOperationId("open"),
      };
    }
    connectMutation.mutate({
      instrumentId,
      operator,
      operationId: openAttemptRef.current.operationId,
    });
  };
  const closeWithStableOperationId = (closingLease: InstrumentSessionLease) => {
    const operationId =
      closeOperationIdsRef.current[closingLease.session_id] ?? createInstrumentOperationId("close");
    closeOperationIdsRef.current[closingLease.session_id] = operationId;
    closingRef.current = true;
    setClosingSessionId(closingLease.session_id);
    setSessionError(undefined);
    closeMutation.mutate({ closingLease, operationId });
  };

  useEffect(() => {
    if (!lease) return;
    const leasedInstrument = instruments.find((instrument) =>
      lease.instrument_ids.includes(instrument.spec.id),
    );
    if (!leasedInstrument) return;
    const ownerChanged =
      leasedInstrument.availability === "active" &&
      (leasedInstrument.owner_kind !== "instrument_session" ||
        leasedInstrument.owner_id !== lease.session_id);
    if (leasedInstrument.availability === "quarantined" || ownerChanged) {
      loseCurrent(
        leasedInstrument.availability === "quarantined"
          ? "The daemon quarantined this instrument after an uncertain operation."
          : "The instrument lease is now owned by another run or session.",
        lease.expires_at,
      );
    }
    // Reconcile the local lease whenever a fresh canonical instrument view arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrumentsQuery.dataUpdatedAt, lease?.session_id]);

  return (
    <section className="instruments-workspace" aria-labelledby="instruments-heading">
      <header className="instruments-toolbar">
        <div>
          <span className="eyebrow">Direct hardware interaction</span>
          <h2 id="instruments-heading">Instruments</h2>
          <p>
            Inspect driver capabilities, then explicitly lease one device for direct interaction.
          </p>
        </div>
        <div className="instrument-config-identity">
          <span>Active configuration</span>
          {instrumentsQuery.data ? (
            <>
              <code>{instrumentsQuery.data.config_entry_id}</code>
              <small title={instrumentsQuery.data.config_content_hash}>
                {shortHash(instrumentsQuery.data.config_content_hash)}
              </small>
            </>
          ) : (
            <small>Waiting for daemon</small>
          )}
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
              detail="Reading the active configuration and current lease owners."
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
              detail="Publish an active configuration with at least one instrument."
            />
          ) : (
            <div className="instrument-list">
              {instruments.map((instrument) => (
                <InstrumentListItem
                  key={instrument.spec.id}
                  instrument={instrument}
                  selected={instrument.spec.id === selected?.spec.id}
                  connected={lease?.instrument_ids.includes(instrument.spec.id)}
                  onSelect={() => selectInstrument(instrument.spec.id)}
                />
              ))}
            </div>
          )}
        </aside>

        {selected ? (
          <InstrumentInspector
            key={selected.spec.id}
            instrument={selected}
            lease={lease}
            actor={actor}
            sessionError={sessionError}
            connectPending={
              connectMutation.isPending &&
              connectMutation.variables?.instrumentId === selected.spec.id
            }
            closePending={closeMutation.isPending}
            onActorChange={(nextActor) => {
              if (nextActor !== actor) {
                openAttemptRef.current = undefined;
                connectMutation.reset();
              }
              setActor(nextActor);
            }}
            onConnect={() => connectCurrent(selected.spec.id)}
            onClose={closeCurrent}
            onLeaseLost={loseCurrent}
            onEditConnection={() => {
              if (activeConfigQuery.isError) {
                setSessionError(errorMessage(activeConfigQuery.error));
              } else {
                setConfigInstrumentId(selected.spec.id);
              }
            }}
          />
        ) : (
          <div className="instrument-inspector no-selection">
            <InstrumentListMessage
              icon={<Cable />}
              title="Nothing selected"
              detail="Choose a configured instrument to inspect its driver contract."
            />
          </div>
        )}
      </div>

      {configInstrumentId && activeConfigQuery.data && (
        <InstrumentConnectionDialog
          key={`${configInstrumentId}-${activeConfigQuery.data.activation.generation}`}
          active={activeConfigQuery.data}
          instrumentId={configInstrumentId}
          onCancel={() => setConfigInstrumentId(undefined)}
          onPublished={async () => {
            setConfigInstrumentId(undefined);
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
  const label = instrument.description?.label ?? instrument.spec.id;
  return (
    <button
      type="button"
      className={`instrument-list-item ${selected ? "selected" : ""}`}
      aria-current={selected ? "true" : undefined}
      title={`Inspect instrument ${instrument.spec.id}`}
      onClick={onSelect}
    >
      <span className="instrument-list-title">
        <strong>{label}</strong>
        <AvailabilityBadge availability={instrument.availability} connected={connected} />
      </span>
      <code>{instrument.spec.id}</code>
      <dl>
        <div>
          <dt>Driver</dt>
          <dd>{instrument.spec.driver_id}</dd>
        </div>
        <div>
          <dt>Connection</dt>
          <dd>{connectionSummary(instrument.spec.connection)}</dd>
        </div>
      </dl>
      {instrument.owner_id && (
        <span className="instrument-list-owner">
          {instrument.owner_kind === "run" ? "Run" : "Session"} <code>{instrument.owner_id}</code>
          {instrument.owner_actor ? ` · ${instrument.owner_actor}` : ""}
          {instrument.expires_at ? ` · ${formatRelative(instrument.expires_at)}` : ""}
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

function shortHash(value: string): string {
  return value.length > 21 ? `${value.slice(0, 14)}…${value.slice(-6)}` : value;
}

function leaseExpiryAttentionMessage(expiresAt: string): string {
  return (
    `At the lease deadline (${formatDateTime(expiresAt)}), the session enters ` +
    "attention_required/quarantine; it is not released automatically. " +
    "An operator must resolve it before the instrument can be reused."
  );
}

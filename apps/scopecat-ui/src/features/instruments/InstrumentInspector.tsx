import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Cable,
  Check,
  CircleOff,
  Database,
  LoaderCircle,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Unplug,
} from "lucide-react";
import type {
  InstrumentCollectReceipt,
  InstrumentConfiguredDefaultsApplyReceipt,
  InstrumentInterface,
  InstrumentInvokeReceipt,
  InstrumentOperation,
  InstrumentProperty,
  InstrumentSession,
  InstrumentState,
  InstrumentStateValue,
  InstrumentView,
} from "../../api-contract";
import { ApiError } from "../../api";
import { errorMessage, formatRelative, titleCase } from "../../lib/presentation";
import {
  applyInstrumentState,
  applyInstrumentConfiguredDefaults,
  collectInstrumentAcquisition,
  acquisitionResultsForState,
  declaredAcquisitionResults,
  createInstrumentCommandId,
  instrumentAcquisitionReadiness,
  invokeInstrumentOperation,
  readInstrumentState,
  resolveInstrumentAttention,
  retryTransientInstrumentMutation,
  type InstrumentAcquisitionTarget,
  type InstrumentOperationArgument,
  type InstrumentOperationTarget,
  type StagedInstrumentProperty,
} from "./instrument-api";

interface DraftValue {
  raw: string | boolean;
  unit?: string;
  value?: InstrumentStateValue;
}

type DiscriminatedStateSpec = NonNullable<InstrumentInterface["state"]>;
type DiscriminatedStateCase = DiscriminatedStateSpec["cases"][number];

export function InstrumentInspector({
  instrument,
  session,
  actor,
  sessionError,
  connectPending,
  closePending,
  editConnectionPending,
  onActorChange,
  onConnect,
  onClose,
  onSessionLost,
  onDisconnectOwner,
  onEditConnection,
}: {
  instrument: InstrumentView;
  session?: InstrumentSession;
  actor: string;
  sessionError?: string;
  connectPending: boolean;
  closePending: boolean;
  editConnectionPending: boolean;
  onActorChange: (actor: string) => void;
  onConnect: () => void;
  onClose: () => void;
  onSessionLost: (message: string) => void;
  onDisconnectOwner: () => void;
  onEditConnection: () => void;
}) {
  const queryClient = useQueryClient();
  const instrumentId = instrument.instrument_id;
  const connected = session?.instrument_ids.includes(instrumentId) ?? false;
  const connectionEditable = instrument.connection.kind === "tcpip_socket";
  const description =
    session?.descriptions.find((candidate) => candidate.instrument_id === instrumentId) ??
    instrument.description ??
    undefined;
  const [state, setState] = useState<InstrumentState>();
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const [applyResult, setApplyResult] = useState<string>();
  const [configuredDefaultsResult, setConfiguredDefaultsResult] =
    useState<InstrumentConfiguredDefaultsApplyReceipt>();
  const [collectResults, setCollectResults] = useState<Record<string, InstrumentCollectReceipt>>(
    {},
  );
  const [invokeResults, setInvokeResults] = useState<Record<string, InstrumentInvokeReceipt>>({});
  const applyCommandIdRef = useRef<string | undefined>(undefined);
  const configuredDefaultsOperationIdRef = useRef<string | undefined>(undefined);
  const collectCommandIdsRef = useRef<Record<string, string>>({});
  const invokeCommandIdsRef = useRef<Record<string, string>>({});

  useEffect(() => {
    if (connected) return;
    applyCommandIdRef.current = undefined;
    configuredDefaultsOperationIdRef.current = undefined;
    collectCommandIdsRef.current = {};
    invokeCommandIdsRef.current = {};
    setState(undefined);
    setDrafts({});
    setApplyResult(undefined);
    setConfiguredDefaultsResult(undefined);
    setCollectResults({});
    setInvokeResults({});
  }, [connected]);

  const hasConfiguredDefaults =
    session?.configured_default_instrument_ids.includes(instrumentId) ?? false;

  const readMutation = useMutation({
    mutationFn: () => readInstrumentState(requireSession(session), instrumentId),
    onSuccess: (snapshot) => {
      applyCommandIdRef.current = undefined;
      configuredDefaultsOperationIdRef.current = undefined;
      collectCommandIdsRef.current = {};
      invokeCommandIdsRef.current = {};
      setState(snapshot);
      setDrafts({});
      setApplyResult(undefined);
      setConfiguredDefaultsResult(undefined);
      setCollectResults({});
      setInvokeResults({});
    },
  });
  useEffect(() => {
    if (connected && session) readMutation.mutate();
    // Only a newly opened session should trigger fresh observation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, instrumentId, session?.session_id]);
  const visiblePropertyKeys = useMemo(
    () => instrumentVisiblePropertyKeys(description?.interfaces ?? [], state, drafts),
    [description?.interfaces, drafts, state],
  );
  const visibleDrafts = useMemo(
    () => filterDrafts(drafts, visiblePropertyKeys),
    [drafts, visiblePropertyKeys],
  );
  const stagedProperties = useMemo(
    () => stagedInstrumentProperties(visibleDrafts),
    [visibleDrafts],
  );
  const stagedCount = Object.keys(visibleDrafts).length;
  const invalidDraft = Object.values(visibleDrafts).some((draft) => draft.value === undefined);
  useEffect(() => {
    if (!description) return;
    setDrafts((current) => {
      const visible = instrumentVisiblePropertyKeys(description.interfaces ?? [], state, current);
      return filterDrafts(current, visible);
    });
  }, [description, state]);
  const applyMutation = useMutation({
    mutationFn: ({
      properties,
      commandId,
    }: {
      properties: StagedInstrumentProperty[];
      commandId: string;
    }) => applyInstrumentState(requireSession(session), instrumentId, properties, commandId),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt) => {
      applyCommandIdRef.current = undefined;
      setApplyResult(receipt.status);
      if (receipt.state) setState(receipt.state);
      if (receipt.status === "applied") {
        collectCommandIdsRef.current = {};
        invokeCommandIdsRef.current = {};
        setCollectResults({});
        setInvokeResults({});
        setDrafts({});
      } else if (receipt.status === "unknown") {
        onSessionLost(
          "The apply result is unknown. The daemon quarantined this session for operator review.",
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });
  const configuredDefaultsMutation = useMutation({
    mutationFn: ({ operationId }: { operationId: string }) =>
      applyInstrumentConfiguredDefaults(requireSession(session), instrumentId, operationId),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt) => {
      configuredDefaultsOperationIdRef.current = undefined;
      setConfiguredDefaultsResult(receipt);
      if (receipt.state) setState(receipt.state);
      if (receipt.status === "applied" || receipt.status === "unchanged") {
        applyCommandIdRef.current = undefined;
        collectCommandIdsRef.current = {};
        invokeCommandIdsRef.current = {};
        setApplyResult(undefined);
        setDrafts({});
        setCollectResults({});
        setInvokeResults({});
      }
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: async (cause) => {
      await queryClient.invalidateQueries({ queryKey: ["instruments"] });
      if (!(cause instanceof ApiError) || ![404, 409].includes(cause.status ?? 0)) {
        return;
      }
      const canonical = queryClient
        .getQueryData<{ items: InstrumentView[] }>(["instruments"])
        ?.items.find((candidate) => candidate.instrument_id === instrumentId);
      const stillOwned =
        canonical?.availability === "active" &&
        canonical.owner_kind === "instrument_session" &&
        canonical.owner_id === session?.session_id;
      if (canonical && !stillOwned) {
        onSessionLost(
          canonical?.availability === "quarantined"
            ? "The daemon quarantined this instrument while applying configured defaults."
            : "The interactive session ended while applying configured defaults.",
        );
      }
    },
  });
  const collectMutation = useMutation({
    mutationFn: ({
      target,
      stateSnapshot,
      commandId,
    }: {
      target: InstrumentAcquisitionTarget;
      stateSnapshot?: InstrumentState;
      commandId: string;
    }) =>
      collectInstrumentAcquisition(
        requireSession(session),
        instrumentId,
        target,
        stateSnapshot,
        commandId,
      ),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt, { target }) => {
      const key = acquisitionKey(target);
      delete collectCommandIdsRef.current[key];
      setCollectResults((current) => ({ ...current, [key]: receipt }));
      if (receipt.status === "unknown") {
        onSessionLost(
          "The collection result is unknown. The daemon quarantined this session for operator review.",
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });
  const invokeMutation = useMutation({
    mutationFn: ({
      target,
      operationArguments,
      commandId,
    }: {
      target: InstrumentOperationTarget;
      operationArguments: InstrumentOperationArgument[];
      commandId: string;
    }) =>
      invokeInstrumentOperation(
        requireSession(session),
        instrumentId,
        target,
        operationArguments,
        commandId,
      ),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt, { target }) => {
      const key = operationKey(target);
      delete invokeCommandIdsRef.current[key];
      setInvokeResults((current) => ({ ...current, [key]: receipt }));
      if (receipt.state) setState(receipt.state);
      if (receipt.status === "invoked") {
        collectCommandIdsRef.current = {};
        setCollectResults({});
      } else if (receipt.status === "unknown") {
        onSessionLost(
          "The operation result is unknown. The daemon quarantined this session for operator review.",
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });
  const resolveMutation = useMutation({
    mutationFn: () => {
      if (instrument.owner_kind !== "instrument_session" || !instrument.owner_id) {
        throw new Error("This attention state is not owned by an interactive session.");
      }
      return resolveInstrumentAttention(instrument.owner_id);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });

  const stage = (
    interfaceId: string,
    componentPath: string[],
    property: InstrumentProperty,
    discriminatedState: DiscriminatedStateSpec | undefined,
    draft?: DraftValue,
  ) => {
    const key = propertyKey(interfaceId, componentPath, property.id);
    applyCommandIdRef.current = undefined;
    setDrafts((current) => {
      const next = { ...current };
      if (draft === undefined) delete next[key];
      else next[key] = draft;
      if (discriminatedState && property.id === discriminatedState.discriminator_property_id) {
        const activeCase = effectiveStateCase(
          discriminatedState,
          draft?.value,
          stateValue(
            state,
            interfaceId,
            componentPath,
            discriminatedState.discriminator_property_id,
          ),
        );
        const activePropertyIds = new Set(activeCase?.property_ids ?? []);
        for (const stateCase of discriminatedState.cases) {
          for (const propertyId of stateCase.property_ids ?? []) {
            if (!activePropertyIds.has(propertyId)) {
              delete next[propertyKey(interfaceId, componentPath, propertyId)];
            }
          }
        }
      }
      return next;
    });
    setApplyResult(undefined);
    applyMutation.reset();
  };
  const applyStaged = () => {
    applyCommandIdRef.current ??= createInstrumentCommandId("apply");
    applyMutation.mutate({
      properties: stagedProperties,
      commandId: applyCommandIdRef.current,
    });
  };
  const resetStaged = () => {
    applyCommandIdRef.current = undefined;
    setDrafts({});
    applyMutation.reset();
  };
  const applyConfiguredDefaults = () => {
    configuredDefaultsOperationIdRef.current ??= createInstrumentCommandId("configured-defaults");
    configuredDefaultsMutation.mutate({
      operationId: configuredDefaultsOperationIdRef.current,
    });
  };
  const collectAcquisition = (target: InstrumentAcquisitionTarget) => {
    const key = acquisitionKey(target);
    const commandId = collectCommandIdsRef.current[key] ?? createInstrumentCommandId("collect");
    collectCommandIdsRef.current[key] = commandId;
    collectMutation.mutate({
      target,
      stateSnapshot: state,
      commandId,
    });
  };
  const invokeOperation = (
    target: InstrumentOperationTarget,
    operationArguments: InstrumentOperationArgument[],
  ) => {
    const key = operationKey(target);
    const commandId = invokeCommandIdsRef.current[key] ?? createInstrumentCommandId("invoke");
    invokeCommandIdsRef.current[key] = commandId;
    invokeMutation.mutate({ target, operationArguments, commandId });
  };
  const editOperation = (target: InstrumentOperationTarget) => {
    const key = operationKey(target);
    delete invokeCommandIdsRef.current[key];
    setInvokeResults((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
    invokeMutation.reset();
  };
  const interactionError =
    sessionError ??
    mutationError(readMutation.error) ??
    mutationError(applyMutation.error) ??
    mutationError(configuredDefaultsMutation.error) ??
    mutationError(collectMutation.error) ??
    mutationError(invokeMutation.error) ??
    mutationError(resolveMutation.error);
  const interactionPending =
    readMutation.isPending ||
    applyMutation.isPending ||
    configuredDefaultsMutation.isPending ||
    collectMutation.isPending ||
    invokeMutation.isPending;
  const interactionDisabled = closePending || interactionPending;
  const configuredDefaultsDisabled =
    interactionDisabled || stagedCount > 0 || resolveMutation.isPending;
  const configuredDefaultsDisabledReason =
    stagedCount > 0
      ? "Apply or reset staged properties first"
      : configuredDefaultsDisabled
        ? "Wait for the current instrument interaction to finish"
        : undefined;

  return (
    <section className="instrument-inspector" aria-live="polite">
      <header className="instrument-inspector-header">
        <div>
          <div className="instrument-title-row">
            <h2>{description?.label ?? instrumentId}</h2>
            <AvailabilityBadge availability={instrument.availability} connected={connected} />
          </div>
          <code>{instrumentId}</code>
          {description?.description && <p>{description.description}</p>}
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={onEditConnection}
          disabled={
            !connectionEditable ||
            connected ||
            editConnectionPending ||
            instrument.availability === "active" ||
            instrument.availability === "quarantined"
          }
          title={
            !connectionEditable
              ? "Virtual connections have no editable endpoint"
              : connected
                ? "Disconnect before changing the immutable config"
                : instrument.availability === "active" || instrument.availability === "quarantined"
                  ? "Resolve the current owner before changing the immutable config"
                  : undefined
          }
        >
          {editConnectionPending ? (
            <LoaderCircle className="spin" size={14} />
          ) : (
            <Pencil size={14} />
          )}
          {editConnectionPending ? "Loading configuration" : "Edit connection"}
        </button>
      </header>

      <InstrumentSessionPanel
        instrument={instrument}
        session={session}
        connected={connected}
        actor={actor}
        connectPending={connectPending}
        closePending={closePending}
        interactionPending={interactionPending}
        refreshPending={readMutation.isPending}
        configuredDefaultsVisible={hasConfiguredDefaults}
        configuredDefaultsPending={configuredDefaultsMutation.isPending}
        configuredDefaultsDisabled={configuredDefaultsDisabled}
        configuredDefaultsDisabledReason={configuredDefaultsDisabledReason}
        resolvePending={resolveMutation.isPending}
        onActorChange={onActorChange}
        onConnect={onConnect}
        onClose={onClose}
        onDisconnectOwner={onDisconnectOwner}
        onRefresh={() => readMutation.mutate()}
        onApplyConfiguredDefaults={applyConfiguredDefaults}
        onResolve={() => resolveMutation.mutate()}
      />

      {interactionError && (
        <div className="instrument-inline-error" role="alert">
          <AlertTriangle size={15} />
          {interactionError}
        </div>
      )}

      {configuredDefaultsResult && (
        <p className={`instrument-receipt ${configuredDefaultsResult.status}`} role="status">
          {configuredDefaultsReceiptMessage(configuredDefaultsResult)}
        </p>
      )}

      {(instrument.problems ?? []).length > 0 && (
        <div className="instrument-problems" role="status">
          <strong>Driver is unavailable</strong>
          {instrument.problems.map((problem, index) => (
            <p key={`${problem.code}-${index}`}>{problem.message}</p>
          ))}
        </div>
      )}

      {description ? (
        <>
          <div className="interface-heading">
            <div>
              <span className="eyebrow">Driver contract</span>
              <h3>Interfaces</h3>
            </div>
          </div>

          {(description.interfaces ?? []).length > 0 ? (
            <div className="interface-list">
              {(description.interfaces ?? []).map((instrumentInterface) => (
                <InterfaceCard
                  key={instrumentInterface.id}
                  instrumentInterface={instrumentInterface}
                  connected={connected}
                  interactionDisabled={interactionDisabled}
                  state={state}
                  drafts={drafts}
                  collectResults={collectResults}
                  invokeResults={invokeResults}
                  collectingTarget={
                    collectMutation.isPending ? collectMutation.variables?.target : undefined
                  }
                  invokingTarget={
                    invokeMutation.isPending ? invokeMutation.variables?.target : undefined
                  }
                  onStage={(componentPath, property, discriminatedState, draft) =>
                    stage(
                      instrumentInterface.id,
                      componentPath,
                      property,
                      discriminatedState,
                      draft,
                    )
                  }
                  onCollect={(target) => collectAcquisition(target)}
                  onInvoke={(target, operationArguments) =>
                    invokeOperation(target, operationArguments)
                  }
                  onOperationEdit={editOperation}
                />
              ))}
            </div>
          ) : (
            <InspectorEmpty
              icon={<CircleOff />}
              title="No interactive interfaces"
              detail="This driver does not declare GUI-safe properties, operations, or acquisitions."
            />
          )}

          {connected && stagedCount > 0 && (
            <div className="staged-apply-bar">
              <div>
                <strong>
                  {stagedCount} staged {stagedCount === 1 ? "property" : "properties"}
                </strong>
                <small>Values remain local until you apply the complete staged change once.</small>
              </div>
              <button
                type="button"
                className="secondary-button"
                onClick={resetStaged}
                disabled={applyMutation.isPending}
              >
                <RotateCcw size={14} />
                Reset
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={applyStaged}
                disabled={interactionDisabled || invalidDraft || stagedProperties.length === 0}
              >
                {applyMutation.isPending ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <Check size={14} />
                )}
                Apply staged
              </button>
            </div>
          )}
          {applyResult && (
            <p className={`instrument-receipt ${applyResult}`}>
              Apply receipt: {titleCase(applyResult)}
            </p>
          )}
        </>
      ) : (
        <InspectorEmpty
          icon={<CircleOff />}
          title="Driver description unavailable"
          detail="Review the listed provider problem or edit this instrument’s connection configuration."
        />
      )}
    </section>
  );
}

function InstrumentSessionPanel({
  instrument,
  session,
  connected,
  actor,
  connectPending,
  closePending,
  interactionPending,
  refreshPending,
  configuredDefaultsVisible,
  configuredDefaultsPending,
  configuredDefaultsDisabled,
  configuredDefaultsDisabledReason,
  resolvePending,
  onActorChange,
  onConnect,
  onClose,
  onDisconnectOwner,
  onRefresh,
  onApplyConfiguredDefaults,
  onResolve,
}: {
  instrument: InstrumentView;
  session?: InstrumentSession;
  connected: boolean;
  actor: string;
  connectPending: boolean;
  closePending: boolean;
  interactionPending: boolean;
  refreshPending: boolean;
  configuredDefaultsVisible: boolean;
  configuredDefaultsPending: boolean;
  configuredDefaultsDisabled: boolean;
  configuredDefaultsDisabledReason?: string;
  resolvePending: boolean;
  onActorChange: (actor: string) => void;
  onConnect: () => void;
  onClose: () => void;
  onDisconnectOwner: () => void;
  onRefresh: () => void;
  onApplyConfiguredDefaults: () => void;
  onResolve: () => void;
}) {
  if (connected && session) {
    return (
      <div className="instrument-session-panel connected">
        <div className="session-summary">
          <span aria-hidden="true">
            <Cable size={16} />
          </span>
          <div>
            <strong>Interactive session connected</strong>
            <small>
              {session.actor} · opened {formatRelative(session.opened_at)}
            </small>
          </div>
        </div>
        <div className="session-actions">
          {configuredDefaultsVisible && (
            <button
              type="button"
              className="secondary-button"
              onClick={onApplyConfiguredDefaults}
              disabled={configuredDefaultsDisabled}
              title={configuredDefaultsDisabledReason}
            >
              {configuredDefaultsPending ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <RotateCcw size={14} />
              )}
              Apply configured defaults
            </button>
          )}
          <button
            type="button"
            className="secondary-button"
            onClick={onRefresh}
            disabled={interactionPending || closePending}
            title={
              interactionPending
                ? "Wait for the current instrument interaction to finish"
                : undefined
            }
          >
            <RefreshCw className={refreshPending ? "spin" : undefined} size={14} />
            Refresh state
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={onClose}
            disabled={closePending || interactionPending}
            title={
              interactionPending
                ? "Wait for the current instrument interaction to finish"
                : undefined
            }
          >
            {closePending ? <LoaderCircle className="spin" size={14} /> : <Unplug size={14} />}
            Disconnect
          </button>
        </div>
      </div>
    );
  }

  if (instrument.availability === "quarantined") {
    const canResolve =
      instrument.owner_kind === "instrument_session" && Boolean(instrument.owner_id);
    return (
      <div className="instrument-attention-panel">
        <ShieldAlert size={19} aria-hidden="true" />
        <div>
          <strong>Operator resolution required</strong>
          <p>The previous operation left hardware state uncertain. Automatic reuse is blocked.</p>
          <OwnerDescription instrument={instrument} />
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={onResolve}
          disabled={!canResolve || resolvePending}
          title={
            canResolve
              ? "Acknowledge the quarantined interactive session and release it"
              : "Resolve this owner from its run workflow"
          }
        >
          {resolvePending ? <LoaderCircle className="spin" size={14} /> : <ShieldAlert size={14} />}
          Resolve quarantine
        </button>
      </div>
    );
  }

  if (instrument.availability === "active") {
    const canDisconnectSession =
      instrument.owner_kind === "instrument_session" && Boolean(instrument.owner_id);
    return (
      <div className="instrument-busy-panel">
        <Database size={18} aria-hidden="true" />
        <div>
          <strong>Read-only while owned</strong>
          <p>Another run or interactive session owns this instrument.</p>
          <OwnerDescription instrument={instrument} />
        </div>
        {canDisconnectSession && (
          <button
            type="button"
            className="secondary-button"
            onClick={onDisconnectOwner}
            disabled={closePending}
            title="Disconnect this daemon-owned interactive session"
          >
            {closePending ? <LoaderCircle className="spin" size={14} /> : <Unplug size={14} />}
            Disconnect session
          </button>
        )}
      </div>
    );
  }

  if (instrument.availability === "unavailable") {
    return (
      <div className="instrument-busy-panel unavailable">
        <CircleOff size={18} aria-hidden="true" />
        <div>
          <strong>Connection unavailable</strong>
          <p>Fix the provider or connection configuration before opening a session.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="instrument-session-panel">
      <div className="connect-prompt">
        <strong>Connect only when you are ready to interact</strong>
        <small>
          Opening a session gives the daemon exclusive ownership. Selecting this instrument never
          connects it.
        </small>
      </div>
      <label className="instrument-actor-field">
        <span>Actor</span>
        <input
          value={actor}
          onChange={(event) => onActorChange(event.target.value)}
          aria-label="Instrument session actor"
        />
      </label>
      <button
        type="button"
        className="primary-button"
        onClick={onConnect}
        disabled={connectPending || !actor.trim()}
      >
        {connectPending ? <LoaderCircle className="spin" size={14} /> : <Cable size={14} />}
        Connect
      </button>
    </div>
  );
}

function OwnerDescription({ instrument }: { instrument: InstrumentView }) {
  const ownerKind = instrument.owner_kind === "run" ? "Run" : "Interactive session";
  return (
    <dl className="instrument-owner">
      <div>
        <dt>Owner</dt>
        <dd>
          {ownerKind}
          {instrument.owner_kind === "run" && instrument.owner_id && (
            <>
              {" "}
              <code>{instrument.owner_id}</code>
            </>
          )}
        </dd>
      </div>
      {instrument.owner_actor && (
        <div>
          <dt>Actor</dt>
          <dd>{instrument.owner_actor}</dd>
        </div>
      )}
    </dl>
  );
}

function InterfaceCard({
  instrumentInterface,
  connected,
  state,
  drafts,
  collectResults,
  invokeResults,
  collectingTarget,
  invokingTarget,
  interactionDisabled,
  onStage,
  onCollect,
  onInvoke,
  onOperationEdit,
}: {
  instrumentInterface: InstrumentInterface;
  connected: boolean;
  state?: InstrumentState;
  drafts: Record<string, DraftValue>;
  collectResults: Record<string, InstrumentCollectReceipt>;
  invokeResults: Record<string, InstrumentInvokeReceipt>;
  collectingTarget?: InstrumentAcquisitionTarget;
  invokingTarget?: InstrumentOperationTarget;
  interactionDisabled: boolean;
  onStage: (
    componentPath: string[],
    property: InstrumentProperty,
    discriminatedState: DiscriminatedStateSpec | undefined,
    draft?: DraftValue,
  ) => void;
  onCollect: (target: InstrumentAcquisitionTarget) => void;
  onInvoke: (
    target: InstrumentOperationTarget,
    operationArguments: InstrumentOperationArgument[],
  ) => void;
  onOperationEdit: (target: InstrumentOperationTarget) => void;
}) {
  return (
    <article className="interface-card">
      <header>
        <div>
          <h4>{instrumentInterface.label ?? interfaceFallbackLabel(instrumentInterface.id)}</h4>
          {instrumentInterface.description && <p>{instrumentInterface.description}</p>}
        </div>
      </header>

      <InterfaceEndpoint
        interfaceId={instrumentInterface.id}
        componentPath={[]}
        member={instrumentInterface}
        connected={connected}
        state={state}
        drafts={drafts}
        collectResults={collectResults}
        invokeResults={invokeResults}
        collectingTarget={collectingTarget}
        invokingTarget={invokingTarget}
        interactionDisabled={interactionDisabled}
        onStage={onStage}
        onCollect={onCollect}
        onInvoke={onInvoke}
        onOperationEdit={onOperationEdit}
      />
    </article>
  );
}

type InterfaceMember = Pick<
  InstrumentInterface,
  "label" | "description" | "properties" | "state" | "operations" | "acquisitions" | "components"
>;

function InterfaceEndpoint({
  interfaceId,
  componentPath,
  member,
  connected,
  state,
  drafts,
  collectResults,
  invokeResults,
  collectingTarget,
  invokingTarget,
  interactionDisabled,
  onStage,
  onCollect,
  onInvoke,
  onOperationEdit,
}: {
  interfaceId: string;
  componentPath: string[];
  member: InterfaceMember;
  connected: boolean;
  state?: InstrumentState;
  drafts: Record<string, DraftValue>;
  collectResults: Record<string, InstrumentCollectReceipt>;
  invokeResults: Record<string, InstrumentInvokeReceipt>;
  collectingTarget?: InstrumentAcquisitionTarget;
  invokingTarget?: InstrumentOperationTarget;
  interactionDisabled: boolean;
  onStage: (
    componentPath: string[],
    property: InstrumentProperty,
    discriminatedState: DiscriminatedStateSpec | undefined,
    draft?: DraftValue,
  ) => void;
  onCollect: (target: InstrumentAcquisitionTarget) => void;
  onInvoke: (
    target: InstrumentOperationTarget,
    operationArguments: InstrumentOperationArgument[],
  ) => void;
  onOperationEdit: (target: InstrumentOperationTarget) => void;
}) {
  const properties = visibleMemberProperties(member, interfaceId, componentPath, state, drafts);
  const hasLocalControls =
    properties.length > 0 ||
    (member.operations ?? []).length > 0 ||
    (member.acquisitions ?? []).length > 0;
  return (
    <>
      {hasLocalControls && (
        <section className={componentPath.length > 0 ? "interface-component" : undefined}>
          {componentPath.length > 0 && (
            <header>
              <h5>{member.label ?? titleCase(componentPath.at(-1) ?? "")}</h5>
              <small>{componentPath.map(titleCase).join(" / ")}</small>
              {member.description && <p>{member.description}</p>}
            </header>
          )}

          {properties.length > 0 && (
            <div className="interface-properties">
              {properties.map((property) => {
                const key = propertyKey(interfaceId, componentPath, property.id);
                return (
                  <PropertyEditor
                    key={property.id}
                    property={property}
                    currentValue={stateValue(state, interfaceId, componentPath, property.id)}
                    draft={drafts[key]}
                    editable={connected && !interactionDisabled && property.access !== "read_only"}
                    onChange={(draft) =>
                      onStage(componentPath, property, member.state ?? undefined, draft)
                    }
                  />
                );
              })}
            </div>
          )}

          {(member.operations ?? []).length > 0 && (
            <div className="operation-list">
              {(member.operations ?? []).map((operation) => {
                const target = { interfaceId, componentPath, operation };
                const key = operationKey(target);
                return (
                  <OperationControl
                    key={operation.id}
                    target={target}
                    connected={connected}
                    result={invokeResults[key]}
                    invoking={invokingTarget !== undefined && operationKey(invokingTarget) === key}
                    interactionDisabled={interactionDisabled}
                    onInvoke={(operationArguments) => onInvoke(target, operationArguments)}
                    onEdit={() => onOperationEdit(target)}
                  />
                );
              })}
            </div>
          )}

          {(member.acquisitions ?? []).length > 0 && (
            <div className="acquisition-list">
              {(member.acquisitions ?? []).map((acquisition) => {
                const target = { interfaceId, componentPath, acquisition };
                const key = acquisitionKey(target);
                return (
                  <AcquisitionControl
                    key={acquisition.id}
                    target={target}
                    connected={connected}
                    state={state}
                    result={collectResults[key]}
                    interactionDisabled={interactionDisabled}
                    collecting={
                      collectingTarget !== undefined && acquisitionKey(collectingTarget) === key
                    }
                    onCollect={() => onCollect(target)}
                  />
                );
              })}
            </div>
          )}
        </section>
      )}

      {(member.components ?? []).map((child) => (
        <InterfaceEndpoint
          key={child.id}
          interfaceId={interfaceId}
          componentPath={[...componentPath, child.id]}
          member={child}
          connected={connected}
          state={state}
          drafts={drafts}
          collectResults={collectResults}
          invokeResults={invokeResults}
          collectingTarget={collectingTarget}
          invokingTarget={invokingTarget}
          interactionDisabled={interactionDisabled}
          onStage={onStage}
          onCollect={onCollect}
          onInvoke={onInvoke}
          onOperationEdit={onOperationEdit}
        />
      ))}
    </>
  );
}

function OperationControl({
  target,
  connected,
  result,
  invoking,
  interactionDisabled,
  onInvoke,
  onEdit,
}: {
  target: InstrumentOperationTarget;
  connected: boolean;
  result?: InstrumentInvokeReceipt;
  invoking: boolean;
  interactionDisabled: boolean;
  onInvoke: (operationArguments: InstrumentOperationArgument[]) => void;
  onEdit: () => void;
}) {
  const operation = target.operation;
  const argumentSpecs = operation.arguments ?? [];
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const payloadUnsupported = argumentSpecs.some(
    (argument) => argument.value_type.type === "payload",
  );
  const operationArguments = argumentSpecs.flatMap((argument) => {
    const value = drafts[argument.id]?.value;
    return value === undefined ? [] : [{ id: argument.id, value }];
  });
  const invalid = payloadUnsupported || operationArguments.length !== argumentSpecs.length;
  const label = operation.label ?? titleCase(operation.id);

  const edit = (argumentId: string, draft?: DraftValue) => {
    setDrafts((current) => {
      const next = { ...current };
      if (draft === undefined) delete next[argumentId];
      else next[argumentId] = draft;
      return next;
    });
    onEdit();
  };

  return (
    <section className="operation-control">
      <header>
        <div>
          <strong>{label}</strong>
          {operation.description && <p>{operation.description}</p>}
        </div>
        <button
          type="button"
          className="secondary-button"
          aria-label={`Invoke ${label}`}
          onClick={() => onInvoke(operationArguments)}
          disabled={!connected || interactionDisabled || invalid}
          title={
            !connected
              ? "Connect before invoking"
              : interactionDisabled
                ? "Wait for the current instrument interaction to finish"
                : payloadUnsupported
                  ? "Payload arguments cannot be encoded in the GUI"
                  : invalid
                    ? "Fill every operation argument before invoking"
                    : undefined
          }
        >
          {invoking ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />}
          Invoke
        </button>
      </header>
      {argumentSpecs.length > 0 && (
        <div className="operation-arguments">
          {argumentSpecs.map((argument) => (
            <OperationArgumentEditor
              key={argument.id}
              argument={argument}
              draft={drafts[argument.id]}
              editable={connected && !interactionDisabled}
              onChange={(draft) => edit(argument.id, draft)}
            />
          ))}
        </div>
      )}
      {payloadUnsupported && (
        <small className="operation-payload-warning">
          Payload arguments require an encoded command payload and are not supported in the GUI.
        </small>
      )}
      {result && (
        <p className={`instrument-receipt ${result.status}`}>
          Invoke receipt: {titleCase(result.status)}
        </p>
      )}
    </section>
  );
}

function OperationArgumentEditor({
  argument,
  draft,
  editable,
  onChange,
}: {
  argument: NonNullable<InstrumentOperation["arguments"]>[number];
  draft?: DraftValue;
  editable: boolean;
  onChange: (draft?: DraftValue) => void;
}) {
  const type = argument.value_type;
  const label = argument.label ?? titleCase(argument.id);
  const raw = draft?.raw ?? "";
  return (
    <label className="operation-argument">
      <span className="property-label">
        <span>
          <strong>{label}</strong>
        </span>
        <small>Argument</small>
      </span>
      {type.type === "bool" ? (
        <select
          value={typeof raw === "boolean" ? String(raw) : ""}
          disabled={!editable}
          onChange={(event) => {
            const value = event.target.value === "true";
            onChange({ raw: value, value });
          }}
        >
          <option value="" disabled>
            Select…
          </option>
          <option value="true">On</option>
          <option value="false">Off</option>
        </select>
      ) : type.type === "string" && type.choices ? (
        <select
          value={typeof raw === "string" ? raw : ""}
          disabled={!editable}
          onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
        >
          <option value="" disabled>
            Select…
          </option>
          {type.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : type.type === "int" || type.type === "float" || type.type === "quantity" ? (
        <span className={`number-unit-editor ${type.type === "quantity" ? "" : "number-only"}`}>
          <input
            type="number"
            step={type.type === "int" ? 1 : "any"}
            min={type.minimum ?? undefined}
            max={type.maximum ?? undefined}
            value={typeof raw === "string" ? raw : ""}
            placeholder={editable ? "Enter value" : "—"}
            disabled={!editable}
            aria-invalid={draft !== undefined && draft.value === undefined}
            onChange={(event) =>
              onChange(operationArgumentDraft(type, event.target.value, draft?.unit))
            }
          />
          {type.type === "quantity" &&
            (type.unit ? (
              <span>{type.unit}</span>
            ) : (
              <input
                className="operation-unit-input"
                type="text"
                aria-label={`${label} unit`}
                value={draft?.unit ?? ""}
                placeholder="Unit"
                disabled={!editable}
                onChange={(event) =>
                  onChange(
                    operationArgumentDraft(
                      type,
                      typeof raw === "string" ? raw : "",
                      event.target.value,
                    ),
                  )
                }
              />
            ))}
        </span>
      ) : type.type === "string" ? (
        <input
          type="text"
          value={typeof raw === "string" ? raw : ""}
          placeholder={editable ? "Enter value" : "—"}
          disabled={!editable}
          onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
        />
      ) : (
        <input type="text" value="Payload encoding unavailable in GUI" disabled />
      )}
      {argument.description && (
        <small className="property-description">{argument.description}</small>
      )}
      {draft && (
        <button type="button" className="property-reset" onClick={() => onChange()}>
          Clear argument
        </button>
      )}
    </label>
  );
}

function AcquisitionControl({
  target,
  connected,
  state,
  result,
  collecting,
  interactionDisabled,
  onCollect,
}: {
  target: InstrumentAcquisitionTarget;
  connected: boolean;
  state?: InstrumentState;
  result?: InstrumentCollectReceipt;
  collecting: boolean;
  interactionDisabled: boolean;
  onCollect: () => void;
}) {
  const acquisition = target.acquisition;
  const selection = acquisitionResultsForState(acquisition, state);
  const results = selection.ready ? selection.results : [];
  const hasDeclaredResults = declaredAcquisitionResults(acquisition).length > 0;
  const readiness = instrumentAcquisitionReadiness(target, state);
  const blocked = !readiness.ready;
  const reasonId = domId("collect-reason", acquisitionKey(target));
  return (
    <section className="acquisition-control">
      <header>
        <div>
          <strong>{acquisition.label ?? titleCase(acquisition.id)}</strong>
          {acquisition.description && <p>{acquisition.description}</p>}
        </div>
        {hasDeclaredResults && (
          <div className="acquisition-collect-action">
            <button
              type="button"
              className="secondary-button"
              onClick={onCollect}
              disabled={!connected || interactionDisabled || blocked}
              aria-describedby={connected && !interactionDisabled && blocked ? reasonId : undefined}
              title={
                !connected
                  ? "Connect before collecting"
                  : interactionDisabled
                    ? "Wait for the current instrument interaction to finish"
                    : blocked
                      ? readiness.reason
                      : undefined
              }
            >
              {collecting ? <LoaderCircle className="spin" size={14} /> : <Database size={14} />}
              Collect
            </button>
            {connected && blocked && (
              <small id={reasonId} className="collection-blocked-reason">
                <AlertTriangle size={12} aria-hidden="true" />
                {readiness.reason}
              </small>
            )}
          </div>
        )}
      </header>
      {results.length > 0 && (
        <div className="acquisition-results">
          <span>Results</span>
          {results.map((acquisitionResult) => (
            <span key={acquisitionResult.id} className="result-chip">
              {acquisitionResult.label ?? titleCase(acquisitionResult.id)}
              <small>
                {acquisitionResult.dtype}
                {acquisitionResult.unit ? ` · ${acquisitionResult.unit}` : ""}
              </small>
            </span>
          ))}
        </div>
      )}
      {result && <CollectPreview receipt={result} />}
    </section>
  );
}

function PropertyEditor({
  property,
  currentValue,
  draft,
  editable,
  onChange,
}: {
  property: InstrumentProperty;
  currentValue?: InstrumentStateValue;
  draft?: DraftValue;
  editable: boolean;
  onChange: (draft?: DraftValue) => void;
}) {
  const type = property.value_type;
  const value = draft?.raw ?? inputValue(currentValue, type.type);
  const dirty = draft !== undefined;
  return (
    <label className={`interface-property ${dirty ? "staged" : ""}`}>
      <span className="property-label">
        <span>
          <strong>{property.label ?? titleCase(property.id)}</strong>
        </span>
        <small>{accessLabel(property.access)}</small>
      </span>
      {type.type === "bool" ? (
        <span className="boolean-editor">
          <input
            type="checkbox"
            checked={typeof value === "boolean" ? value : false}
            disabled={!editable}
            onChange={(event) =>
              onChange({ raw: event.target.checked, value: event.target.checked })
            }
          />
          {typeof value === "boolean" ? (value ? "On" : "Off") : "Unknown"}
        </span>
      ) : type.type === "string" && type.choices ? (
        <select
          value={typeof value === "string" ? value : ""}
          disabled={!editable}
          onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
        >
          <option value="" disabled>
            Select…
          </option>
          {type.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : type.type === "int" || type.type === "float" || type.type === "quantity" ? (
        <span className="number-unit-editor">
          <input
            type="number"
            step={type.type === "int" ? 1 : "any"}
            min={type.minimum ?? undefined}
            max={type.maximum ?? undefined}
            value={typeof value === "string" || typeof value === "number" ? value : ""}
            placeholder={editable ? "Enter value" : "—"}
            disabled={!editable}
            aria-invalid={draft !== undefined && draft.value === undefined}
            onChange={(event) => {
              const raw = event.target.value;
              const number = Number(raw);
              const valid =
                raw.length > 0 &&
                Number.isFinite(number) &&
                (type.type !== "int" || Number.isInteger(number)) &&
                (type.minimum === null || type.minimum === undefined || number >= type.minimum) &&
                (type.maximum === null || type.maximum === undefined || number <= type.maximum);
              const unit =
                type.type === "quantity"
                  ? (type.unit ?? quantityValue(currentValue)?.unit)
                  : undefined;
              const typed =
                valid && type.type === "quantity" && unit
                  ? { value: number, unit }
                  : valid && type.type !== "quantity"
                    ? number
                    : undefined;
              onChange({ raw, value: typed });
            }}
          />
          {type.type === "quantity" && <span>{type.unit ?? "unit required"}</span>}
        </span>
      ) : type.type === "string" ? (
        <input
          type="text"
          value={typeof value === "string" ? value : ""}
          placeholder={editable ? "Enter value" : "—"}
          disabled={!editable}
          onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
        />
      ) : (
        <input type="text" value="Payload editing unavailable in GUI" disabled />
      )}
      {property.description && (
        <small className="property-description">{property.description}</small>
      )}
      {dirty && (
        <button type="button" className="property-reset" onClick={() => onChange()}>
          Reset staged value
        </button>
      )}
    </label>
  );
}

function CollectPreview({ receipt }: { receipt: InstrumentCollectReceipt }) {
  const trace = traceValues(receipt);
  return (
    <div className={`collect-preview ${receipt.status}`}>
      <div>
        <strong>Collect receipt: {titleCase(receipt.status)}</strong>
        {receipt.readback && (
          <small>{Object.keys(receipt.readback.values ?? {}).length} results returned</small>
        )}
      </div>
      {trace && <TracePreview values={trace} />}
      <details>
        <summary>JSON preview</summary>
        <pre>{JSON.stringify(receipt.readback ?? receipt, null, 2)}</pre>
      </details>
    </div>
  );
}

function TracePreview({ values }: { values: number[] }) {
  if (values.length === 0) return null;
  const width = 420;
  const height = 100;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = maximum - minimum || 1;
  const points = values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width;
      const y = height - ((value - minimum) / range) * (height - 8) - 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className="instrument-trace"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${values.length}-point trace preview`}
      preserveAspectRatio="none"
    >
      <polyline points={points} />
    </svg>
  );
}

function InspectorEmpty({
  icon,
  title,
  detail,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="instrument-inspector-empty">
      <span aria-hidden="true">{icon}</span>
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

export function AvailabilityBadge({
  availability,
  connected = false,
}: {
  availability: InstrumentView["availability"];
  connected?: boolean;
}) {
  const label = connected ? "Connected" : titleCase(availability);
  return (
    <span className={`instrument-availability ${connected ? "connected" : availability}`}>
      <span aria-hidden="true" />
      {label}
    </span>
  );
}

function instrumentVisiblePropertyKeys(
  interfaces: InstrumentInterface[],
  state: InstrumentState | undefined,
  drafts: Record<string, DraftValue>,
): Set<string> {
  const keys = new Set<string>();
  for (const instrumentInterface of interfaces) {
    collectVisiblePropertyKeys(
      keys,
      instrumentInterface.id,
      [],
      instrumentInterface,
      state,
      drafts,
    );
  }
  return keys;
}

function collectVisiblePropertyKeys(
  keys: Set<string>,
  interfaceId: string,
  componentPath: string[],
  member: InterfaceMember,
  state: InstrumentState | undefined,
  drafts: Record<string, DraftValue>,
): void {
  for (const property of visibleMemberProperties(
    member,
    interfaceId,
    componentPath,
    state,
    drafts,
  )) {
    keys.add(propertyKey(interfaceId, componentPath, property.id));
  }
  for (const child of member.components ?? []) {
    collectVisiblePropertyKeys(
      keys,
      interfaceId,
      [...componentPath, child.id],
      child,
      state,
      drafts,
    );
  }
}

function visibleMemberProperties(
  member: InterfaceMember,
  interfaceId: string,
  componentPath: string[],
  state: InstrumentState | undefined,
  drafts: Record<string, DraftValue>,
): InstrumentProperty[] {
  const properties = member.properties ?? [];
  const discriminatedState = member.state;
  if (!discriminatedState) return properties;
  const discriminatorId = discriminatedState.discriminator_property_id;
  const activeCase = effectiveStateCase(
    discriminatedState,
    drafts[propertyKey(interfaceId, componentPath, discriminatorId)]?.value,
    stateValue(state, interfaceId, componentPath, discriminatorId),
  );
  const registry = new Map(properties.map((property) => [property.id, property]));
  const orderedIds = [
    discriminatorId,
    ...(discriminatedState.common_property_ids ?? []),
    ...(activeCase?.property_ids ?? []),
  ];
  const seen = new Set<string>();
  return orderedIds.flatMap((propertyId) => {
    if (seen.has(propertyId)) return [];
    seen.add(propertyId);
    const property = registry.get(propertyId);
    return property ? [property] : [];
  });
}

function effectiveStateCase(
  discriminatedState: DiscriminatedStateSpec,
  draftValue: InstrumentStateValue | undefined,
  snapshotValue: InstrumentStateValue | undefined,
): DiscriminatedStateCase | undefined {
  return (
    stateCaseForValue(discriminatedState, draftValue) ??
    stateCaseForValue(discriminatedState, snapshotValue)
  );
}

function stateCaseForValue(
  discriminatedState: DiscriminatedStateSpec,
  value: InstrumentStateValue | undefined,
): DiscriminatedStateCase | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  return discriminatedState.cases.find((stateCase) => stateCase.value === value);
}

function filterDrafts(
  drafts: Record<string, DraftValue>,
  visiblePropertyKeys: Set<string>,
): Record<string, DraftValue> {
  const next: Record<string, DraftValue> = {};
  let changed = false;
  for (const [key, draft] of Object.entries(drafts)) {
    if (visiblePropertyKeys.has(key)) next[key] = draft;
    else changed = true;
  }
  return changed ? next : drafts;
}

function stateValue(
  state: InstrumentState | undefined,
  interfaceId: string,
  componentPath: string[],
  propertyId: string,
): InstrumentStateValue | undefined {
  return (state?.properties ?? []).find(
    (property) =>
      property.interface_id === interfaceId &&
      samePath(property.component_path ?? [], componentPath) &&
      property.property_id === propertyId,
  )?.value;
}

function inputValue(
  value: InstrumentStateValue | undefined,
  type: InstrumentProperty["value_type"]["type"],
): string | number | boolean {
  if (value === undefined) return "";
  if (type === "quantity") return quantityValue(value)?.value ?? "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  return "";
}

function quantityValue(
  value: InstrumentStateValue | undefined,
): { value: number; unit: string } | undefined {
  if (
    typeof value === "object" &&
    value !== null &&
    "value" in value &&
    "unit" in value &&
    typeof value.value === "number" &&
    typeof value.unit === "string"
  ) {
    return value;
  }
  return undefined;
}

type NumericOperationArgumentType = Extract<
  NonNullable<InstrumentOperation["arguments"]>[number]["value_type"],
  { type: "int" | "float" | "quantity" }
>;

function operationArgumentDraft(
  type: NumericOperationArgumentType,
  raw: string,
  unit?: string,
): DraftValue {
  const number = Number(raw);
  const valid =
    raw.length > 0 &&
    Number.isFinite(number) &&
    (type.type !== "int" || Number.isInteger(number)) &&
    (type.minimum === null || type.minimum === undefined || number >= type.minimum) &&
    (type.maximum === null || type.maximum === undefined || number <= type.maximum);
  const resolvedUnit = type.type === "quantity" ? (type.unit ?? unit?.trim()) : undefined;
  const value =
    valid && type.type === "quantity" && resolvedUnit
      ? { value: number, unit: resolvedUnit }
      : valid && type.type !== "quantity"
        ? number
        : undefined;
  return {
    raw,
    unit: type.type === "quantity" ? (type.unit ?? unit ?? "") : undefined,
    value,
  };
}

function stagedInstrumentProperties(
  drafts: Record<string, DraftValue>,
): StagedInstrumentProperty[] {
  return Object.entries(drafts).flatMap(([key, draft]) => {
    if (draft.value === undefined) return [];
    const segments = key.split("\u0000");
    return [
      {
        interfaceId: segments[0] ?? "",
        componentPath: segments.slice(1, -1),
        propertyId: segments.at(-1) ?? "",
        value: draft.value,
      },
    ];
  });
}

function propertyKey(interfaceId: string, componentPath: string[], propertyId: string): string {
  return [interfaceId, ...componentPath, propertyId].join("\u0000");
}

function acquisitionKey(target: InstrumentAcquisitionTarget): string {
  return [target.interfaceId, ...target.componentPath, target.acquisition.id].join("\u0000");
}

function operationKey(target: InstrumentOperationTarget): string {
  return [target.interfaceId, ...target.componentPath, target.operation.id].join("\u0000");
}

function accessLabel(access: InstrumentProperty["access"]): string {
  if (access === "read_only") return "Read only";
  if (access === "write_only") return "Write only";
  return "Read / write";
}

function samePath(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function interfaceFallbackLabel(interfaceId: string): string {
  const qualifiedName = interfaceId.slice(0, interfaceId.lastIndexOf("/"));
  return titleCase(qualifiedName.slice(qualifiedName.lastIndexOf(".") + 1));
}

function domId(prefix: string, value: string): string {
  return `${prefix}-${value.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function requireSession(session: InstrumentSession | undefined): InstrumentSession {
  if (!session) throw new Error("Connect the instrument before interacting with it.");
  return session;
}

function mutationError(error: unknown): string | undefined {
  return error === null || error === undefined ? undefined : errorMessage(error);
}

function configuredDefaultsReceiptMessage(
  receipt: InstrumentConfiguredDefaultsApplyReceipt,
): string {
  if (receipt.status === "applied") return "Configured defaults applied.";
  if (receipt.status === "unchanged") {
    return "State already matched the configured defaults.";
  }
  return `Configured defaults rejected: ${receipt.problems
    .map((problem) => problem.message)
    .join(" ")}`;
}

function traceValues(receipt: InstrumentCollectReceipt): number[] | undefined {
  for (const value of Object.values(receipt.readback?.values ?? {})) {
    if (
      typeof value === "object" &&
      value !== null &&
      "values" in value &&
      Array.isArray(value.values)
    ) {
      const samples = value.values
        .map((sample) => {
          if (typeof sample === "number" && Number.isFinite(sample)) return sample;
          if (
            typeof sample === "object" &&
            sample !== null &&
            "real" in sample &&
            "imag" in sample &&
            typeof sample.real === "number" &&
            typeof sample.imag === "number"
          ) {
            return Math.hypot(sample.real, sample.imag);
          }
          return undefined;
        })
        .filter((sample): sample is number => sample !== undefined);
      if (samples.length > 0) return samples;
    }
  }
  return undefined;
}

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
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Unplug,
} from "lucide-react";
import type {
  InstrumentCollectReceipt,
  InstrumentInterface,
  InstrumentProperty,
  InstrumentSession,
  InstrumentState,
  InstrumentStateValue,
  InstrumentView,
} from "../../api-contract";
import { errorMessage, formatRelative, titleCase } from "../../lib/presentation";
import {
  applyInstrumentState,
  collectInstrumentAcquisition,
  createInstrumentOperationId,
  instrumentAcquisitionReadiness,
  readInstrumentState,
  resolveInstrumentAttention,
  retryTransientInstrumentMutation,
  type InstrumentAcquisitionTarget,
  type StagedInstrumentProperty,
} from "./instrument-api";

interface DraftValue {
  raw: string | boolean;
  value?: InstrumentStateValue;
}

export function InstrumentInspector({
  instrument,
  session,
  actor,
  sessionError,
  connectPending,
  closePending,
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
  onActorChange: (actor: string) => void;
  onConnect: () => void;
  onClose: () => void;
  onSessionLost: (message: string) => void;
  onDisconnectOwner: () => void;
  onEditConnection: () => void;
}) {
  const queryClient = useQueryClient();
  const instrumentId = instrument.spec.id;
  const connected = session?.instrument_ids.includes(instrumentId) ?? false;
  const connectionEditable = instrument.spec.connection.kind === "tcpip_socket";
  const interactionEnabled = connected && !closePending;
  const description =
    session?.descriptions.find((candidate) => candidate.instrument_id === instrumentId) ??
    instrument.description ??
    undefined;
  const [state, setState] = useState<InstrumentState>();
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const [applyResult, setApplyResult] = useState<string>();
  const [collectResults, setCollectResults] = useState<Record<string, InstrumentCollectReceipt>>(
    {},
  );
  const applyOperationIdRef = useRef<string | undefined>(undefined);
  const collectOperationIdsRef = useRef<Record<string, string>>({});

  useEffect(() => {
    if (connected) return;
    applyOperationIdRef.current = undefined;
    collectOperationIdsRef.current = {};
    setState(undefined);
    setDrafts({});
    setApplyResult(undefined);
    setCollectResults({});
  }, [connected]);

  const readMutation = useMutation({
    mutationFn: () => readInstrumentState(requireSession(session), instrumentId),
    onSuccess: (snapshot) => {
      applyOperationIdRef.current = undefined;
      collectOperationIdsRef.current = {};
      setState(snapshot);
      setDrafts({});
      setApplyResult(undefined);
      setCollectResults({});
    },
  });
  useEffect(() => {
    if (connected && session) readMutation.mutate();
    // Only a newly opened session should trigger the initial read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, instrumentId, session?.session_id]);
  const stagedProperties = useMemo(() => stagedInstrumentProperties(drafts), [drafts]);
  const invalidDraft = Object.values(drafts).some((draft) => draft.value === undefined);
  const applyMutation = useMutation({
    mutationFn: ({
      properties,
      operationId,
    }: {
      properties: StagedInstrumentProperty[];
      operationId: string;
    }) => applyInstrumentState(requireSession(session), instrumentId, properties, operationId),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt) => {
      applyOperationIdRef.current = undefined;
      setApplyResult(receipt.status);
      if (receipt.state) setState(receipt.state);
      if (receipt.status === "applied") {
        collectOperationIdsRef.current = {};
        setCollectResults({});
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
  const collectMutation = useMutation({
    mutationFn: ({
      target,
      stateSnapshot,
      operationId,
    }: {
      target: InstrumentAcquisitionTarget;
      stateSnapshot?: InstrumentState;
      operationId: string;
    }) =>
      collectInstrumentAcquisition(
        requireSession(session),
        instrumentId,
        target,
        stateSnapshot,
        operationId,
      ),
    retry: retryTransientInstrumentMutation,
    retryDelay: 250,
    onSuccess: (receipt, { target }) => {
      const key = acquisitionKey(target);
      delete collectOperationIdsRef.current[key];
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
    draft?: DraftValue,
  ) => {
    const key = propertyKey(interfaceId, componentPath, property.id);
    applyOperationIdRef.current = undefined;
    setDrafts((current) => {
      const next = { ...current };
      if (draft === undefined) delete next[key];
      else next[key] = draft;
      return next;
    });
    setApplyResult(undefined);
    applyMutation.reset();
  };
  const applyStaged = () => {
    applyOperationIdRef.current ??= createInstrumentOperationId("apply");
    applyMutation.mutate({
      properties: stagedProperties,
      operationId: applyOperationIdRef.current,
    });
  };
  const resetStaged = () => {
    applyOperationIdRef.current = undefined;
    setDrafts({});
    applyMutation.reset();
  };
  const collectAcquisition = (target: InstrumentAcquisitionTarget) => {
    const key = acquisitionKey(target);
    const operationId =
      collectOperationIdsRef.current[key] ?? createInstrumentOperationId("collect");
    collectOperationIdsRef.current[key] = operationId;
    collectMutation.mutate({
      target,
      stateSnapshot: state,
      operationId,
    });
  };
  const interactionError =
    sessionError ??
    mutationError(readMutation.error) ??
    mutationError(applyMutation.error) ??
    mutationError(collectMutation.error) ??
    mutationError(resolveMutation.error);

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
          <Pencil size={14} />
          Edit connection
        </button>
      </header>

      <InstrumentSessionPanel
        instrument={instrument}
        session={session}
        connected={connected}
        actor={actor}
        connectPending={connectPending}
        closePending={closePending}
        refreshPending={readMutation.isPending}
        resolvePending={resolveMutation.isPending}
        onActorChange={onActorChange}
        onConnect={onConnect}
        onClose={onClose}
        onDisconnectOwner={onDisconnectOwner}
        onRefresh={() => readMutation.mutate()}
        onResolve={() => resolveMutation.mutate()}
      />

      {interactionError && (
        <div className="instrument-inline-error" role="alert">
          <AlertTriangle size={15} />
          {interactionError}
        </div>
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
                  connected={interactionEnabled}
                  state={state}
                  drafts={drafts}
                  collectResults={collectResults}
                  collectingTarget={
                    collectMutation.isPending ? collectMutation.variables?.target : undefined
                  }
                  onStage={(componentPath, property, draft) =>
                    stage(instrumentInterface.id, componentPath, property, draft)
                  }
                  onCollect={(target) => collectAcquisition(target)}
                />
              ))}
            </div>
          ) : (
            <InspectorEmpty
              icon={<CircleOff />}
              title="No interactive interfaces"
              detail="This driver does not declare GUI-safe properties or acquisitions."
            />
          )}

          {connected && Object.keys(drafts).length > 0 && (
            <div className="staged-apply-bar">
              <div>
                <strong>
                  {Object.keys(drafts).length} staged{" "}
                  {Object.keys(drafts).length === 1 ? "property" : "properties"}
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
                disabled={
                  closePending ||
                  invalidDraft ||
                  stagedProperties.length === 0 ||
                  applyMutation.isPending
                }
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
  refreshPending,
  resolvePending,
  onActorChange,
  onConnect,
  onClose,
  onDisconnectOwner,
  onRefresh,
  onResolve,
}: {
  instrument: InstrumentView;
  session?: InstrumentSession;
  connected: boolean;
  actor: string;
  connectPending: boolean;
  closePending: boolean;
  refreshPending: boolean;
  resolvePending: boolean;
  onActorChange: (actor: string) => void;
  onConnect: () => void;
  onClose: () => void;
  onDisconnectOwner: () => void;
  onRefresh: () => void;
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
          <button
            type="button"
            className="secondary-button"
            onClick={onRefresh}
            disabled={refreshPending || closePending}
          >
            <RefreshCw className={refreshPending ? "spin" : undefined} size={14} />
            Refresh state
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={onClose}
            disabled={closePending}
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
          {ownerKind} <code>{instrument.owner_id}</code>
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
  collectingTarget,
  onStage,
  onCollect,
}: {
  instrumentInterface: InstrumentInterface;
  connected: boolean;
  state?: InstrumentState;
  drafts: Record<string, DraftValue>;
  collectResults: Record<string, InstrumentCollectReceipt>;
  collectingTarget?: InstrumentAcquisitionTarget;
  onStage: (componentPath: string[], property: InstrumentProperty, draft?: DraftValue) => void;
  onCollect: (target: InstrumentAcquisitionTarget) => void;
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
        collectingTarget={collectingTarget}
        onStage={onStage}
        onCollect={onCollect}
      />
    </article>
  );
}

type InterfaceMember = Pick<
  InstrumentInterface,
  "label" | "description" | "properties" | "operations" | "acquisitions" | "components"
>;

function InterfaceEndpoint({
  interfaceId,
  componentPath,
  member,
  connected,
  state,
  drafts,
  collectResults,
  collectingTarget,
  onStage,
  onCollect,
}: {
  interfaceId: string;
  componentPath: string[];
  member: InterfaceMember;
  connected: boolean;
  state?: InstrumentState;
  drafts: Record<string, DraftValue>;
  collectResults: Record<string, InstrumentCollectReceipt>;
  collectingTarget?: InstrumentAcquisitionTarget;
  onStage: (componentPath: string[], property: InstrumentProperty, draft?: DraftValue) => void;
  onCollect: (target: InstrumentAcquisitionTarget) => void;
}) {
  const hasLocalControls =
    (member.properties ?? []).length > 0 || (member.acquisitions ?? []).length > 0;
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

          {(member.properties ?? []).length > 0 && (
            <div className="interface-properties">
              {(member.properties ?? []).map((property) => {
                const key = propertyKey(interfaceId, componentPath, property.id);
                return (
                  <PropertyEditor
                    key={property.id}
                    property={property}
                    currentValue={stateValue(state, interfaceId, componentPath, property.id)}
                    draft={drafts[key]}
                    editable={connected && property.access !== "read_only"}
                    onChange={(draft) => onStage(componentPath, property, draft)}
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
          collectingTarget={collectingTarget}
          onStage={onStage}
          onCollect={onCollect}
        />
      ))}
    </>
  );
}

function AcquisitionControl({
  target,
  connected,
  state,
  result,
  collecting,
  onCollect,
}: {
  target: InstrumentAcquisitionTarget;
  connected: boolean;
  state?: InstrumentState;
  result?: InstrumentCollectReceipt;
  collecting: boolean;
  onCollect: () => void;
}) {
  const acquisition = target.acquisition;
  const results = acquisition.results ?? [];
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
        {results.length > 0 && (
          <div className="acquisition-collect-action">
            <button
              type="button"
              className="secondary-button"
              onClick={onCollect}
              disabled={!connected || collecting || blocked}
              aria-describedby={connected && blocked ? reasonId : undefined}
              title={
                !connected ? "Connect before collecting" : blocked ? readiness.reason : undefined
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

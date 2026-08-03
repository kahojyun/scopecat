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
import { classes, eyebrow, primaryButton, secondaryButton } from "../../ui/styles";
import { ApiError } from "../../api";
import { errorMessage, formatRelative, titleCase } from "../../lib/presentation";
import { InstrumentPropertyInput, type InstrumentPropertyDraft } from "./InstrumentPropertyInput";
import {
  applyInstrumentState,
  applyInstrumentConfiguredDefaults,
  collectInstrumentAcquisition,
  createInstrumentCommandId,
  invokeInstrumentOperation,
  readInstrumentState,
  resolveInstrumentAttention,
  retryTransientInstrumentMutation,
  type InstrumentAcquisitionTarget,
  type InstrumentOperationArgument,
  type InstrumentOperationTarget,
  type StagedInstrumentProperty,
} from "./instrument-api";

type DraftValue = InstrumentPropertyDraft;

export function InstrumentInspector({
  instrument,
  session,
  sessionError,
  connectPending,
  closePending,
  configurationPending,
  configurationUnavailable,
  onConnect,
  onClose,
  onSessionLost,
  onDisconnectOwner,
  onConfigure,
}: {
  instrument: InstrumentView;
  session?: InstrumentSession;
  sessionError?: string;
  connectPending: boolean;
  closePending: boolean;
  configurationPending: boolean;
  configurationUnavailable: boolean;
  onConnect: () => void;
  onClose: () => void;
  onSessionLost: (message: string) => void;
  onDisconnectOwner: () => void;
  onConfigure: () => void;
}) {
  const queryClient = useQueryClient();
  const instrumentId = instrument.instrument_id;
  const connected = session?.instrument_ids.includes(instrumentId) ?? false;
  const description =
    session?.descriptions.find((candidate) => candidate.instrument_id === instrumentId) ??
    instrument.description ??
    undefined;
  const synchronizedState = session?.observed_state.find(
    (snapshot) => snapshot.instrument_id === instrumentId,
  );
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
  const resetReadMutation = readMutation.reset;
  useEffect(() => {
    applyCommandIdRef.current = undefined;
    configuredDefaultsOperationIdRef.current = undefined;
    collectCommandIdsRef.current = {};
    invokeCommandIdsRef.current = {};
    setState(connected ? synchronizedState : undefined);
    setDrafts({});
    setApplyResult(undefined);
    setConfiguredDefaultsResult(undefined);
    setCollectResults({});
    setInvokeResults({});
    resetReadMutation();
  }, [connected, instrumentId, resetReadMutation, session?.session_id, synchronizedState]);
  const declaredPropertyKeys = useMemo(
    () => instrumentPropertyKeys(description?.interfaces ?? []),
    [description?.interfaces],
  );
  const declaredDrafts = useMemo(
    () => filterDrafts(drafts, declaredPropertyKeys),
    [declaredPropertyKeys, drafts],
  );
  const stagedProperties = useMemo(
    () => stagedInstrumentProperties(declaredDrafts),
    [declaredDrafts],
  );
  const stagedCount = Object.keys(declaredDrafts).length;
  const invalidDraft = Object.values(declaredDrafts).some((draft) => draft.value === undefined);
  useEffect(() => {
    setDrafts((current) => filterDrafts(current, declaredPropertyKeys));
  }, [declaredPropertyKeys]);
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
      commandId,
    }: {
      target: InstrumentAcquisitionTarget;
      commandId: string;
    }) => collectInstrumentAcquisition(requireSession(session), instrumentId, target, commandId),
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
    draft?: DraftValue,
  ) => {
    const key = propertyKey(interfaceId, componentPath, property.id);
    applyCommandIdRef.current = undefined;
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
    <section
      className="relative grid min-h-[640px] min-w-0 content-start gap-3.5 p-5 max-[880px]:min-h-[560px] max-[880px]:rounded-lg max-[880px]:border max-[880px]:border-line max-[680px]:px-[13px] max-[680px]:py-4"
      aria-live="polite"
    >
      <header className="flex items-start justify-between gap-[18px] border-b border-line pb-3.5 max-[460px]:grid">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="m-0 text-[1.1rem] font-[650] tracking-[-0.025em]">
              {description?.label ?? instrumentId}
            </h2>
            <AvailabilityBadge availability={instrument.availability} connected={connected} />
          </div>
          <code className="mt-1 block text-[0.61rem] text-text-dim">{instrumentId}</code>
          {description?.description && (
            <p className="mt-[9px] mb-0 max-w-[760px] text-[0.68rem] leading-[1.55] text-text-dim">
              {description.description}
            </p>
          )}
        </div>
        <button
          type="button"
          className={classes(secondaryButton, "max-[460px]:justify-self-start")}
          onClick={onConfigure}
          disabled={
            connected ||
            configurationPending ||
            configurationUnavailable ||
            instrument.availability === "active" ||
            instrument.availability === "quarantined"
          }
          title={
            configurationUnavailable
              ? "Driver catalog unavailable"
              : connected
                ? "Disconnect before changing the immutable config"
                : instrument.availability === "active" || instrument.availability === "quarantined"
                  ? "Resolve the current owner before changing the immutable config"
                  : undefined
          }
        >
          {configurationPending ? (
            <LoaderCircle className="animate-spin" size={14} />
          ) : (
            <Pencil size={14} />
          )}
          {configurationPending ? "Loading configuration" : "Configure device"}
        </button>
      </header>

      <InstrumentSessionPanel
        instrument={instrument}
        session={session}
        connected={connected}
        connectPending={connectPending}
        closePending={closePending}
        interactionPending={interactionPending}
        refreshPending={readMutation.isPending}
        configuredDefaultsVisible={hasConfiguredDefaults}
        configuredDefaultsPending={configuredDefaultsMutation.isPending}
        configuredDefaultsDisabled={configuredDefaultsDisabled}
        configuredDefaultsDisabledReason={configuredDefaultsDisabledReason}
        resolvePending={resolveMutation.isPending}
        onConnect={onConnect}
        onClose={onClose}
        onDisconnectOwner={onDisconnectOwner}
        onRefresh={() => readMutation.mutate()}
        onApplyConfiguredDefaults={applyConfiguredDefaults}
        onResolve={() => resolveMutation.mutate()}
      />

      {interactionError && (
        <div className={inlineError} role="alert">
          <AlertTriangle size={15} />
          {interactionError}
        </div>
      )}

      {configuredDefaultsResult && (
        <p
          className={classes(receiptStyle, receiptTone(configuredDefaultsResult.status))}
          role="status"
        >
          {configuredDefaultsReceiptMessage(configuredDefaultsResult)}
        </p>
      )}

      {(instrument.problems ?? []).length > 0 && (
        <div className={problems} role="status">
          <strong className="mb-1 block">Driver is unavailable</strong>
          {instrument.problems.map((problem, index) => (
            <p className="my-0.5" key={`${problem.code}-${index}`}>
              {problem.message}
            </p>
          ))}
        </div>
      )}

      {description ? (
        <>
          <div
            className="mt-[3px] flex items-end justify-between max-[460px]:flex-col max-[460px]:items-start"
            data-testid="interface-heading"
          >
            <div>
              <span className={eyebrow}>Device controls</span>
              <h3 className="m-0 text-[0.9rem] font-[650]">Interfaces</h3>
            </div>
          </div>

          {(description.interfaces ?? []).length > 0 ? (
            <div className="grid gap-2.5">
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
                  onStage={(componentPath, property, draft) =>
                    stage(instrumentInterface.id, componentPath, property, draft)
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
              detail="This device does not declare interactive properties, operations, or acquisitions."
            />
          )}

          {connected && stagedCount > 0 && (
            <div className="sticky bottom-2.5 z-[5] grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 rounded-md border border-[rgb(128_163_207_/_35%)] bg-[color-mix(in_srgb,var(--color-panel-strong)_94%,transparent)] px-[11px] py-2.5 shadow-[0_10px_30px_rgb(0_0_0_/_28%)] backdrop-blur-[12px] max-[460px]:grid-cols-2">
              <div className="grid gap-0.5 max-[460px]:col-span-full">
                <strong className="text-[0.67rem]">
                  {stagedCount} staged {stagedCount === 1 ? "property" : "properties"}
                </strong>
                <small className="text-[0.54rem] text-text-dim">
                  Values remain local until you apply the complete staged change once.
                </small>
              </div>
              <button
                type="button"
                className={secondaryButton}
                onClick={resetStaged}
                disabled={applyMutation.isPending}
              >
                <RotateCcw size={14} />
                Reset
              </button>
              <button
                type="button"
                className={primaryButton}
                onClick={applyStaged}
                disabled={interactionDisabled || invalidDraft || stagedProperties.length === 0}
                title={
                  interactionDisabled
                    ? "Wait for the current instrument interaction to finish"
                    : invalidDraft
                      ? "Correct invalid staged values before applying"
                      : undefined
                }
              >
                {applyMutation.isPending ? (
                  <LoaderCircle className="animate-spin" size={14} />
                ) : (
                  <Check size={14} />
                )}
                Apply staged
              </button>
            </div>
          )}
          {applyResult && (
            <p className={classes(receiptStyle, receiptTone(applyResult))}>
              Apply receipt: {titleCase(applyResult)}
            </p>
          )}
        </>
      ) : (
        <InspectorEmpty
          icon={<CircleOff />}
          title="Device controls unavailable"
          detail="Review the listed problem or edit this instrument’s connection configuration."
        />
      )}
    </section>
  );
}

function InstrumentSessionPanel({
  instrument,
  session,
  connected,
  connectPending,
  closePending,
  interactionPending,
  refreshPending,
  configuredDefaultsVisible,
  configuredDefaultsPending,
  configuredDefaultsDisabled,
  configuredDefaultsDisabledReason,
  resolvePending,
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
  connectPending: boolean;
  closePending: boolean;
  interactionPending: boolean;
  refreshPending: boolean;
  configuredDefaultsVisible: boolean;
  configuredDefaultsPending: boolean;
  configuredDefaultsDisabled: boolean;
  configuredDefaultsDisabledReason?: string;
  resolvePending: boolean;
  onConnect: () => void;
  onClose: () => void;
  onDisconnectOwner: () => void;
  onRefresh: () => void;
  onApplyConfiguredDefaults: () => void;
  onResolve: () => void;
}) {
  if (connected && session) {
    return (
      <div className={classes(sessionPanel, "border-[rgb(128_163_207_/_24%)] bg-accent-soft")}>
        <div className="flex min-w-0 flex-1 items-center gap-2.5 max-[680px]:w-full max-[680px]:basis-full">
          <span
            className="grid size-8 place-items-center rounded-sm bg-[rgb(128_163_207_/_10%)] text-accent"
            aria-hidden="true"
          >
            <Cable size={16} />
          </span>
          <div className="grid gap-1">
            <strong className="text-[0.7rem] text-text-soft">Interactive session connected</strong>
            <small className="overflow-hidden text-[0.58rem] leading-[1.4] text-ellipsis text-text-dim">
              Opened {formatRelative(session.opened_at)}
            </small>
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-[7px] max-[460px]:w-full max-[460px]:[&>button]:flex-1">
          {configuredDefaultsVisible && (
            <button
              type="button"
              className={secondaryButton}
              onClick={onApplyConfiguredDefaults}
              disabled={configuredDefaultsDisabled}
              title={configuredDefaultsDisabledReason}
            >
              {configuredDefaultsPending ? (
                <LoaderCircle className="animate-spin" size={14} />
              ) : (
                <RotateCcw size={14} />
              )}
              Apply configured defaults
            </button>
          )}
          <button
            type="button"
            className={secondaryButton}
            onClick={onRefresh}
            disabled={interactionPending || closePending}
            title={
              interactionPending
                ? "Wait for the current instrument interaction to finish"
                : undefined
            }
          >
            <RefreshCw className={refreshPending ? "animate-spin" : undefined} size={14} />
            Refresh state
          </button>
          <button
            type="button"
            className={secondaryButton}
            onClick={onClose}
            disabled={closePending || interactionPending}
            title={
              interactionPending
                ? "Wait for the current instrument interaction to finish"
                : undefined
            }
          >
            {closePending ? (
              <LoaderCircle className="animate-spin" size={14} />
            ) : (
              <Unplug size={14} />
            )}
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
      <div className={attentionPanel}>
        <ShieldAlert className="mt-0.5 flex-none" size={19} aria-hidden="true" />
        <div className="flex-1 max-[680px]:w-full max-[680px]:basis-full">
          <strong className="text-[0.7rem] text-text-soft">Operator resolution required</strong>
          <p className={attentionCopy}>
            The previous operation left hardware state uncertain. Automatic reuse is blocked.
          </p>
          <OwnerDescription instrument={instrument} />
        </div>
        <button
          type="button"
          className={secondaryButton}
          onClick={onResolve}
          disabled={!canResolve || resolvePending}
          title={
            canResolve
              ? "Acknowledge the quarantined interactive session and release it"
              : "Resolve this owner from its run workflow"
          }
        >
          {resolvePending ? (
            <LoaderCircle className="animate-spin" size={14} />
          ) : (
            <ShieldAlert size={14} />
          )}
          Resolve quarantine
        </button>
      </div>
    );
  }

  if (instrument.availability === "active") {
    const canDisconnectSession =
      instrument.owner_kind === "instrument_session" && Boolean(instrument.owner_id);
    return (
      <div className={attentionPanel}>
        <Database className="mt-0.5 flex-none" size={18} aria-hidden="true" />
        <div className="flex-1 max-[680px]:w-full max-[680px]:basis-full">
          <strong className="text-[0.7rem] text-text-soft">Read-only while owned</strong>
          <p className={attentionCopy}>Another run or interactive session owns this instrument.</p>
          <OwnerDescription instrument={instrument} />
        </div>
        {canDisconnectSession && (
          <button
            type="button"
            className={secondaryButton}
            onClick={onDisconnectOwner}
            disabled={closePending}
            title="Disconnect this daemon-owned interactive session"
          >
            {closePending ? (
              <LoaderCircle className="animate-spin" size={14} />
            ) : (
              <Unplug size={14} />
            )}
            Disconnect session
          </button>
        )}
      </div>
    );
  }

  if (instrument.availability === "unavailable") {
    return (
      <div
        className={classes(attentionPanel, "border-[rgb(215_126_121_/_24%)] bg-red-soft text-red")}
      >
        <CircleOff className="mt-0.5 flex-none" size={18} aria-hidden="true" />
        <div className="flex-1">
          <strong className="text-[0.7rem] text-text-soft">Connection unavailable</strong>
          <p className={attentionCopy}>
            Fix the provider or connection configuration before opening a session.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={sessionPanel}>
      <div className="grid min-w-0 flex-1 gap-1 max-[680px]:w-full max-[680px]:basis-full">
        <strong className="text-[0.7rem] text-text-soft">
          Connect only when you are ready to interact
        </strong>
        <small className="overflow-hidden text-[0.58rem] leading-[1.4] text-ellipsis text-text-dim">
          Opening a session gives the daemon exclusive ownership. Selecting this instrument never
          connects it.
        </small>
      </div>
      <button type="button" className={primaryButton} onClick={onConnect} disabled={connectPending}>
        {connectPending ? <LoaderCircle className="animate-spin" size={14} /> : <Cable size={14} />}
        Connect
      </button>
    </div>
  );
}

function OwnerDescription({ instrument }: { instrument: InstrumentView }) {
  const ownerKind = instrument.owner_kind === "run" ? "Run" : "Interactive session";
  return <small className="mt-[7px] block text-[0.59rem] text-text-dim">{ownerKind}</small>;
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
  onStage: (componentPath: string[], property: InstrumentProperty, draft?: DraftValue) => void;
  onCollect: (target: InstrumentAcquisitionTarget) => void;
  onInvoke: (
    target: InstrumentOperationTarget,
    operationArguments: InstrumentOperationArgument[],
  ) => void;
  onOperationEdit: (target: InstrumentOperationTarget) => void;
}) {
  return (
    <article
      className="overflow-hidden rounded-md border border-line bg-panel-soft"
      data-testid={`interface-card-${instrumentInterface.id}`}
    >
      <header className="flex items-start justify-between gap-3.5 border-b border-line bg-[rgb(255_255_255_/_1%)] px-[13px] py-3 max-[460px]:flex-col">
        <div>
          <h4 className="m-0 text-[0.77rem] font-[680]">
            {instrumentInterface.label ?? interfaceFallbackLabel(instrumentInterface.id)}
          </h4>
          {instrumentInterface.description && (
            <p className="mt-1.5 mb-0 max-w-[760px] text-[0.6rem] leading-[1.45] text-text-dim">
              {instrumentInterface.description}
            </p>
          )}
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
  onStage: (componentPath: string[], property: InstrumentProperty, draft?: DraftValue) => void;
  onCollect: (target: InstrumentAcquisitionTarget) => void;
  onInvoke: (
    target: InstrumentOperationTarget,
    operationArguments: InstrumentOperationArgument[],
  ) => void;
  onOperationEdit: (target: InstrumentOperationTarget) => void;
}) {
  const properties = member.properties ?? [];
  const operations = guiSafeOperations(member.operations ?? []);
  const hasLocalControls =
    properties.length > 0 || operations.length > 0 || (member.acquisitions ?? []).length > 0;
  return (
    <>
      {hasLocalControls && (
        <section className={componentPath.length > 0 ? "border-t border-line" : undefined}>
          {componentPath.length > 0 && (
            <header className="bg-panel-strong px-[13px] py-2.5">
              <h5 className="m-0 text-[0.67rem] text-text-soft">
                {member.label ?? titleCase(componentPath.at(-1) ?? "")}
              </h5>
              <small className="mt-[3px] block text-[0.51rem] text-text-dim">
                {componentPath.map(titleCase).join(" / ")}
              </small>
              {member.description && <p>{member.description}</p>}
            </header>
          )}

          {properties.length > 0 && (
            <div className={controlGrid}>
              {properties.map((property) => {
                const key = propertyKey(interfaceId, componentPath, property.id);
                return (
                  <PropertyEditor
                    key={property.id}
                    property={property}
                    currentValue={stateValue(state, interfaceId, componentPath, property.id)}
                    draft={drafts[key]}
                    editable={connected && !interactionDisabled && property.access !== "read_only"}
                    onChange={(draft) => onStage(componentPath, property, draft)}
                  />
                );
              })}
            </div>
          )}

          {operations.length > 0 && (
            <div className="grid">
              {operations.map((operation) => {
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
            <div className="grid">
              {(member.acquisitions ?? []).map((acquisition) => {
                const target = { interfaceId, componentPath, acquisition };
                const key = acquisitionKey(target);
                return (
                  <AcquisitionControl
                    key={acquisition.id}
                    target={target}
                    connected={connected}
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
  const operationArguments = argumentSpecs.flatMap((argument) => {
    const value = drafts[argument.id]?.value;
    return value === undefined ? [] : [{ id: argument.id, value }];
  });
  const invalid = operationArguments.length !== argumentSpecs.length;
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
    <section className="border-t border-line">
      <header className={controlHeader}>
        <div>
          <strong className="text-[0.66rem] text-text-soft">{label}</strong>
          {operation.description && <p className={controlDescription}>{operation.description}</p>}
        </div>
        <button
          type="button"
          className={classes(secondaryButton, "flex-none")}
          aria-label={`Invoke ${label}`}
          onClick={() => onInvoke(operationArguments)}
          disabled={!connected || interactionDisabled || invalid}
          title={
            !connected
              ? "Connect before invoking"
              : interactionDisabled
                ? "Wait for the current instrument interaction to finish"
                : invalid
                  ? "Fill every operation argument before invoking"
                  : undefined
          }
        >
          {invoking ? <LoaderCircle className="animate-spin" size={14} /> : <Play size={14} />}
          Invoke
        </button>
      </header>
      {argumentSpecs.length > 0 && (
        <div className={controlGrid}>
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
      {result && (
        <p
          className={classes(
            receiptStyle,
            "rounded-none border-x-0 border-b-0",
            receiptTone(result.status),
          )}
        >
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
  if (type.type === "payload") return null;
  const label = argument.label ?? titleCase(argument.id);
  const raw = draft?.raw ?? "";
  return (
    <label className={editorRow}>
      <span className={propertyLabel}>
        <span className="grid min-w-0">
          <strong className="overflow-hidden text-[0.66rem] font-[670] text-ellipsis whitespace-nowrap">
            {label}
          </strong>
        </span>
        <small className="flex-none text-[0.49rem] font-extrabold tracking-[0.04em] text-text-dim uppercase">
          Argument
        </small>
      </span>
      {type.type === "bool" ? (
        <select
          className={controlInput}
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
          className={controlInput}
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
        <span
          className={classes(
            "grid items-stretch",
            type.type === "quantity"
              ? "grid-cols-[minmax(0,1fr)_auto]"
              : "grid-cols-[minmax(0,1fr)]",
          )}
        >
          <input
            className={classes(controlInput, type.type === "quantity" && "rounded-r-none")}
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
              <span className={unitAddon}>{type.unit}</span>
            ) : (
              <input
                className={classes(controlInput, "min-w-16 rounded-l-none border-l-0")}
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
          className={controlInput}
          type="text"
          value={typeof raw === "string" ? raw : ""}
          placeholder={editable ? "Enter value" : "—"}
          disabled={!editable}
          onChange={(event) => onChange({ raw: event.target.value, value: event.target.value })}
        />
      ) : null}
      {argument.description && (
        <small className={propertyDescription}>{argument.description}</small>
      )}
      {draft && (
        <button type="button" className={propertyReset} onClick={() => onChange()}>
          Clear argument
        </button>
      )}
    </label>
  );
}

function AcquisitionControl({
  target,
  connected,
  result,
  collecting,
  interactionDisabled,
  onCollect,
}: {
  target: InstrumentAcquisitionTarget;
  connected: boolean;
  result?: InstrumentCollectReceipt;
  collecting: boolean;
  interactionDisabled: boolean;
  onCollect: () => void;
}) {
  const acquisition = target.acquisition;
  const results = acquisition.results;
  return (
    <section className="border-t border-line">
      <header className={controlHeader}>
        <div>
          <strong className="text-[0.66rem] text-text-soft">
            {acquisition.label ?? titleCase(acquisition.id)}
          </strong>
          {acquisition.description && (
            <p className={controlDescription}>{acquisition.description}</p>
          )}
        </div>
        {results.length > 0 && (
          <div className="grid max-w-80 flex-none justify-items-end gap-1.5">
            <button
              type="button"
              className={secondaryButton}
              onClick={onCollect}
              disabled={!connected || interactionDisabled}
              title={
                !connected
                  ? "Connect before collecting"
                  : interactionDisabled
                    ? "Wait for the current instrument interaction to finish"
                    : undefined
              }
            >
              {collecting ? (
                <LoaderCircle className="animate-spin" size={14} />
              ) : (
                <Database size={14} />
              )}
              Collect
            </button>
          </div>
        )}
      </header>
      {results.length > 0 && (
        <div className="flex flex-wrap items-center gap-[7px] border-t border-line px-3 py-[9px]">
          <span className="mr-[3px] text-[0.51rem] font-extrabold tracking-[0.05em] text-text-dim uppercase">
            Results
          </span>
          {results.map((acquisitionResult) => (
            <span
              className="inline-flex items-baseline gap-[7px] rounded-full border border-line px-[7px] py-1 text-[0.56rem] text-text-soft"
              key={acquisitionResult.id}
            >
              {acquisitionResult.label ?? titleCase(acquisitionResult.id)}
              <small className="text-[0.5rem] text-text-dim">
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
  const dirty = draft !== undefined;
  return (
    <label
      className={classes(
        editorRow,
        dirty && "bg-accent-soft shadow-[inset_2px_0_var(--color-accent)]",
      )}
      data-testid={`interface-property-${property.id}`}
    >
      <span className={propertyLabel}>
        <span className="grid min-w-0">
          <strong
            className="overflow-hidden text-[0.66rem] font-[670] text-ellipsis whitespace-nowrap"
            data-testid="property-label"
          >
            {property.label ?? titleCase(property.id)}
          </strong>
        </span>
        <small className="flex-none text-[0.49rem] font-extrabold tracking-[0.04em] text-text-dim uppercase">
          {accessLabel(property.access)}
        </small>
      </span>
      <InstrumentPropertyInput
        property={property}
        currentValue={currentValue}
        draft={draft}
        editable={editable}
        onChange={onChange}
      />
      {property.description && (
        <small className={propertyDescription}>{property.description}</small>
      )}
      {dirty && (
        <button type="button" className={propertyReset} onClick={() => onChange()}>
          Reset staged value
        </button>
      )}
    </label>
  );
}

function CollectPreview({ receipt }: { receipt: InstrumentCollectReceipt }) {
  const trace = traceValues(receipt);
  const unavailable = unavailableResults(receipt);
  return (
    <div className="grid gap-[9px] border-t border-line bg-bg px-3 py-[11px]">
      <div className="flex items-baseline gap-[9px]">
        <strong
          className={classes(
            "text-[0.62rem] text-accent",
            (receipt.status === "not_collected" || receipt.status === "unknown") && "text-yellow",
          )}
        >
          Collect receipt: {titleCase(receipt.status)}
        </strong>
        {receipt.readback && (
          <small className="text-[0.54rem] text-text-dim">
            {Object.keys(receipt.readback.values ?? {}).length} results returned
          </small>
        )}
      </div>
      {unavailable.count > 0 && (
        <div className="flex items-center gap-[7px] text-yellow" role="status">
          <AlertTriangle size={13} aria-hidden="true" />
          <span className="text-[0.58rem] font-[650]">
            {unavailable.count} {unavailable.count === 1 ? "result" : "results"} unavailable
          </span>
          <small className="text-inherit">
            Reasons: {unavailable.reasons.map(titleCase).join(", ")}
          </small>
        </div>
      )}
      {trace && <TracePreview values={trace} />}
    </div>
  );
}

function guiSafeOperations(operations: InstrumentOperation[]): InstrumentOperation[] {
  return operations.filter(
    (operation) =>
      !(operation.arguments ?? []).some((argument) => argument.value_type.type === "payload"),
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
      className="h-[110px] w-full rounded-sm border border-line p-[5px] [background-image:linear-gradient(var(--color-line)_1px,transparent_1px),linear-gradient(90deg,var(--color-line)_1px,transparent_1px)] [background-size:25%_50%] [&_polyline]:fill-none [&_polyline]:stroke-accent [&_polyline]:[stroke-width:1.5] [&_polyline]:[vector-effect:non-scaling-stroke]"
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
    <div className="grid min-h-[230px] place-content-center justify-items-center px-5 py-[35px] text-center text-text-dim">
      <span
        className="mb-[11px] grid size-[42px] place-items-center rounded-full bg-panel-strong"
        aria-hidden="true"
      >
        {icon}
      </span>
      <h3 className="m-0 text-[0.76rem] text-text-soft">{title}</h3>
      <p className="mt-1.5 mb-0 max-w-[370px] text-[0.62rem] leading-normal">{detail}</p>
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
  const tone = connected ? availabilityTone.connected : availabilityTone[availability];
  return (
    <span
      className={classes(
        "inline-flex min-h-[21px] flex-none items-center gap-[5px] rounded-full border border-line px-1.5 text-[0.52rem] font-extrabold tracking-[0.04em] text-text-dim uppercase",
        tone,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {label}
    </span>
  );
}

const sessionPanel =
  "flex min-h-16 items-center gap-3.5 rounded-md border border-line bg-panel-soft px-[13px] py-[11px] max-[680px]:flex-wrap max-[680px]:items-stretch";
const attentionPanel =
  "flex min-h-16 items-start gap-3.5 rounded-md border border-[rgb(207_173_104_/_24%)] bg-yellow-soft px-[13px] py-[11px] text-yellow max-[680px]:flex-wrap max-[680px]:items-stretch";
const attentionCopy = "mt-1 mb-0 text-[0.62rem] leading-normal text-text-dim";
const inlineError =
  "flex items-center gap-2 rounded-md border border-[rgb(215_126_121_/_25%)] bg-red-soft px-3 py-2.5 text-[0.66rem] leading-normal text-[#edb5b2]";
const problems =
  "rounded-md border border-[rgb(215_126_121_/_25%)] bg-red-soft px-3 py-2.5 text-[0.66rem] leading-normal text-[#edb5b2]";
const receiptStyle =
  "m-0 rounded-sm border border-line bg-panel-soft px-2.5 py-2 text-[0.61rem] text-text-soft";
const controlGrid =
  "grid grid-cols-[repeat(2,minmax(230px,1fr))] max-[1100px]:grid-cols-[minmax(0,1fr)]";
const controlHeader = "flex items-start justify-between gap-3.5 px-3 py-2.5 max-[460px]:flex-col";
const controlDescription = "mt-1.5 mb-0 max-w-[760px] text-[0.6rem] leading-[1.45] text-text-dim";
const editorRow =
  "relative grid min-h-[78px] grid-cols-[minmax(130px,1fr)_minmax(140px,0.85fr)] items-center gap-x-3.5 gap-y-[9px] border-r border-b border-line bg-transparent px-[13px] py-2.5 even:border-r-0 max-[1100px]:border-r-0 max-[680px]:grid-cols-[minmax(120px,1fr)_minmax(125px,0.9fr)] max-[460px]:grid-cols-[minmax(0,1fr)]";
const propertyLabel = "flex min-w-0 items-start justify-between gap-2";
const controlInput =
  "min-h-[34px] w-full min-w-0 rounded-sm border border-line bg-bg px-[9px] text-[0.64rem] text-text outline-0 focus:border-accent disabled:cursor-not-allowed disabled:text-text-dim disabled:opacity-70 aria-invalid:border-red";
const unitAddon =
  "grid min-w-[42px] place-items-center rounded-r-sm border border-l-0 border-line bg-panel-strong px-2 text-[0.57rem] text-text-dim";
const propertyDescription = "col-span-full text-[0.53rem] leading-[1.4] text-text-dim";
const propertyReset =
  "absolute right-3 bottom-[3px] cursor-pointer border-0 bg-transparent p-0 text-[0.49rem] text-accent";
const positiveReceipt = "border-[rgb(128_163_207_/_24%)] bg-accent-soft text-accent";
const warningReceipt = "border-[rgb(207_173_104_/_25%)] bg-yellow-soft text-yellow";
const availabilityTone = {
  available: positiveReceipt,
  connected: positiveReceipt,
  active: positiveReceipt,
  quarantined: warningReceipt,
  unavailable: "border-[rgb(215_126_121_/_25%)] bg-red-soft text-red",
} satisfies Record<InstrumentView["availability"] | "connected", string>;

function receiptTone(status: string): string {
  return ["applied", "unchanged", "invoked"].includes(status) ? positiveReceipt : warningReceipt;
}

function instrumentPropertyKeys(interfaces: InstrumentInterface[]): Set<string> {
  const keys = new Set<string>();
  for (const instrumentInterface of interfaces) {
    collectPropertyKeys(keys, instrumentInterface.id, [], instrumentInterface);
  }
  return keys;
}

function collectPropertyKeys(
  keys: Set<string>,
  interfaceId: string,
  componentPath: string[],
  member: InterfaceMember,
): void {
  for (const property of member.properties ?? []) {
    keys.add(propertyKey(interfaceId, componentPath, property.id));
  }
  for (const child of member.components ?? []) {
    collectPropertyKeys(keys, interfaceId, [...componentPath, child.id], child);
  }
}

function filterDrafts(
  drafts: Record<string, DraftValue>,
  declaredPropertyKeys: Set<string>,
): Record<string, DraftValue> {
  const next: Record<string, DraftValue> = {};
  let changed = false;
  for (const [key, draft] of Object.entries(drafts)) {
    if (declaredPropertyKeys.has(key)) next[key] = draft;
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
    if (value.kind !== "array") continue;
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
  return undefined;
}

function unavailableResults(receipt: InstrumentCollectReceipt): {
  count: number;
  reasons: string[];
} {
  const values = Object.values(receipt.readback?.values ?? {});
  const unavailable = values.filter((value) => value.kind === "unavailable");
  return {
    count: unavailable.length,
    reasons: [...new Set(unavailable.map((value) => value.reason))].sort(),
  };
}

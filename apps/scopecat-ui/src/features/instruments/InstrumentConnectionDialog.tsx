import { useMemo, useRef, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { Cable, LoaderCircle, Save, X } from "lucide-react";
import type { InstrumentConnection } from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import {
  connectionForKind,
  publishInstrumentConnection,
  type ActiveConfig,
} from "./instrument-api";

export function InstrumentConnectionDialog({
  active,
  instrumentId,
  onCancel,
  onPublished,
}: {
  active: ActiveConfig;
  instrumentId: string;
  onCancel: () => void;
  onPublished: () => void | Promise<void>;
}) {
  const spec = active.config.system.instrument_registry.instruments.find(
    (instrument) => instrument.id === instrumentId,
  );
  if (!spec) {
    return <MissingInstrumentDialog instrumentId={instrumentId} onCancel={onCancel} />;
  }
  return (
    <ConnectionEditor
      active={active}
      instrumentId={instrumentId}
      initialDriverId={spec.driver_id}
      initialConnection={spec.connection}
      onCancel={onCancel}
      onPublished={onPublished}
    />
  );
}

function ConnectionEditor({
  active,
  instrumentId,
  initialDriverId,
  initialConnection,
  onCancel,
  onPublished,
}: {
  active: ActiveConfig;
  instrumentId: string;
  initialDriverId: string;
  initialConnection: InstrumentConnection;
  onCancel: () => void;
  onPublished: () => void | Promise<void>;
}) {
  const driverInput = useRef<HTMLInputElement>(null);
  const [driverId, setDriverId] = useState(initialDriverId);
  const [connection, setConnection] = useState<InstrumentConnection>(initialConnection);
  const [driverPrivateConfigCleared, setDriverPrivateConfigCleared] = useState(false);
  const [actor, setActor] = useState("local-operator");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const valid = useMemo(
    () => driverId.trim().length > 0 && connectionIsValid(connection) && actor.trim().length > 0,
    [actor, connection, driverId],
  );

  const publish = async () => {
    if (!valid) return;
    setPending(true);
    setError(undefined);
    try {
      await publishInstrumentConnection({
        active,
        instrumentId,
        driverId: driverId.trim(),
        connection,
        actor: actor.trim(),
        note: note.trim(),
      });
      await onPublished();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(open) => !open && !pending && onCancel()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup
            className="dialog-popup config-modal instrument-connection-modal"
            initialFocus={driverInput}
          >
            <header>
              <span aria-hidden="true">
                <Cable size={19} />
              </span>
              <div>
                <Dialog.Title className="dialog-title">Edit instrument connection</Dialog.Title>
                <Dialog.Description className="dialog-description">
                  {instrumentId} · publishes a new immutable default
                </Dialog.Description>
              </div>
              <Dialog.Close
                className="icon-button"
                aria-label="Close connection editor"
                disabled={pending}
              >
                <X size={16} />
              </Dialog.Close>
            </header>
            <div className="config-modal-body instrument-connection-form">
              <p
                className={`connection-privacy-note ${driverPrivateConfigCleared ? "cleared" : ""}`}
                aria-live="polite"
              >
                {driverPrivateConfigCleared
                  ? "Driver id changed. The previous credential reference and driver options were cleared; configure replacements outside this simple editor if required."
                  : "Credential references and driver options are hidden. They are preserved only while the driver id remains unchanged; changing it clears both."}
              </p>
              <label>
                <span>Driver id</span>
                <input
                  ref={driverInput}
                  value={driverId}
                  onChange={(event) => {
                    const nextDriverId = event.target.value;
                    setDriverId(nextDriverId);
                    if (!driverPrivateConfigCleared && nextDriverId.trim() !== initialDriverId) {
                      setConnection(clearDriverPrivateConfig);
                      setDriverPrivateConfigCleared(true);
                    }
                  }}
                  aria-invalid={!driverId.trim()}
                />
              </label>
              <label>
                <span>Connection type</span>
                <select
                  value={connection.kind}
                  onChange={(event) =>
                    setConnection(
                      connectionForKind(
                        event.target.value as InstrumentConnection["kind"],
                        connection,
                      ),
                    )
                  }
                >
                  <option value="virtual">Virtual</option>
                  <option value="tcpip_socket">TCP/IP socket</option>
                  <option value="visa">VISA</option>
                  <option value="serial">Serial</option>
                </select>
              </label>
              <ConnectionFields connection={connection} onChange={setConnection} />
              <div className="instrument-config-audit">
                <label>
                  <span>Actor</span>
                  <input
                    value={actor}
                    onChange={(event) => setActor(event.target.value)}
                    aria-label="Configuration actor"
                  />
                </label>
                <label>
                  <span>Note</span>
                  <input
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="Why is this connection changing?"
                  />
                </label>
              </div>
              {error && (
                <div className="instrument-inline-error" role="alert">
                  {error}
                </div>
              )}
            </div>
            <footer>
              <Dialog.Close className="secondary-button" disabled={pending}>
                Cancel
              </Dialog.Close>
              <button
                type="button"
                className="primary-button"
                disabled={!valid || pending}
                onClick={() => void publish()}
              >
                {pending ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                Publish default
              </button>
            </footer>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ConnectionFields({
  connection,
  onChange,
}: {
  connection: InstrumentConnection;
  onChange: (connection: InstrumentConnection) => void;
}) {
  switch (connection.kind) {
    case "virtual":
      return (
        <p className="connection-kind-help">
          Uses the configured in-process virtual driver. Saving does not connect it.
        </p>
      );
    case "tcpip_socket":
      return (
        <div className="instrument-connection-fields two-column">
          <label>
            <span>Host</span>
            <input
              value={connection.host}
              onChange={(event) => onChange({ ...connection, host: event.target.value })}
            />
          </label>
          <NumberField
            label="Port"
            value={connection.port}
            minimum={1}
            maximum={65_535}
            onChange={(port) => onChange({ ...connection, port })}
          />
          <TimeoutField
            value={connection.timeout_seconds}
            onChange={(timeout_seconds) => onChange({ ...connection, timeout_seconds })}
          />
        </div>
      );
    case "visa":
      return (
        <div className="instrument-connection-fields">
          <label>
            <span>VISA resource</span>
            <input
              value={connection.resource}
              onChange={(event) => onChange({ ...connection, resource: event.target.value })}
            />
          </label>
          <label>
            <span>Backend (optional)</span>
            <input
              value={connection.backend ?? ""}
              onChange={(event) => onChange({ ...connection, backend: event.target.value || null })}
            />
          </label>
          <TimeoutField
            value={connection.timeout_seconds}
            onChange={(timeout_seconds) => onChange({ ...connection, timeout_seconds })}
          />
        </div>
      );
    case "serial":
      return (
        <div className="instrument-connection-fields two-column">
          <label>
            <span>Serial port</span>
            <input
              value={connection.port}
              onChange={(event) => onChange({ ...connection, port: event.target.value })}
            />
          </label>
          <NumberField
            label="Baud rate"
            value={connection.baud_rate}
            minimum={1}
            onChange={(baud_rate) => onChange({ ...connection, baud_rate })}
          />
          <TimeoutField
            value={connection.timeout_seconds}
            onChange={(timeout_seconds) => onChange({ ...connection, timeout_seconds })}
          />
        </div>
      );
  }
}

function TimeoutField({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return (
    <NumberField label="Timeout (seconds)" value={value} minimum={0.001} onChange={onChange} />
  );
}

function NumberField({
  label,
  value,
  minimum,
  maximum,
  onChange,
}: {
  label: string;
  value: number;
  minimum: number;
  maximum?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={minimum}
        max={maximum}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function connectionIsValid(connection: InstrumentConnection): boolean {
  switch (connection.kind) {
    case "virtual":
      return true;
    case "tcpip_socket":
      return (
        connection.host.trim().length > 0 &&
        Number.isInteger(connection.port) &&
        connection.port >= 1 &&
        connection.port <= 65_535 &&
        connection.timeout_seconds > 0
      );
    case "visa":
      return connection.resource.trim().length > 0 && connection.timeout_seconds > 0;
    case "serial":
      return (
        connection.port.trim().length > 0 &&
        Number.isInteger(connection.baud_rate) &&
        connection.baud_rate > 0 &&
        connection.timeout_seconds > 0
      );
  }
}

function clearDriverPrivateConfig(connection: InstrumentConnection): InstrumentConnection {
  return {
    ...connection,
    credential_ref: null,
    options: {},
  };
}

function MissingInstrumentDialog({
  instrumentId,
  onCancel,
}: {
  instrumentId: string;
  onCancel: () => void;
}) {
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onCancel()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="dialog-popup confirmation-dialog">
            <div className="dialog-heading">
              <span aria-hidden="true">
                <Cable size={18} />
              </span>
              <div>
                <Dialog.Title className="dialog-title">Instrument changed</Dialog.Title>
                <Dialog.Description className="dialog-description">
                  {instrumentId} is no longer present in the active configuration. Refresh the
                  instrument index before editing.
                </Dialog.Description>
              </div>
            </div>
            <div className="dialog-actions">
              <Dialog.Close className="secondary-button">Close</Dialog.Close>
            </div>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

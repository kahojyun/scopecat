import { useRef } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { FileUp, LoaderCircle, X } from "lucide-react";
import { ActionNote } from "./ConfigUi";
import { safeConfigEntryId } from "./config-utils";
import type { ImportDraft } from "./useConfigMutationWorkflow";

export function ConfigImportDialog({
  draft,
  note,
  pending,
  disabled,
  onChange,
  onNoteChange,
  onCancel,
  onSubmit,
}: {
  draft: ImportDraft;
  note: string;
  pending: boolean;
  disabled: boolean;
  onChange: (draft: ImportDraft) => void;
  onNoteChange: (note: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const validEntryId =
    draft.entryId.length > 0 && safeConfigEntryId(draft.entryId) === draft.entryId;
  const entryIdInput = useRef<HTMLInputElement>(null);
  return (
    <Dialog.Root open onOpenChange={(open) => !open && !pending && onCancel()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="dialog-popup config-modal" initialFocus={entryIdInput}>
            <header>
              <span aria-hidden="true">
                <FileUp size={19} />
              </span>
              <div>
                <Dialog.Title className="dialog-title">Import config snapshot</Dialog.Title>
                <Dialog.Description className="dialog-description">
                  Advanced raw import · {draft.fileName}
                </Dialog.Description>
              </div>
              <Dialog.Close
                className="icon-button"
                aria-label="Close import dialog"
                disabled={pending}
              >
                <X size={16} />
              </Dialog.Close>
            </header>
            <div className="config-modal-body">
              <label>
                <span>Registry entry id</span>
                <input
                  ref={entryIdInput}
                  value={draft.entryId}
                  onChange={(event) => onChange({ ...draft, entryId: event.target.value })}
                  aria-invalid={!validEntryId}
                />
                {!validEntryId && (
                  <small>
                    Use letters, numbers, underscores, and hyphens; start with a letter or number.
                  </small>
                )}
              </label>
              <ActionNote value={note} onChange={onNoteChange} />
            </div>
            <footer>
              <Dialog.Close className="secondary-button" disabled={pending}>
                Cancel
              </Dialog.Close>
              <button
                className="primary-button"
                type="button"
                disabled={disabled || !validEntryId}
                onClick={onSubmit}
              >
                {pending ? <LoaderCircle className="spin" size={15} /> : <FileUp size={15} />}
                Import raw snapshot
              </button>
            </footer>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

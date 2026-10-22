import type { ReactNode } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";
import styles from "./ConfirmDialog.module.css";

type ConfirmDialogProps = {
  open: boolean;
  title: string; // names what will happen, e.g. "Cancel EXP-0042?"
  children: ReactNode; // what it does, and what's kept
  confirmLabel: string; // the action in words, e.g. "Cancel the experiment"
  cancelLabel?: string; // e.g. "Keep running"
  danger?: boolean;
  pending?: boolean;
  error?: string; // the API's message when the action failed
  onConfirm: () => void;
  onClose: () => void;
};

/** Asks before anything the app can't undo: stopping a Brev instance, cancelling a job, approving a finger for the robot.
 *  The title and button name what will happen, so nobody confirms blind. Escape or the cancel button closes it. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = "Go back",
  danger = false,
  pending = false,
  error,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={pending}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div>{children}</div>
      {error && <p className={styles.error}>{error}</p>}
    </Modal>
  );
}

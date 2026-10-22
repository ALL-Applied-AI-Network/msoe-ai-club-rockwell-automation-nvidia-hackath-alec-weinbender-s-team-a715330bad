import { useEffect, useId, useRef, type ReactNode } from "react";
import styles from "./Modal.module.css";

type ModalProps = {
  open: boolean;
  title: string;
  children: ReactNode;
  footer?: ReactNode; // the actions, right-aligned, e.g. Cancel and Save
  wide?: boolean; // for forms with two columns
  onClose: () => void; // Escape, or the caller's cancel button
};

/** A dialog over the page, for a short form or a question: recording a printed finger, uploading a part. Built on the
 *  native <dialog>, so focus, Escape and the backdrop behave as the browser does. */
export function Modal({ open, title, children, footer, wide = false, onClose }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog ref={ref} className={`${styles.dialog} ${wide ? styles.wide : ""}`} onClose={onClose} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        {title}
      </h2>
      <div className={styles.body}>{children}</div>
      {footer && <div className={styles.footer}>{footer}</div>}
    </dialog>
  );
}

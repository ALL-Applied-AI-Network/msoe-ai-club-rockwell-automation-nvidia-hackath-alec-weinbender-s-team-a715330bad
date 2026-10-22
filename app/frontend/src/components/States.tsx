import type { ReactNode } from "react";
import { Button } from "./Button";
import styles from "./States.module.css";

/** What a list or section shows when it has nothing yet: what will be here, and how to get it. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={styles.box}>
      <p className={styles.title}>{title}</p>
      {children && <div className={styles.body}>{children}</div>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}

/** What a list or section shows when its data couldn't load: the API's message, and a way to try again. */
export function ErrorState({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className={`${styles.box} ${styles.error}`} role="alert">
      <p className={styles.title}>{title}</p>
      <p className={styles.body}>{message}</p>
      {onRetry && (
        <div className={styles.action}>
          <Button variant="secondary" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
    </div>
  );
}

/** A placeholder block while data loads, sized like what it stands in for. */
export function Skeleton({ height }: { height: number }) {
  return <div className={styles.skeleton} style={{ height }} aria-hidden="true" />;
}

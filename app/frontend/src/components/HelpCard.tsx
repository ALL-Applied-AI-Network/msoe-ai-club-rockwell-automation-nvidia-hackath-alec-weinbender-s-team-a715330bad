import type { ReactNode } from "react";
import styles from "./HelpCard.module.css";

type HelpCardProps = {
  message: string; // the error as the API sent it, shown as it is
  meaning: string; // what it means, in a sentence
  fix: ReactNode[]; // what to do, in order
  reference?: ReactNode; // where it's written up, e.g. "SETUP.md, MSOE VPN"
  action?: ReactNode; // a button: Try again, or the one that fixes it
  tone?: "bad" | "warn";
};

/** An error turned into a next step (frontend-plan.md, 4.5): the message, what it means, the fix, where to read more,
 *  and a button. Used beside every GPU error, and anywhere else an error has a known fix. */
export function HelpCard({ message, meaning, fix, reference, action, tone = "bad" }: HelpCardProps) {
  return (
    <div className={`${styles.card} ${styles[tone]}`} role={tone === "bad" ? "alert" : "status"}>
      <p className={styles.meaning}>{meaning}</p>
      <p className={styles.message}>{message}</p>
      {fix.length > 0 && (
        <ol className={styles.fix}>
          {fix.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      )}
      {(reference || action) && (
        <div className={styles.footer}>
          {reference && <span className={styles.reference}>{reference}</span>}
          {action && <div className={styles.action}>{action}</div>}
        </div>
      )}
    </div>
  );
}

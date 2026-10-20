import styles from "./StatusBadge.module.css";

export type Tone = "neutral" | "active" | "ok" | "warn" | "bad";

/** A short status word in a pill, coloured by what it means: the same badge for the same status everywhere. */
export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{label}</span>;
}

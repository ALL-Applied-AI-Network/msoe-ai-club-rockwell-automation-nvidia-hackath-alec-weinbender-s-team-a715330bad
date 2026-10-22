import styles from "./Badge.module.css";

export type Tone = "neutral" | "active" | "ok" | "warn" | "bad";

type BadgeProps = {
  tone: Tone;
  label: string;
  dot?: boolean; // a status dot before the label; it pulses for the active tone
  title?: string; // a longer explanation on hover
};

/** A short status word in a pill, coloured by what it means. The app's one badge: job status, sim backend, sim path and
 *  physical results all use it (Badges.tsx maps each to a tone and label), so the same status always looks the same. */
export function Badge({ tone, label, dot = false, title }: BadgeProps) {
  return (
    <span className={`${styles.badge} ${styles[tone]}`} title={title}>
      {dot && <span className={styles.dot} aria-hidden="true" />}
      {label}
    </span>
  );
}

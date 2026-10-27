import styles from "./ProgressBar.module.css";

type ProgressBarProps = {
  value: number; // 0 to 1
  label: string; // what it measures, for screen readers, e.g. "Designs evaluated"
  tone?: "acc" | "active" | "warn"; // acc: results and done; active: work under way; warn: waiting on the GPU connection
};

/** How far along something is. */
export function ProgressBar({ value, label, tone = "acc" }: ProgressBarProps) {
  const clamped = Math.min(1, Math.max(0, value));
  return (
    <div className={styles.track} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(clamped * 100)}>
      <div className={`${styles.fill} ${styles[tone]}`} style={{ width: `${clamped * 100}%` }} />
    </div>
  );
}

import type { ReactNode } from "react";
import styles from "./Stat.module.css";

type StatProps = {
  label: string;
  value: ReactNode; // already formatted through format.ts, with its unit
  detail?: ReactNode; // a line under the value, e.g. "capture radius 5.0 mm"
  size?: "sm" | "lg";
  tone?: "ink" | "acc" | "bad"; // acc for the winning design, bad for a baseline
};

/** One number with its label: progress on job cards, the summary on the results page. */
export function Stat({ label, value, detail, size = "sm", tone = "ink" }: StatProps) {
  return (
    <div className={styles.stat}>
      <div className={styles.label}>{label}</div>
      <div className={`${styles.value} ${styles[size]} ${styles[tone]}`}>{value}</div>
      {detail && <div className={styles.detail}>{detail}</div>}
    </div>
  );
}

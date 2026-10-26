import type { ReactNode } from "react";
import { percent } from "../format";
import styles from "./Score.module.css";

const SEGMENTS = 10;

type ScoreProps = {
  value: number | null | undefined; // a success rate, 0 to 1; null: nothing yet
  look?: "dot" | "meter"; // dot: a coloured dot before the number (work under way); meter: the segmented meter (a result)
  sub?: ReactNode; // a line under it, e.g. "stock 61%"
  label?: string; // what it scores, for screen readers
  size?: "md" | "lg"; // lg: a page's headline numbers, e.g. the results summary
};

/** A grasp success rate, the app's one headline number: green from 70%, amber from 40%, red below. As a result it's a
 *  segmented meter, ten segments lit to the score, like the bar graphs on a cell's operator panel. The same everywhere
 *  a success rate shows. */
export function Score({ value, look = "meter", sub, label = "Grasp success", size = "md" }: ScoreProps) {
  if (value == null) return <span className={styles.none}>No score yet</span>;
  const tone = value >= 0.7 ? "ok" : value >= 0.4 ? "warn" : "bad";
  const lit = Math.round(Math.min(1, Math.max(0, value)) * SEGMENTS);
  return (
    <div className={`${styles.score} ${styles[tone]} ${size === "lg" ? styles.lg : ""}`}>
      <span className={styles.line}>
        {look === "dot" && <span className={styles.dot} aria-hidden="true" />}
        <span className={styles.value}>{percent(value)}</span>
      </span>
      {look === "meter" && (
        <span className={styles.meter} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
          {Array.from({ length: SEGMENTS }, (_, i) => (
            <span key={i} className={i < lit ? styles.on : styles.off} />
          ))}
        </span>
      )}
      {sub && <span className={styles.sub}>{sub}</span>}
    </div>
  );
}

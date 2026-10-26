import type { ReactNode } from "react";
import { Badge, type Tone } from "../../components/Badge";
import styles from "./Stage.module.css";

type StageProps = {
  step: number;
  title: string;
  status: { tone: Tone; label: string }; // where this stage stands, e.g. "2 of 3 printed"
  description?: ReactNode;
  children: ReactNode;
};

/** One stage of an experiment's validation, numbered, with where it stands. The page shows the six in order. */
export function Stage({ step, title, status, description, children }: StageProps) {
  return (
    <section className={styles.stage} aria-labelledby={`stage-${step}`}>
      <div className={styles.rail} aria-hidden="true">
        <span className={`${styles.number} ${status.tone === "ok" ? styles.done : ""}`}>{step}</span>
      </div>
      <div className={styles.main}>
        <header className={styles.header}>
          <div>
            <h2 id={`stage-${step}`} className={styles.title}>
              {title}
            </h2>
            {description && <p className={styles.description}>{description}</p>}
          </div>
          <Badge tone={status.tone} label={status.label} dot={status.tone === "active"} />
        </header>
        <div className={styles.body}>{children}</div>
      </div>
    </section>
  );
}

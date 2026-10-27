import type { ReactNode } from "react";
import { Link } from "react-router";
import styles from "./StepLayout.module.css";

export type StepStatus = "done" | "current" | "attention" | "blocked" | "todo";

export type StepItem = {
  key: string;
  label: string;
  to: string; // the step's own address, so browser Back works and a failure can link to it
  status: StepStatus;
  note?: string; // why it needs attention or is blocked: a tooltip on the step (the rail stays one word per step)
};

type StepLayoutProps = {
  steps: StepItem[];
  current: number; // index into steps
  title: string;
  description?: ReactNode;
  children: ReactNode; // the step's content
  rail?: ReactNode; // the summary at the right: the choices so far and the run estimate
  footer?: ReactNode; // Back and Next
};

const STATUS_LABEL: Record<StepStatus, string> = {
  done: "done",
  current: "current step",
  attention: "needs attention",
  blocked: "blocked",
  todo: "not done yet",
};

/** The layout every wizard step shares: the step list down the side, the step in the middle, a summary rail at the
 *  right, Back and Next at the bottom. On narrow screens the list becomes a row above the step and the rail drops
 *  below it. */
export function StepLayout({ steps, current, title, description, children, rail, footer }: StepLayoutProps) {
  return (
    <div className={styles.layout}>
      <nav className={styles.steps} aria-label="Steps">
        <ol className={styles.list}>
          {steps.map((step, i) => (
            <li key={step.key}>
              <Link
                to={step.to}
                className={`${styles.step} ${styles[step.status]}`}
                aria-current={i === current ? "step" : undefined}
                title={step.note}
              >
                <span className={styles.number} aria-hidden="true">
                  {i + 1}
                </span>
                <span className={styles.text}>
                  <span className={styles.label}>{step.label}</span>
                  <span className={styles.visuallyHidden}>, {STATUS_LABEL[step.status]}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </nav>

      <section className={styles.main} aria-labelledby="step-title">
        <header className={styles.header}>
          <h2 id="step-title" className={styles.title}>
            {title}
          </h2>
          {description && <p className={styles.description}>{description}</p>}
        </header>
        <div className={styles.content}>{children}</div>
        {footer && <footer className={styles.footer}>{footer}</footer>}
      </section>

      {rail && <aside className={styles.rail}>{rail}</aside>}
    </div>
  );
}

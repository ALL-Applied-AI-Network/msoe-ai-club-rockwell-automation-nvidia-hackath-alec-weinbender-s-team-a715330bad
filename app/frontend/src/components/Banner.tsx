import type { ReactNode } from "react";
import styles from "./Banner.module.css";

type BannerProps = {
  tone: "info" | "warn" | "bad";
  title?: string;
  children: ReactNode;
  action?: ReactNode; // a button or link at the right, e.g. "Reset" or "Connect a GPU"
  strip?: boolean; // full width with no rounded border, for page-wide notices under the top bar
};

/** A notice in a tone: demo data, the mock sim, caveats beside the numbers they qualify, a re-scored view. */
export function Banner({ tone, title, children, action, strip = false }: BannerProps) {
  return (
    <div className={[styles.banner, styles[tone], strip && styles.strip].filter(Boolean).join(" ")} role={tone === "bad" ? "alert" : "status"}>
      <div className={styles.text}>
        {title && <strong className={styles.title}>{title}</strong>}
        <span>{children}</span>
      </div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}

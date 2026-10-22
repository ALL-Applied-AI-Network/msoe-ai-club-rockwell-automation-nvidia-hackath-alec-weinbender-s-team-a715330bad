import type { ReactNode } from "react";
import styles from "./Card.module.css";

type CardProps = {
  title?: ReactNode; // a heading, or a link for cards that open a page
  subtitle?: ReactNode; // a line under the title, e.g. an ID
  aside?: ReactNode; // at the right of the title, e.g. a badge
  footer?: ReactNode; // a bar under a divider, e.g. timestamps and actions
  children?: ReactNode;
};

/** A bordered surface: every page's content sits in cards. */
export function Card({ title, subtitle, aside, footer, children }: CardProps) {
  return (
    <section className={styles.card}>
      {(title || aside) && (
        <header className={styles.header}>
          <div className={styles.heading}>
            {title && <h2 className={styles.title}>{title}</h2>}
            {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
          </div>
          {aside && <div className={styles.aside}>{aside}</div>}
        </header>
      )}
      {children && <div className={styles.body}>{children}</div>}
      {footer && <footer className={styles.footer}>{footer}</footer>}
    </section>
  );
}

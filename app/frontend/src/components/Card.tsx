import type { ReactNode } from "react";
import { Link } from "react-router";
import { Icon, type IconName } from "./Icon";
import styles from "./Card.module.css";

type CardProps = {
  title?: ReactNode; // a heading, or a link for cards that open a page
  subtitle?: ReactNode; // a line under the title, e.g. an ID
  icon?: IconName; // drawn before the title, for the panels of a dashboard
  aside?: ReactNode; // at the right of the title, e.g. a badge or a button
  more?: { to: string; label: string }; // a link at the right of the title to the whole list, e.g. "View all"
  footer?: ReactNode; // a bar under a divider, e.g. timestamps and actions
  flush?: boolean; // the body runs to the card's edges, for a table or a list of rows that draw their own padding
  children?: ReactNode;
};

/** A bordered panel with a heading: every page's content sits in cards. */
export function Card({ title, subtitle, icon, aside, more, footer, flush = false, children }: CardProps) {
  return (
    <section className={styles.card}>
      {(title || aside || more) && (
        <header className={styles.header}>
          <div className={styles.heading}>
            {icon && (
              <span className={styles.icon}>
                <Icon name={icon} />
              </span>
            )}
            <div className={styles.titles}>
              {title && <h2 className={styles.title}>{title}</h2>}
              {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
            </div>
          </div>
          {(aside || more) && (
            <div className={styles.aside}>
              {aside}
              {more && (
                <Link to={more.to} className={styles.more}>
                  {more.label}
                </Link>
              )}
            </div>
          )}
        </header>
      )}
      {children && <div className={flush ? styles.flush : styles.body}>{children}</div>}
      {footer && <footer className={styles.footer}>{footer}</footer>}
    </section>
  );
}

import type { ReactNode } from "react";
import styles from "./Card.module.css";

type CardProps = {
  title: string;
  aside?: ReactNode; // shown at the right of the title, e.g. a badge
  children: ReactNode;
};

/** A titled section: every page's content sits in cards. */
export function Card({ title, aside, children }: CardProps) {
  return (
    <section className={styles.card}>
      <header className={styles.header}>
        <h2 className={styles.title}>{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  );
}

import { useEffect, useState } from "react";
import { Link } from "react-router";
import styles from "./JobRail.module.css";

export type RailSection = { id: string; label: string };

/** The experiment page's slim side list: one word per section, the one in view filled, and a last link to the physical
 *  validation. A click scrolls to the section (the app uses hash routes, so a #anchor link would change the page). */
export function JobRail({ sections, validationTo }: { sections: RailSection[]; validationTo: string }) {
  const [active, setActive] = useState(sections[0]?.id ?? "");
  const key = sections.map((s) => s.id).join();

  useEffect(() => {
    const visible = new Set<string>();
    const watch = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        const first = sections.find((s) => visible.has(s.id));
        if (first) setActive(first.id);
      },
      { rootMargin: "-20% 0px -60% 0px" },
    );
    for (const { id } of sections) {
      const element = document.getElementById(id);
      if (element) watch.observe(element);
    }
    return () => watch.disconnect();
    // `key` stands for the list of sections, which a parent rebuilds on every render
  }, [key]);

  const at = sections.findIndex((s) => s.id === active);
  return (
    <nav className={styles.rail} aria-label="Sections">
      <ol className={styles.list}>
        {sections.map((section, i) => (
          <li key={section.id}>
            <button
              type="button"
              className={`${styles.step} ${i < at ? styles.done : ""} ${i === at ? styles.current : ""}`}
              aria-current={i === at ? "location" : undefined}
              onClick={() => document.getElementById(section.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
            >
              <span className={styles.number} aria-hidden="true">
                {i + 1}
              </span>
              <span className={styles.label}>{section.label}</span>
            </button>
          </li>
        ))}
        <li>
          <Link to={validationTo} className={styles.step}>
            <span className={styles.number} aria-hidden="true">
              {sections.length + 1}
            </span>
            <span className={styles.label}>Validate</span>
          </Link>
        </li>
      </ol>
    </nav>
  );
}

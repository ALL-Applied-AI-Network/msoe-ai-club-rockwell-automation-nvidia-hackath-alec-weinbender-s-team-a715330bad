import { NavLink } from "react-router";
import styles from "./Tabs.module.css";

type Tab = { to: string; label: string; end?: boolean; count?: number };

/** Links to the sections of one page, each its own address: Settings' sections, an experiment's results and validation.
 *  The current one is underlined, like the top bar. */
export function Tabs({ tabs, label }: { tabs: Tab[]; label: string }) {
  return (
    <nav className={styles.tabs} aria-label={label}>
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) => [styles.tab, isActive && styles.current].filter(Boolean).join(" ")}
        >
          {tab.label}
          {tab.count !== undefined && <span className={styles.count}>{tab.count}</span>}
        </NavLink>
      ))}
    </nav>
  );
}

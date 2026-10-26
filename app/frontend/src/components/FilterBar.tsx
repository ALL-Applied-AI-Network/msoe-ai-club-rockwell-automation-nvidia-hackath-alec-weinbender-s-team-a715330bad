import type { ReactNode } from "react";
import { Card } from "./Card";
import styles from "./FilterBar.module.css";

/** A list's filters in one panel, on one line: the chips (a Segmented) on the left, then the selects (`inline`) and the
 *  search box on the right. Every list page has the same bar: the overview, jobs, the part and finger libraries. */
export function FilterBar({ chips, children }: { chips: ReactNode; children?: ReactNode }) {
  return (
    <Card>
      <div className={styles.bar}>
        {chips}
        {children && <div className={styles.right}>{children}</div>}
      </div>
    </Card>
  );
}

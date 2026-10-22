import type { ReactNode } from "react";
import { CAVEATS } from "../caveats";
import { Badge } from "./Badge";
import styles from "./KeyValues.module.css";

export type KeyValue = {
  label: string;
  value: ReactNode; // formatted, with its unit
  placeholder?: boolean; // not measured yet: marked "Placeholder"
  mono?: boolean; // IDs and codes
};

/** Read-only facts as label and value pairs: a part's size and mass, a cell profile's numbers. `inline` sets them on one
 *  wrapping row (cards); otherwise they form a two-column grid. */
export function KeyValues({ items, inline = false }: { items: KeyValue[]; inline?: boolean }) {
  return (
    <dl className={`${styles.list} ${inline ? styles.inline : styles.grid}`}>
      {items.map((item) => (
        <div key={item.label} className={styles.item}>
          <dt>{item.label}</dt>
          <dd className={item.mono ? styles.mono : undefined}>
            {item.value}
            {item.placeholder && <Badge tone="warn" label="Placeholder" title={CAVEATS.placeholderCell} />}
          </dd>
        </div>
      ))}
    </dl>
  );
}

import { useState, type ReactNode } from "react";
import styles from "./Table.module.css";

export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => number | string | null | undefined; // makes the column sortable
  align?: "left" | "right"; // right for numbers
  width?: string; // a CSS width, e.g. "120px"
};

type TableProps<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  label: string; // what the table lists, for screen readers
  selected?: Set<string>; // with onSelect: a tick box column, e.g. the final-test table's "print this"
  onSelect?: (key: string, selected: boolean) => void;
  selectLabel?: string; // the tick box column's header, e.g. "Print"
  rowTone?: (row: T) => "bad" | "warn" | undefined; // tints a row, e.g. an upload error
  empty?: ReactNode; // shown in place of the rows when there are none
  fixed?: boolean; // columns keep the widths given (percentages), and long text wraps inside its cell, so the table never overflows
};

/** The app's one table: the session log, the final-test table, upload errors, cell-profile versions. Click a sortable
 *  header to sort by it; click again to reverse. */
export function Table<T>({ columns, rows, rowKey, label, selected, onSelect, selectLabel = "Select", rowTone, empty, fixed = false }: TableProps<T>) {
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const column = sort && columns.find((c) => c.key === sort.key);
  const sorted =
    column?.sortValue && sort
      ? [...rows].sort((a, b) => compare(column.sortValue!(a), column.sortValue!(b)) * (sort.desc ? -1 : 1))
      : rows;
  const toggle = (key: string) => setSort((s) => (s?.key === key ? { key, desc: !s.desc } : { key, desc: false }));

  return (
    <div className={styles.scroll}>
      <table className={`${styles.table} ${fixed ? styles.fixed : ""}`} aria-label={label}>
        <thead>
          <tr>
            {onSelect && <th className={styles.select}>{selectLabel}</th>}
            {columns.map((c) => (
              <th
                key={c.key}
                className={c.align === "right" ? styles.right : undefined}
                style={c.width ? { width: c.width } : undefined}
                aria-sort={sort?.key === c.key ? (sort.desc ? "descending" : "ascending") : undefined}
              >
                {c.sortValue ? (
                  <button type="button" className={styles.sort} onClick={() => toggle(c.key)}>
                    {c.header}
                    <span className={styles.sortMark} aria-hidden="true" data-dir={sort?.key === c.key ? (sort.desc ? "desc" : "asc") : "none"} />
                  </button>
                ) : (
                  c.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && empty !== undefined && (
            <tr>
              <td className={styles.empty} colSpan={columns.length + (onSelect ? 1 : 0)}>
                {empty}
              </td>
            </tr>
          )}
          {sorted.map((row) => {
            const key = rowKey(row);
            const tone = rowTone?.(row);
            return (
              <tr key={key} className={tone ? styles[tone] : undefined}>
                {onSelect && (
                  <td className={styles.select}>
                    <input
                      type="checkbox"
                      checked={selected?.has(key) ?? false}
                      onChange={(event) => onSelect(key, event.target.checked)}
                      aria-label={`${selectLabel} ${key}`}
                    />
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.key} className={c.align === "right" ? styles.right : undefined}>
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function compare(a: number | string | null | undefined, b: number | string | null | undefined): number {
  if (a == null) return b == null ? 0 : 1; // blanks last
  if (b == null) return -1;
  return typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
}

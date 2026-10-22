import type { ReactNode } from "react";
import { useChartColors, type ChartColor } from "./chartColors";
import { MarkSwatch, type MarkShapeName } from "./MarkShape";
import styles from "./ChartFrame.module.css";

export type LegendItem = {
  label: string;
  description?: string; // what it means, in words, e.g. "the sim held it, the robot missed"
  color: ChartColor;
  shape: MarkShapeName;
};

type ChartFrameProps = {
  summary: string; // the text alternative: what the chart shows and its main finding, for screen readers
  legend?: LegendItem[]; // two or more series or categories; a single series needs none
  note?: ReactNode; // a caveat or a "how to read it" line under the chart
  children: ReactNode; // the chart itself
};

/** Every chart sits in one: the chart, its legend in words, a note, and a text alternative. */
export function ChartFrame({ summary, legend, note, children }: ChartFrameProps) {
  const colors = useChartColors();
  return (
    <figure className={styles.figure}>
      <p className={styles.srOnly}>{summary}</p>
      <div aria-hidden="true">{children}</div>
      {legend && legend.length > 0 && (
        <ul className={styles.legend}>
          {legend.map((item) => (
            <li key={item.label} className={styles.legendItem}>
              <MarkSwatch shape={item.shape} color={colors[item.color]} ring={colors.surface} />
              <span>
                <span className={styles.legendLabel}>{item.label}</span>
                {item.description && <span className={styles.legendDescription}>{item.description}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {note && <figcaption className={styles.note}>{note}</figcaption>}
    </figure>
  );
}

/** The hover readout: values lead, labels follow. */
export function ChartTooltip({ title, rows }: { title: string; rows: { label: string; value: ReactNode }[] }) {
  return (
    <div className={styles.tooltip}>
      <div className={styles.tooltipTitle}>{title}</div>
      {rows.map((row) => (
        <div key={row.label} className={styles.tooltipRow}>
          <strong>{row.value}</strong>
          <span>{row.label}</span>
        </div>
      ))}
    </div>
  );
}

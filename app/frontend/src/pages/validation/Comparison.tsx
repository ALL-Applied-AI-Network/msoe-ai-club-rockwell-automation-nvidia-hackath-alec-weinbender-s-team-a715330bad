import { useState } from "react";
import type { Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { DownloadButton } from "../../components/DownloadButton";
import { DotGridMap, type DotCategory, type GridDot } from "../../components/charts/DotGridMap";
import { IntervalChart, type IntervalRow } from "../../components/charts/IntervalChart";
import { Segmented } from "../../components/Segmented";
import { EmptyState } from "../../components/States";
import { Table, type Column } from "../../components/Table";
import { CAVEATS } from "../../caveats";
import { degrees, of, percent } from "../../format";
import { designLabel } from "../../labels";
import styles from "./JobValidationPage.module.css";

type Validation = Schemas["Validation"];
type DesignValidation = Schemas["DesignValidation"];
type Mismatch = Schemas["MismatchPoint"];

/** What each mismatch status means, with its colour and shape. Shape carries it as well as colour, so the map reads
 *  without colour vision too. */
export const MISMATCH_CATEGORIES: DotCategory[] = [
  { key: "agreed", label: "Agreed", description: "The sim and the robot gave the same outcome.", color: "ok", shape: "dot" },
  {
    key: "sim_only",
    label: "Sim only",
    description: "The sim held it and the robot missed: the sim is too optimistic here.",
    color: "bad",
    shape: "diamond",
  },
  {
    key: "real_only",
    label: "Robot only",
    description: "The robot held it and the sim missed: the sim is too cautious here.",
    color: "warn",
    shape: "square",
  },
  {
    key: "mixed",
    label: "Mixed",
    description: "The repeats on the robot disagreed with each other.",
    color: "active",
    shape: "triangle",
  },
  { key: "pending", label: "Pending", description: "Not tested on the robot yet.", color: "faint", shape: "ring" },
];

const COLUMNS: Column<DesignValidation>[] = [
  {
    key: "design",
    header: "Design",
    sortValue: (d) => d.design_label,
    render: (d) => <strong className={styles.design}>{designLabel(d.design_label)}</strong>,
  },
  {
    key: "fingers",
    header: "Fingers",
    render: (d) => (d.finger_ids.length ? <code>{d.finger_ids.join(", ")}</code> : "none recorded"),
  },
  {
    key: "predicted",
    header: "Predicted",
    align: "right",
    sortValue: (d) => d.predicted_success,
    render: (d) => (d.predicted_success == null ? "none" : percent(d.predicted_success)),
  },
  {
    key: "measured",
    header: "Measured",
    align: "right",
    sortValue: (d) => d.measured_success,
    render: (d) => (d.measured_success == null ? "none yet" : percent(d.measured_success)),
  },
  {
    key: "interval",
    header: "95% interval",
    align: "right",
    render: (d) => (d.wilson_low == null || d.wilson_high == null ? "none" : `${percent(d.wilson_low)} to ${percent(d.wilson_high)}`),
  },
  {
    key: "logged",
    header: "Logged",
    align: "right",
    sortValue: (d) => d.logged,
    render: (d) => `${of(d.logged, d.planned)}${d.skipped ? `, ${d.skipped} skipped` : ""}`,
  },
  { key: "agreement", header: "Agreement", render: (d) => d.summary },
];

/** Predicted against measured, per design and per offset, once trials are logged. */
export function Comparison({
  jobId,
  experimentId,
  validation,
  simBackend,
}: {
  jobId: string;
  experimentId: string;
  validation: Validation;
  simBackend: "mock" | "isaac";
}) {
  const logged = validation.designs.some((d) => d.logged > 0);
  const exportQuery = `job_id=${encodeURIComponent(jobId)}`;

  if (!logged) {
    return (
      <EmptyState title="No trials logged yet">
        Upload outcomes to compare each design with the sim.
      </EmptyState>
    );
  }

  const rows: IntervalRow[] = validation.designs.map((d) => ({
    key: d.design_label,
    label: designLabel(d.design_label),
    predicted: d.predicted_success,
    measured: d.measured_success,
    low: d.wilson_low,
    high: d.wilson_high,
    n: d.n,
  }));
  const summary =
    `${experimentId}: predicted against measured success per design. ` +
    validation.designs
      .map(
        (d) =>
          `${designLabel(d.design_label)}: predicted ${d.predicted_success == null ? "none" : percent(d.predicted_success)}, ` +
          `measured ${d.measured_success == null ? "none yet" : percent(d.measured_success)}; ${d.summary}.`,
      )
      .join(" ");

  return (
    <div className={styles.comparison}>
      <h3 className={styles.panelTitle}>Predicted against measured</h3>
      {simBackend === "mock" && <Banner tone="warn">{CAVEATS.mock} The predictions here come from the mock sim.</Banner>}
      <IntervalChart
        rows={rows}
        summary={summary}
        note="Where the ring falls outside the measured interval, the sim's prediction is off by more than the trials can explain."
      />
      <Table label="Validation per design" columns={COLUMNS} rows={validation.designs} rowKey={(d) => d.design_label} />
      <MismatchMap mismatches={validation.mismatches} experimentId={experimentId} />
      <div className={styles.actions}>
        <DownloadButton href={`/api/export/physical.csv?${exportQuery}`} label="Download the trials (.csv)" />
        <DownloadButton href={`/api/export/physical.jsonl?${exportQuery}`} label="Download the trials (.jsonl)" />
      </div>
    </div>
  );
}

/** Each tested offset of one design, marked by whether the sim and the robot agreed there. */
function MismatchMap({ mismatches, experimentId }: { mismatches: Mismatch[]; experimentId: string }) {
  const designs = [...new Set(mismatches.map((m) => m.design_label))];
  const [chosen, setChosen] = useState("");
  const design = designs.includes(chosen) ? chosen : (designs[0] ?? "");
  const ofDesign = mismatches.filter((m) => m.design_label === design);
  const yaws = [...new Set(ofDesign.map((m) => m.yaw_deg))].sort((a, b) => a - b);
  const [chosenYaw, setChosenYaw] = useState<string>("");
  const yaw = yaws.map(String).includes(chosenYaw) ? Number(chosenYaw) : (yaws[0] ?? 0);
  const shown = ofDesign.filter((m) => m.yaw_deg === yaw);
  if (designs.length === 0) return null;

  const dots: GridDot[] = shown.map((m, i) => ({
    key: `${m.kind}-${m.offset_x_mm}-${m.offset_y_mm}-${i}`,
    x: m.offset_x_mm,
    y: m.offset_y_mm,
    category: m.status,
    title: `${designLabel(m.design_label)}, ${m.kind === "pointwise" ? "point-wise" : "random"} offset`,
    details: [
      { label: "sim", value: m.predicted == null ? "no prediction" : m.predicted ? "held" : "missed" },
      {
        label: "robot",
        value: m.measured_rate == null ? "not tested" : `held ${percent(m.measured_rate)} of ${m.repeats} tries`,
      },
      ...(yaws.length > 1 ? [{ label: "yaw", value: degrees(m.yaw_deg) }] : []),
    ],
  }));
  const counts = MISMATCH_CATEGORIES.map((c) => `${shown.filter((m) => m.status === c.key).length} ${c.label.toLowerCase()}`);

  return (
    <div className={styles.panel}>
      <div className={styles.mapHeader}>
        <div>
          <h3 className={styles.panelTitle}>Where the sim and the robot disagree</h3>
          <p className={styles.note}>Every tested offset, from above, marked by whether the sim and the robot agree.</p>
        </div>
        <div className={styles.mapControls}>
          {designs.length > 1 && (
            <Segmented
              label="Design"
              value={design}
              onChange={setChosen}
              options={designs.map((d) => ({ value: d, label: designLabel(d) }))}
            />
          )}
          {yaws.length > 1 && (
            <Segmented
              label="Yaw layer"
              value={String(yaw)}
              onChange={setChosenYaw}
              options={yaws.map((y) => ({ value: String(y), label: `Yaw ${degrees(y)}` }))}
            />
          )}
        </div>
      </div>
      <DotGridMap
        dots={dots}
        categories={MISMATCH_CATEGORIES}
        summary={`${experimentId}, design ${designLabel(design)}: ${dots.length} tested offsets; ${counts.join(", ")}.`}
      />
    </div>
  );
}

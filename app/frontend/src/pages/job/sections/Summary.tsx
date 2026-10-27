import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import type { Schemas } from "../../../backend/client";
import { mm, percent, points } from "../../../format";
import { designLabel } from "../../../labels";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type Score = Schemas["DesignScore"];
type PoseScore = Schemas["PoseScore"];

/** The headline: the best design against the stock fingers and the imprint at the target camera error, with how far
 *  off centre each still catches the part. */
export function Summary({ results }: { results: Results }) {
  const summary = results.summary!;
  const { best, stock, imprint, task_metric_label: metricLabel } = summary;
  const sigma = results.header.error.sigma_mm;
  const rows: Row[] = [
    { key: "best", name: designLabel(best.label), sub: "best design", score: best, versus: summary.gain_vs_stock },
    ...(imprint
      ? [{ key: "imprint", name: "Imprint", sub: "baseline", score: imprint, versus: stock ? imprint.success - stock.success : null }]
      : []),
    ...(stock ? [{ key: "stock", name: "Stock fingers", sub: "baseline", score: stock, versus: null }] : []),
  ];
  const columns: Column<Row>[] = [
    {
      key: "finger",
      header: "Finger",
      render: (r) => (
        <>
          <strong>{r.name}</strong>
          <span className={styles.sub}>{r.sub}</span>
        </>
      ),
    },
    {
      key: "success",
      header: "Held",
      width: "38%",
      render: (r) => (
        <span className={styles.meter}>
          <span className={styles.track}>
            <span className={r.key === "best" ? styles.fillBest : styles.fillBase} style={{ width: percent(r.score.success) }} />
          </span>
          <strong className={styles.meterValue}>{percent(r.score.success)}</strong>
        </span>
      ),
    },
    {
      key: "radius",
      header: "Capture radius",
      render: (r) => (r.score.capture_radius_mm == null ? "none" : mm(r.score.capture_radius_mm)),
    },
    ...(metricLabel
      ? [{ key: "metric", header: metricLabel, render: (r: Row) => (r.score.task_metric == null ? "" : percent(r.score.task_metric)) }]
      : []),
    {
      key: "versus",
      header: "Vs stock",
      align: "right" as const,
      render: (r) => (r.versus == null ? "" : <span className={r.key === "best" ? styles.gain : undefined}>{points(r.versus)}</span>),
    },
  ];

  return (
    <Card
      title={`Share of grasps held at σ ${mm(sigma)}`}
      aside={<span className={styles.note}>{summary.designs_evaluated} designs evaluated</span>}
    >
      <Table label="Best design against the baselines" columns={columns} rows={rows} rowKey={(r) => r.key} />
      {best.poses && best.poses.length > 1 && <PoseTable best={best} stock={stock} imprint={imprint} />}
    </Card>
  );
}

type Row = { key: string; name: string; sub: string; score: Score; versus: number | null | undefined };

/** Each pose's share of the score and each design's success in it: the headline numbers are these, weighted. */
function PoseTable({ best, stock, imprint }: { best: Score; stock: Score | null; imprint: Score | null }) {
  const cell = (score: Score | null, key: string) => {
    const pose = score?.poses?.find((p) => p.key === key);
    if (!pose) return "Not tested";
    return (
      <>
        {percent(pose.success)}
        <span className={styles.note}>
          {pose.capture_radius_mm == null ? " no capture radius" : ` capture radius ${mm(pose.capture_radius_mm)}`}
        </span>
      </>
    );
  };
  const columns: Column<PoseScore>[] = [
    { key: "pose", header: "Resting pose", render: (p) => capitalise(p.label ?? "unnamed pose") },
    { key: "share", header: "Share of the score", align: "right", render: (p) => percent(p.weight) },
    { key: "best", header: designLabel(best.label), render: (p) => cell(best, p.key) },
    ...(stock ? [{ key: "stock", header: "Stock fingers", render: (p: PoseScore) => cell(stock, p.key) }] : []),
    ...(imprint ? [{ key: "imprint", header: "Imprint", render: (p: PoseScore) => cell(imprint, p.key) }] : []),
  ];
  return <Table label="Success in each resting pose" columns={columns} rows={best.poses!} rowKey={(p) => p.key} />;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

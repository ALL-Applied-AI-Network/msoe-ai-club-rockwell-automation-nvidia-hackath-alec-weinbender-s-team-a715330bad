import { Card } from "../../../components/Card";
import { Score } from "../../../components/Score";
import { Table, type Column } from "../../../components/Table";
import type { Schemas } from "../../../backend/client";
import { mm, percent, points } from "../../../format";
import { designLabel } from "../../../labels";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type Score = Schemas["DesignScore"];
type PoseScore = Schemas["PoseScore"];

/** The headline: the best design against the stock fingers and the imprint at the target camera error, each as a meter,
 *  with how far off centre it still catches the part and what it gains. */
export function Summary({ results }: { results: Results }) {
  const summary = results.summary!;
  const { best, stock, imprint, task_metric_label: metricLabel } = summary;
  const sigma = results.header.error.sigma_mm;
  const facts = (score: Score, gain?: number | null) => (
    <>
      <span>{score.capture_radius_mm == null ? "No capture radius" : `Capture radius ${mm(score.capture_radius_mm)}`}</span>
      {metricLabel && score.task_metric != null && (
        <span>
          {percent(score.task_metric)} {metricLabel}
        </span>
      )}
      {gain != null && (
        <span>
          {designLabel(best.label)} gains {points(gain)}
        </span>
      )}
    </>
  );

  return (
    <Card title={`Grasps held at a ${mm(sigma)} camera error`} subtitle={`${summary.designs_evaluated} designs evaluated`}>
      <div className={styles.summary}>
        <div className={styles.headline}>
          <span className={styles.headlineLabel}>Best design, {designLabel(best.label)}</span>
          <Score value={best.success} size="lg" label={`${designLabel(best.label)} success`} sub={facts(best)} />
        </div>
        {stock && (
          <div className={styles.headline}>
            <span className={styles.headlineLabel}>Stock fingers</span>
            <Score value={stock.success} size="lg" label="Stock fingers success" sub={facts(stock, summary.gain_vs_stock)} />
          </div>
        )}
        {imprint && (
          <div className={styles.headline}>
            <span className={styles.headlineLabel}>Imprint</span>
            <Score value={imprint.success} size="lg" label="Imprint success" sub={facts(imprint, summary.gain_vs_imprint)} />
          </div>
        )}
      </div>
      {best.poses && best.poses.length > 1 && <PoseTable best={best} stock={stock} imprint={imprint} />}
    </Card>
  );
}

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

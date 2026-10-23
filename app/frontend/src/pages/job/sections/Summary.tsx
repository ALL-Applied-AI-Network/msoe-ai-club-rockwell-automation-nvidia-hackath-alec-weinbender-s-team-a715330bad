import { Card } from "../../../components/Card";
import { Stat } from "../../../components/Stat";
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
  const detail = (score: Score) => (
    <>
      {score.capture_radius_mm == null ? "no capture radius" : `capture radius ${mm(score.capture_radius_mm)}`}
      {metricLabel && score.task_metric != null && (
        <>
          <br />
          {percent(score.task_metric)} {metricLabel}
        </>
      )}
    </>
  );

  return (
    <Card
      title={`Share of grasps held at σ ${mm(sigma)}`}
      aside={<span className={styles.note}>{summary.designs_evaluated} designs evaluated</span>}
    >
      <div className={styles.summary}>
        <Stat size="lg" tone="acc" label={`Best design, ${designLabel(best.label)}`} value={percent(best.success)} detail={detail(best)} />
        {stock && (
          <Stat
            size="lg"
            label="Stock fingers"
            value={percent(stock.success)}
            detail={
              <>
                {detail(stock)}
                {summary.gain_vs_stock != null && (
                  <>
                    <br />
                    {designLabel(best.label)}: {points(summary.gain_vs_stock)}
                  </>
                )}
              </>
            }
          />
        )}
        {imprint && (
          <Stat
            size="lg"
            label="Imprint"
            value={percent(imprint.success)}
            detail={
              <>
                {detail(imprint)}
                {summary.gain_vs_imprint != null && (
                  <>
                    <br />
                    {designLabel(best.label)}: {points(summary.gain_vs_imprint)}
                  </>
                )}
              </>
            }
          />
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
